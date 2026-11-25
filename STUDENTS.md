# Recreate the self-driving lab yourself

You will run your own simulated device in a browser tab and drive it from the same notebook
used in class. About 15 minutes. No hardware needed.

```
 notebook on your laptop  <-->  MQTT broker (cloud)  <-->  your Wokwi tab (LED + sensor)
```

## 1. Get the code

Download or clone this repository, then install the Python packages:

```bash
pip install -r requirements.txt
```

## 2. Make your settings file

Copy `.env.example` to `.env` (same folder as the notebook) and fill it in:

```
MQTT_HOST=<broker host from your instructor>
MQTT_PORT=8883
MQTT_TLS=true
MQTT_USER=<user from your instructor>
MQTT_PASS=<password from your instructor>
PICO_ID=wokwi-yourname
```

- `PICO_ID` is your device's name. Make it unique (for example your name), so your
  notebook talks to *your* device and not a classmate's.
- No broker login? Use `MQTT_HOST=broker.hivemq.com` and leave `MQTT_USER` and
  `MQTT_PASS` empty. It's a free public test broker.
- Never commit `.env` or share it; it's already in `.gitignore`.

## 3. Start your simulated device

1. Open the Wokwi link your instructor shared (or build the project yourself with
   [wokwi/README.md](wokwi/README.md)).
2. Open `config.py` in the Wokwi editor and type the **same values** as your `.env`
   (`PICO_ID`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`).
3. Press the green ▶ button and wait until the small screen says **Ready!**
   (up to a minute). Keep this tab open.

Anyone with a link to a *saved* Wokwi project can read its files. If you save your copy,
remove the password from `config.py` first.

## 4. Run the notebook

```bash
jupyter notebook sdl_class_demo.ipynb
```

Put the notebook and Wokwi **side by side in two browser windows** (not two tabs of one
window), then run the cells one at a time (Shift + Enter). The LED ring changes color for
every experiment. Wokwi nearly pauses when it's hidden behind another tab.

## If something goes wrong

| What you see | What to check |
| --- | --- |
| `No broker host found` | `.env` is missing or not in the notebook's folder |
| `Broker refused the connection` | `MQTT_USER` / `MQTT_PASS` in `.env` |
| `No reply from device` (timeout) | The Wokwi tab is running, **visible**, and says **Ready!**, and `PICO_ID` is identical in `.env` and `config.py` |
| Wokwi screen says **Broker error** | `MQTT_HOST` / `MQTT_USER` / `MQTT_PASS` in Wokwi's `config.py` |
| Wokwi stuck on `Connecting to Wi-Fi` | Press ■ then ▶ to restart the simulation |
