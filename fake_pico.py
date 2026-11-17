"""Fake Pico W: pretends to be the SDL LED demo device.

Listens on the same MQTT topics as the real main.py, simulates the AS7341
sensor with a simple linear light model, and replies in the same format.

Run:
    pip install paho-mqtt
    export HIVEMQ_HOST=xxxx.s1.eu.hivemq.cloud
    export HIVEMQ_USER=your-user
    export HIVEMQ_PASS=your-password
    python fake_pico.py
"""

import json
import os
import random
import time

import paho.mqtt.client as mqtt

PICO_ID = os.environ.get("PICO_ID", "test")  # the real Pico prints its own ID
HOST = os.environ["HIVEMQ_HOST"]
USER = os.environ["HIVEMQ_USER"]
PASS = os.environ["HIVEMQ_PASS"]

PREFIX = f"sdl-demo/picow/{PICO_ID}/"
COMMAND_TOPIC = PREFIX + "GPIO/28"   # notebook -> device
RESULT_TOPIC = PREFIX + "as7341/"    # device -> notebook

CHANNELS = ["ch410", "ch440", "ch470", "ch510", "ch550", "ch583", "ch620", "ch670"]

# How strongly each LED color shows up in each sensor channel (made-up but
# realistic shape: blue LED ~470 nm, green ~528 nm, red ~622 nm).
WEIGHTS = {
    #        410  440  470  510  550  583  620  670
    "R": [0.0, 0.0, 0.0, 0.0, 0.5, 6.0, 30.0, 8.0],
    "G": [0.0, 1.0, 4.0, 22.0, 18.0, 3.0, 0.5, 0.0],
    "B": [2.0, 18.0, 30.0, 5.0, 0.5, 0.0, 0.0, 0.0],
}
BACKGROUND = [12, 20, 25, 30, 35, 30, 28, 15]  # room light leaking in
NOISE = 0.02  # 2% random noise, like a real sensor


def simulate(R, G, B):
    readings = []
    for i in range(8):
        signal = R * WEIGHTS["R"][i] + G * WEIGHTS["G"][i] + B * WEIGHTS["B"][i]
        value = (signal + BACKGROUND[i]) * (1 + random.gauss(0, NOISE))
        readings.append(max(0, min(65535, int(value))))  # sensor is 16-bit
    return readings


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected ({reason_code}). Listening on {COMMAND_TOPIC}")
    client.subscribe(COMMAND_TOPIC, qos=1)


def on_message(client, userdata, msg):
    reply = {}
    try:
        params = json.loads(msg.payload)
        reply["_input_message"] = params
        R, G, B = params["R"], params["G"], params["B"]
        for name, v in (("R", R), ("G", G), ("B", B)):
            if not 0 <= v <= 255:
                raise ValueError(f"Invalid {name}: {v} (must be between 0 and 255)")
        time.sleep(0.6)  # the real device takes about this long
        reply.update(zip(CHANNELS, simulate(R, G, B)))
        reply["background"] = dict(zip(CHANNELS, BACKGROUND))
        print(f"R={R:3d} G={G:3d} B={B:3d} -> {[reply[c] for c in CHANNELS]}")
    except Exception as e:  # same behavior as main.py: report the error back
        reply.setdefault("_input_message", msg.payload.decode(errors="replace"))
        reply["error"] = repr(e)
        print("Error:", e)
    client.publish(RESULT_TOPIC, json.dumps(reply), qos=0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-pico-{PICO_ID}")
client.tls_set()
client.username_pw_set(USER, PASS)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, 8883)
client.loop_forever()
