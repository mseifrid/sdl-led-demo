"""Notebook side: send R, G, B to the device and get 8 readings back.

Works the same with the Wokwi simulation, fake_pico.py or the real Pico W;
only the broker settings and PICO_ID differ.

    lab = LedLab.from_env()          # reads .env next to the notebook
    readings = lab.measure(255, 0, 0)
"""

import json
import os
import queue
import threading
import time
import uuid

import paho.mqtt.client as mqtt

CHANNELS = ["ch410", "ch440", "ch470", "ch510", "ch550", "ch583", "ch620", "ch670"]


def load_settings(path=".env"):
    """Read KEY=value lines from a .env file; real environment variables win.

    MQTT_* names are preferred; the older HIVEMQ_* names still work.
    """
    values = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().removeprefix("export ").strip()
                values[key] = val.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k.startswith(("MQTT_", "HIVEMQ_", "PICO_"))})

    def get(name, default=""):
        return values.get("MQTT_" + name) or values.get("HIVEMQ_" + name) or default

    return {
        "host": get("HOST"),
        "port": int(get("PORT", "8883")),
        "username": get("USER"),
        "password": get("PASS"),
        "tls": get("TLS", "true").lower() not in ("0", "false", "no"),
        "pico_id": values.get("PICO_ID", "test"),
    }


class LedLab:
    def __init__(self, host, username="", password="", pico_id="test", port=8883, tls=True):
        self.pico_id = pico_id
        self.prefix = f"sdl-demo/picow/{pico_id}/"
        self.inbox = queue.Queue()
        self._ready = threading.Event()
        self._error = None

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if tls:
            self.client.tls_set()
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = lambda *args: self._ready.set()
        self.client.on_message = self._on_message
        self.client.connect(host, port)
        self.client.loop_start()
        if not self._ready.wait(15):
            self.close()
            raise ConnectionError(self._error or f"Could not reach the broker at {host}:{port}.")

    @classmethod
    def from_env(cls, path=".env"):
        s = load_settings(path)
        if not s["host"]:
            raise RuntimeError(f"No broker host found. Put MQTT_HOST=... in {os.path.abspath(path)}.")
        return cls(s["host"], s["username"], s["password"], s["pico_id"], s["port"], s["tls"])

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._error = f"Broker refused the connection: {reason_code}. Check MQTT_USER / MQTT_PASS."
            return
        client.subscribe(self.prefix + "as7341/", qos=1)  # (re)subscribe on every connect

    def _on_message(self, client, userdata, msg):
        try:
            self.inbox.put(json.loads(msg.payload))
        except ValueError:
            pass  # not JSON: not from our device

    def measure(self, R, G, B, timeout=30, hidden=False):
        """Set the LED to (R, G, B), return the 8 sensor readings.

        hidden=True asks the simulated device not to display the color
        (used for the secret target). A real Pico W ignores it.
        """
        exp_id = str(uuid.uuid4())
        msg = {
            "R": int(R), "G": int(G), "B": int(B),
            "atime": 100, "astep": 999, "gain": 128,
            "mongodb": False, "_session_id": "class", "_experiment_id": exp_id,
        }
        if hidden:
            msg["_hidden"] = True
        self.client.publish(self.prefix + "GPIO/28", json.dumps(msg), qos=1)
        end = time.time() + timeout
        while True:  # ignore replies that are not ours
            remaining = end - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"No reply from device '{self.pico_id}'. Is the simulation running and "
                    "VISIBLE (Wokwi nearly pauses in a hidden tab), and does its PICO_ID match?"
                )
            try:
                data = self.inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            inp = data.get("_input_message", {})
            if isinstance(inp, dict) and inp.get("_experiment_id") == exp_id:
                if data.get("error"):
                    raise RuntimeError(data["error"])
                return [data[ch] for ch in CHANNELS]

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
