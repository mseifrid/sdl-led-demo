"""Simulated SDL-Demo device for Wokwi (MicroPython).

Behaves like the real Pico W in Baird & Sparks' SDL-Demo:
  1. listens for {"R":..,"G":..,"B":..} on   sdl-demo/picow/<PICO_ID>/GPIO/28
  2. sets the RGB LED (a NeoPixel ring)
  3. "measures" 8 AS7341 channels (simulated with a simple light model,
     because Wokwi has no AS7341 part)
  4. replies on                              sdl-demo/picow/<PICO_ID>/as7341/
The OLED shows the latest color and the 8 readings as bars.

Wokwi simulates Wi-Fi only on the ESP32, so the Wokwi project uses an ESP32.
The same file also runs on a Pico W (it picks the pins by board).
"""

import json
import math
import random
import sys
import time

import machine
import neopixel
import network

import config
from mqtt_lite import MQTTClient

# Defaults for any setting left out of config.py
for _name, _default in (("MQTT_PORT", 8883), ("MQTT_TLS", True), ("MQTT_USER", ""),
                        ("MQTT_PASS", ""), ("WIFI_SSID", "Wokwi-GUEST"), ("WIFI_PASS", "")):
    if not hasattr(config, _name):
        setattr(config, _name, _default)

PREFIX = "sdl-demo/picow/%s/" % config.PICO_ID
COMMAND_TOPIC = PREFIX + "GPIO/28"   # notebook -> device
RESULT_TOPIC = PREFIX + "as7341/"    # device -> notebook

CHANNELS = ["ch410", "ch440", "ch470", "ch510", "ch550", "ch583", "ch620", "ch670"]

# Same light model as fake_pico.py and the notebook's offline simulator.
# How strongly each LED color shows up in each sensor channel (410 ... 670 nm).
WEIGHTS = {
    "R": [0.0, 0.0, 0.0, 0.0, 0.5, 6.0, 30.0, 8.0],
    "G": [0.0, 1.0, 4.0, 22.0, 18.0, 3.0, 0.5, 0.0],
    "B": [2.0, 18.0, 30.0, 5.0, 0.5, 0.0, 0.0, 0.0],
}
BACKGROUND = [12, 20, 25, 30, 35, 30, 28, 15]  # room light leaking in
NOISE = 0.02  # 2% random noise, like a real sensor
BAR_FULL_SCALE = 8000  # counts that fill a bar on the OLED

# ---------------- Hardware ----------------
if sys.platform == "rp2":  # Pico W: LED on GP28 like the Maker Pi Pico, OLED on GP4/GP5
    LED_PIN, SDA_PIN, SCL_PIN = 28, 4, 5
else:                      # ESP32 (the Wokwi project)
    LED_PIN, SDA_PIN, SCL_PIN = 13, 21, 22

led = neopixel.NeoPixel(machine.Pin(LED_PIN), 16)
try:
    from ssd1306 import SSD1306_I2C
    oled = SSD1306_I2C(128, 64, machine.I2C(0, sda=machine.Pin(SDA_PIN), scl=machine.Pin(SCL_PIN)))
except Exception as e:  # the demo still works without the screen
    print("OLED not found:", e)
    oled = None


def set_led(R, G, B):
    led.fill((R, G, B))
    led.write()


def screen(lines, readings=None):
    if not oled:
        return
    oled.fill(0)
    for i, line in enumerate(lines[:3 if readings else 6]):
        oled.text(line, 0, i * 10)
    if readings:
        top, bottom = 30, 63
        for i, v in enumerate(readings):
            h = min(bottom - top, int((bottom - top) * v / BAR_FULL_SCALE))
            oled.fill_rect(i * 16 + 2, bottom - h, 12, h + 1, 1)
    oled.show()


# ---------------- Simulated AS7341 sensor ----------------
def _uniform():
    return (random.getrandbits(24) + 1) / 16777217


def gauss():
    """Standard normal random number (Box-Muller)."""
    return math.sqrt(-2 * math.log(_uniform())) * math.cos(2 * math.pi * _uniform())


