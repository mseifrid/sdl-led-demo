# The Wokwi simulation tab

These five files make up the simulated device that runs in a browser tab at
[wokwi.com](https://wokwi.com): an LED ring that lights up in each color the notebook
sends, and a small screen that shows the 8 sensor readings as bars.

| File | What it does |
| --- | --- |
| `diagram.json` | The board and the wiring: ESP32, 16-LED NeoPixel ring on pin 13, OLED screen on pins 21/22 |
| `main.py` | The device program: receive R, G, B, light the LED, simulate the sensor, reply |
| `config.py` | **The only file you edit:** broker settings and the device ID |
| `mqtt_lite.py` | A small MQTT client (talks to the broker) |
| `ssd1306.py` | Driver for the OLED screen |

**Why an ESP32 and not a Pico W?** Wokwi can show a Pico W, but it does not simulate the
Pico W's Wi-Fi chip, so a simulated Pico W never gets online. Wokwi's ESP32 has working
Wi-Fi, runs the same MicroPython code, and uses the same messages as the real Pico W in the
paper, so the notebook can't tell the difference. `main.py` also runs on a real Pico W
(it picks the pins by board).

**No AS7341 sensor in Wokwi:** the device computes the 8 readings with a simple light model
(each LED color adds light to certain channels, plus room light and 2% noise). It's the same
model as `fake_pico.py`.

## Build the project once (instructor)

1. Sign in at [wokwi.com](https://wokwi.com) (a free account is enough).
2. Open <https://wokwi.com/projects/new/micropython-esp32>.
3. Replace the contents of `main.py` and `diagram.json` with the files from this folder.
4. Add `mqtt_lite.py`, `ssd1306.py` and `config.py`: click the small ▾ arrow to the right
   of the file tabs, choose **New file...**, type the name, then paste the contents in.
   (The name box may already contain text; clear it first.)
5. Press **Save**, then **Share** to get the link for students.

Keep `MQTT_USER` and `MQTT_PASS` empty in the copy you share: anyone with a Wokwi link can
read its files. Students open the link, type their own settings into `config.py`, and
press ▶. They don't need to save or sign in to run it.

## Running it for the demo

1. Open the project, set `config.py` (same values as the notebook's `.env`).
2. Press the green ▶ button. Within about a minute the serial monitor shows
   `Connecting to Wi-Fi ... connected`, then `Ready. Listening on ...`, and the screen says
   **Ready!**
3. Put this tab and the notebook side by side in **two browser windows**, then run the
   notebook. Each command takes about 0.6 seconds round trip.

**Keep the Wokwi window visible.** Wokwi nearly pauses when its tab is hidden: commands then
time out and the broker drops the device. Once the tab is visible again, the device notices
within about 45 seconds (usually much sooner), reconnects, and says **Ready!**

The device retries on its own when something goes wrong: Wi-Fi every 10 seconds (Wokwi's
virtual Wi-Fi sometimes stalls on the first try), the broker every 3 seconds. If the screen
keeps showing **Broker error**, check `MQTT_HOST`, `MQTT_USER` and `MQTT_PASS` in
`config.py`. Settings left out of `config.py` get sensible defaults.
