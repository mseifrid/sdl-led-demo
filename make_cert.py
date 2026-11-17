"""Generate hivemq-com-chain.der for OUR broker host.

Adapted from the authors' notebook 7.2.1 (sparks-baird/self-driving-lab-demo).
Same idea: connect to the broker on 8883, take the SECOND certificate it sends
(the intermediate CA that signed the server cert), and save it in DER format.
The Pico's main.py loads this file as its CA. The file name stays
hivemq-com-chain.der because main.py opens that name, even though our broker
is EMQX Serverless.

It then proves the file works by reconnecting while trusting ONLY that file,
which is what the Pico does.

Run on your laptop (host comes from an env var, never from this file):
    export HIVEMQ_HOST=<broker host>
    python make_cert.py

Re-run it if the Pico ever fails TLS after working before: CAs rotate their
intermediate certificates, and the file must match.
"""

import os
import re
import socket
import ssl
import subprocess
import tempfile

HOST = os.environ["HIVEMQ_HOST"]
PORT = 8883
OUT = "hivemq-com-chain.der"


def get_chain_der():
    """Return the certificates the broker sends, as a list of DER bytes."""
    ctx = ssl.create_default_context()
    with socket.create_connection((HOST, PORT), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as s:
            if hasattr(s, "get_unverified_chain"):  # Python 3.13+
                return s.get_unverified_chain()
    # Older Python: same command as the notebook
    out = subprocess.run(
        ["openssl", "s_client", "-connect", f"{HOST}:{PORT}",
         "-servername", HOST, "-showcerts"],
        input=b"", capture_output=True, timeout=30,
    ).stdout.decode(errors="replace")
    pems = re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", out, re.S)
    return [ssl.PEM_cert_to_DER_cert(p) for p in pems]


def describe(der):
    """Subject, issuer and expiry of a DER certificate (for printing only)."""
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(ssl.DER_cert_to_PEM_cert(der))
    try:
        info = ssl._ssl._test_decode_cert(f.name)
        name = lambda field: ", ".join(v for rdn in info[field] for k, v in rdn if k == "commonName")
        return f"{name('subject')} (issued by {name('issuer')}), expires {info['notAfter']}"
    except Exception:
        return "(could not decode details)"
    finally:
        os.remove(f.name)


def check(der):
    """Connect again trusting only this certificate, like the Pico does."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cadata=der)
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN  # trust an intermediate directly
    with socket.create_connection((HOST, PORT), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST):
            pass


chain = get_chain_der()
print(f"Broker sent {len(chain)} certificate(s):")
for i, der in enumerate(chain):
    print(f"  [{i}] {describe(der)}")

if len(chain) < 2:
    raise SystemExit("Expected at least 2 certificates (server + intermediate). Stopping.")

ca = chain[1]  # same choice as the notebook: occurrence = 1 (second)
with open(OUT, "wb") as f:
    f.write(ca)
print(f"\nWrote {OUT} ({len(ca)} bytes): {describe(ca)}")

check(ca)
print("Check passed: a TLS connection trusting only this file succeeds.")
