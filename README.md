# SDL LED demo

A small self-driving-lab demo: a marimo notebook sends R, G, B values to an LED on a
Raspberry Pi Pico W over MQTT and gets back 8 spectral readings from an AS7341 sensor.
A built-in offline simulator stands in for the hardware, so the notebook runs anywhere
with no device and no credentials.

## Run it

**macOS:** double-click `start_notebook.command` (installs `uv` the first time).

**Any computer** with [uv](https://docs.astral.sh/uv/) installed:

```bash
uvx marimo edit --sandbox sdl_demo.py
```

The first run installs packages, which takes about a minute.

## Simulator vs. real device

- **Simulator** (default): no setup needed.
- **Real Pico W**: set these environment variables before starting the notebook.
  Get the values from the repo owner directly; they are never stored in Git.

  ```bash
  export HIVEMQ_HOST=<broker host>
  export HIVEMQ_USER=<user>
  export HIVEMQ_PASS=<password>
  export PICO_ID=<device id>
  ```

## Files

| File | What it is |
| --- | --- |
| `sdl_demo.py` | The marimo notebook |
| `sdl_client.py` | `LedLab` client: send RGB, receive 8 readings |
| `fake_pico.py` | Simulated Pico W that talks over the real broker |
| `test_laptop.py` | Quick end-to-end check against `fake_pico.py` |
| `make_cert.py` | Generates the broker CA file (`hivemq-com-chain.der`) for the Pico |
| `start_notebook.command` | Double-click launcher for macOS |

## Never commit

`secrets.py`, `*.der` and `.venv/` are in `.gitignore`. Credentials go in
environment variables only, never in any tracked file.
