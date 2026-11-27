# SDL LED demo

A small self-driving-lab demo (after Baird & Sparks, *Matter* 2022): a notebook sends R, G, B
values to an RGB LED over MQTT and gets back 8 spectral readings from an AS7341-style light
sensor, then three optimizers (random, grid, Bayesian) race to match a hidden color.

```
 sdl_class_demo.py     <-->  MQTT broker (cloud)  <-->  Wokwi tab: ESP32 + LED ring + OLED
```

## Quick start

Ask the instructor for two things (they are not in this repository): the **Wokwi project
link** and the **broker settings** (host, user, password).

1. Get the code:
   ```bash
   git clone https://github.com/rcb1409/sdl-led-demo.git
   cd sdl-led-demo
   ```
2. Make your settings file: copy `.env.example` to `.env` and fill in the broker settings.
   ```bash
   cp .env.example .env
   ```
3. Start the simulated device: open the Wokwi link, type the password into `config.py`
   (`MQTT_PASS = "..."`), press ▶, and wait for **Ready!** on its small screen. Don't press
   Save afterwards.
4. Start the [marimo](https://marimo.io) notebook. On a Mac, double-click
   `start_notebook.command`, or run this (needs [uv](https://docs.astral.sh/uv/); the first
   run downloads packages, about a minute):
   ```bash
   uv run --no-project --with marimo,paho-mqtt,numpy,matplotlib,scikit-learn,scipy marimo edit sdl_class_demo.py
   ```
   Without uv: `pip install -r requirements.txt`, then `marimo edit sdl_class_demo.py`.
5. Put Wokwi and the notebook **side by side in two browser windows**. Steps 0 to 5 run on
   their own when the notebook opens; the self-driving runs (Step 7) start when you click
   their buttons. The LED ring changes with every experiment.

Wokwi nearly pauses when its tab is hidden, and the notebook's commands then time out. Bring
it back into view and it reconnects on its own within a few seconds.

To build the Wokwi project yourself instead, see [wokwi/README.md](wokwi/README.md).

Students recreating it on their own: see [STUDENTS.md](STUDENTS.md).

**Backup only:** `sdl_class_demo.ipynb` is a Jupyter copy of the same demo, kept in case
marimo won't run on a machine. It isn't kept in sync with the marimo notebook, so use
`sdl_class_demo.py` unless you have to. To open it:
`uv run --no-project --with jupyterlab,paho-mqtt,numpy,matplotlib,scikit-learn,scipy jupyter lab sdl_class_demo.ipynb`

## Files

| File | What it is |
| --- | --- |
| `sdl_class_demo.py` | The class demo notebook ([marimo](https://marimo.io)) |
| `sdl_class_demo.ipynb` | **Backup only:** Jupyter copy of the class demo, for when marimo won't run |
| `sdl_client.py` | `LedLab` client: send RGB, receive 8 readings; reads `.env` |
| `.env.example` | Template for your settings (`.env` itself is never committed) |
| `wokwi/` | The simulated device for the Wokwi browser tab |
| `STUDENTS.md` | Step-by-step guide for students |
| `sdl_demo.py` | Earlier, separate marimo version of the notebook, with a built-in offline simulator (`uvx marimo edit --sandbox sdl_demo.py`) |
| `fake_pico.py` | Simulated device that runs in a terminal instead of Wokwi |
| `test_laptop.py` | Quick end-to-end check against `fake_pico.py` |
| `make_cert.py` | Generates the broker CA file (`hivemq-com-chain.der`) for a real Pico W |
| `start_notebook.command` | Double-click launcher on macOS: opens `sdl_class_demo.py` in marimo |

## Settings

`sdl_client.py` reads `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS`, `MQTT_USER`, `MQTT_PASS` and
`PICO_ID` from `.env` or from environment variables. The older `HIVEMQ_HOST`,
`HIVEMQ_USER`, `HIVEMQ_PASS` names still work.

## Never commit

`.env`, `secrets.py`, `*.der` and `.venv/` are in `.gitignore`. Credentials go in `.env` or
environment variables only, never in any tracked file, and never in a saved Wokwi project
you share.