def simulate(R, G, B):
    readings = []
    for i in range(8):
        signal = R * WEIGHTS["R"][i] + G * WEIGHTS["G"][i] + B * WEIGHTS["B"][i]
        value = (signal + BACKGROUND[i]) * (1 + NOISE * gauss())
        readings.append(max(0, min(65535, int(value))))  # sensor is 16-bit
    return readings


# ---------------- Network ----------------
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    attempt = 0
    while not wlan.isconnected():
        attempt += 1  # Wokwi's virtual Wi-Fi sometimes stalls: retry every 10 s
        print("Connecting to Wi-Fi", config.WIFI_SSID, "(try %d)" % attempt, end="")
        screen(["Wi-Fi...", config.WIFI_SSID, "try %d" % attempt])
        try:
            wlan.disconnect()
        except Exception:
            pass
        wlan.connect(config.WIFI_SSID, config.WIFI_PASS)
        for _ in range(40):
            if wlan.isconnected():
                break
            print(".", end="")
            time.sleep(0.25)
        print()
    print("Wi-Fi connected")


count = 0


def on_message(topic, payload):
    global count
    reply = {}
    try:
        params = json.loads(payload)
        reply["_input_message"] = params
        R, G, B = params["R"], params["G"], params["B"]
        for name, v in (("R", R), ("G", G), ("B", B)):
            if not (isinstance(v, int) and 0 <= v <= 255):
                raise ValueError("Invalid %s: %s (must be a whole number 0 to 255)" % (name, v))
        hidden = bool(params.get("_hidden"))  # the secret target: measure it, don't show it
        set_led(*((0, 0, 0) if hidden else (R, G, B)))
        time.sleep(0.3)  # let the light settle, like the real sensor's integration time
        readings = simulate(R, G, B)
        for ch, v in zip(CHANNELS, readings):
            reply[ch] = v
        reply["background"] = dict(zip(CHANNELS, BACKGROUND))
        reply["device"] = "wokwi-simulated-pico-w"
        count += 1
        shown = "TARGET (hidden)" if hidden else "R%d G%d B%d" % (R, G, B)
        print("#%d %s -> %s" % (count, shown, readings))
        screen(["Exp #%d  id:%s" % (count, config.PICO_ID[:6]), shown, ""], readings)
    except Exception as e:  # same behavior as the real main.py: report the error back
        if "_input_message" not in reply:
            reply["_input_message"] = payload.decode() if isinstance(payload, bytes) else str(payload)
        reply["error"] = repr(e)
        print("Error:", e)
        screen(["Error:", str(e)[:16], str(e)[16:32]])
    client.publish(RESULT_TOPIC, json.dumps(reply))


set_led(0, 0, 0)
screen(["SDL-Demo (sim)", "id: " + config.PICO_ID[:12], "starting..."])
print("Device ID:", config.PICO_ID)
connect_wifi()

client = None
while True:
    try:
        print("Connecting to broker", config.MQTT_HOST, config.MQTT_PORT)
        screen(["Broker...", config.MQTT_HOST[:16], config.MQTT_HOST[16:32]])
        client = MQTTClient("wokwi-" + config.PICO_ID, config.MQTT_HOST, config.MQTT_PORT,
                            config.MQTT_USER, config.MQTT_PASS, keepalive=30, ssl=config.MQTT_TLS)
        client.set_callback(on_message)
        client.connect()
        client.subscribe(COMMAND_TOPIC)
        print("Ready. Listening on", COMMAND_TOPIC)
        screen(["Ready!", "id: " + config.PICO_ID[:12], "waiting for", "the notebook..."])
        while True:
            client.check_msg(200)
    except Exception as e:
        print("Connection problem:", repr(e), "- retrying in 3 s")
        screen(["Broker error:", repr(e)[:16], repr(e)[16:32], "retrying..."])
        try:
            client.sock.close()
        except Exception:
            pass
        time.sleep(3)
