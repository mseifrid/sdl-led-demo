"""Tiny MQTT 3.1.1 client for the simulated Pico W (MicroPython).

Just enough for this demo: connect (optionally with TLS and a username and
password), subscribe, publish, and poll for incoming messages. Also runs on
regular Python, which is how it is tested on a laptop.
"""

import socket
import struct
import time

try:
    import select
except ImportError:  # very old MicroPython
    import uselect as select


class MQTTError(Exception):
    pass


class MQTTClient:
    def __init__(self, client_id, server, port=8883, user=None, password=None,
                 keepalive=60, ssl=True):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user or None
        self.password = password or ""
        self.keepalive = keepalive
        self.use_ssl = ssl
        self.sock = None
        self.poller = None
        self.pid = 0
        self.last_ping = time.time()
        self.cb = None

    # ---------- low-level helpers ----------
    def _send(self, data):
        view = memoryview(data)
        while len(view):
            n = self.sock.write(view)
            if n is None:  # not ready yet
                continue
            view = view[n:]

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.read(n - len(buf))
            if chunk is None:  # not ready yet (non-blocking read)
                time.sleep(0.01)
                continue
            if not chunk:
                raise MQTTError("Connection closed by broker")
            buf += chunk
        return buf

    @staticmethod
    def _str(s):
        b = s.encode() if isinstance(s, str) else s
        return struct.pack("!H", len(b)) + b

    @staticmethod
    def _remaining_length(n):
        out = bytearray()
        while True:
            byte = n & 0x7F
            n >>= 7
            out.append(byte | (0x80 if n else 0))
            if not n:
                return bytes(out)

    def _read_remaining_length(self):
        n, shift = 0, 0
        while True:
            b = self._recv(1)[0]
            n |= (b & 0x7F) << shift
            if not b & 0x80:
                return n
            shift += 7

    def _packet(self, first_byte, body):
        self._send(bytes([first_byte]) + self._remaining_length(len(body)) + body)

    # ---------- public API ----------
    def set_callback(self, cb):
        """cb(topic: bytes, payload: bytes) is called for each message."""
        self.cb = cb

    def connect(self):
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        raw = socket.socket()
        raw.connect(addr)
        if self.use_ssl:
            import ssl
            if hasattr(ssl, "SSLContext"):
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False  # demo: encrypt, but don't check the CA
                ctx.verify_mode = ssl.CERT_NONE
                self.sock = ctx.wrap_socket(raw, server_hostname=self.server)
            else:
                self.sock = ssl.wrap_socket(raw, server_hostname=self.server)
        else:
            # Give plain sockets the same read/write methods as SSL ones
            self.sock = raw if hasattr(raw, "write") else _SockIO(raw)

        flags = 0x02  # clean session
        payload = self._str(self.client_id)
        if self.user:
            flags |= 0x80 | 0x40
            payload += self._str(self.user) + self._str(self.password)
        body = self._str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive) + payload
        self._packet(0x10, body)

        if self._recv(1)[0] != 0x20:
            raise MQTTError("Unexpected reply to CONNECT")
        self._read_remaining_length()
        code = self._recv(2)[1]
        if code:
            reasons = {4: "bad username or password", 5: "not authorized"}
            raise MQTTError("Broker refused connection: " + reasons.get(code, "code %d" % code))

        self.poller = select.poll()
        self.poller.register(self.sock, select.POLLIN)
        self.last_ping = self.last_rx = time.time()

    def subscribe(self, topic):
        """Subscribe with QoS 0 (no acknowledgements to track)."""
        self.pid = self.pid % 65535 + 1
        self._packet(0x82, struct.pack("!H", self.pid) + self._str(topic) + b"\x00")
        # The SUBACK is read (and skipped) by check_msg().

    def publish(self, topic, msg):
        """Publish with QoS 0."""
        if isinstance(msg, str):
            msg = msg.encode()
        self._packet(0x30, self._str(topic) + msg)

    def ping_if_needed(self):
        # The broker answers every ping, so long silence means the connection is gone
        # (for example after the simulation was paused in a background tab).
        if time.time() - self.last_rx > self.keepalive * 1.5:
            raise MQTTError("No word from the broker: connection lost")
        if time.time() - self.last_ping >= self.keepalive // 2:
            self._send(b"\xc0\x00")
            self.last_ping = time.time()

    def check_msg(self, timeout_ms=100):
        """Handle at most one incoming packet. Returns True if one was read."""
        self.ping_if_needed()
        buffered = hasattr(self.sock, "pending") and self.sock.pending()  # CPython TLS
        if not buffered and not self.poller.poll(timeout_ms):
            return False
        header = self._recv(1)[0]
        length = self._read_remaining_length()
        body = self._recv(length) if length else b""
        self.last_rx = time.time()
        kind = header & 0xF0
        if kind == 0x30:  # PUBLISH
            qos = (header >> 1) & 0x03
            tlen = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + tlen]
            pos = 2 + tlen
            if qos:
                pid = body[pos:pos + 2]
                pos += 2
                self._send(b"\x40\x02" + pid)  # PUBACK
            if self.cb:
                self.cb(topic, body[pos:])
        # SUBACK (0x90), PINGRESP (0xD0) and others need no action.
        return True

    def disconnect(self):
        try:
            self._send(b"\xe0\x00")
        finally:
            self.sock.close()


class _SockIO:
    """read()/write() on a plain CPython socket, for testing without TLS."""

    def __init__(self, s):
        self.s = s

    def read(self, n):
        return self.s.recv(n)

    def write(self, b):
        return self.s.send(b)

    def fileno(self):
        return self.s.fileno()

    def close(self):
        self.s.close()
