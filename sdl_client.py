"""Notebook side: send R, G, B to the device and get 8 readings back.

Works the same with fake_pico.py or the real Pico W; only PICO_ID differs.
"""

import json
import queue
import time
import uuid

import paho.mqtt.client as mqtt

CHANNELS = ["ch410", "ch440", "ch470", "ch510", "ch550", "ch583", "ch620", "ch670"]


class LedLab:
    def __init__(self, host, username, password, pico_id="test", port=8883):
        self.prefix = f"sdl-demo/picow/{pico_id}/"
        self.inbox = queue.Queue()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.tls_set()
        self.client.username_pw_set(username, password)
        self.client.on_message = lambda c, u, m: self.inbox.put(json.loads(m.payload))
        self.client.connect(host, port)
        self.client.subscribe(self.prefix + "as7341/", qos=1)
        self.client.loop_start()

    def measure(self, R, G, B, timeout=30):
        """Set the LED to (R, G, B), return the 8 sensor readings."""
        exp_id = str(uuid.uuid4())
        msg = {
            "R": int(R), "G": int(G), "B": int(B),
            "atime": 100, "astep": 999, "gain": 128,
            "mongodb": False, "_session_id": "class", "_experiment_id": exp_id,
        }
        self.client.publish(self.prefix + "GPIO/28", json.dumps(msg), qos=1)
        end = time.time() + timeout
        while True:  # ignore replies that are not ours
            remaining = end - time.time()
            if remaining <= 0:
                raise TimeoutError("No reply from device. Is it running and is PICO_ID right?")
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
