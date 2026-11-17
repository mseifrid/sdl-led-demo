"""Laptop check: talk to fake_pico.py through the broker with LedLab.

Run in a second Terminal window while fake_pico.py is running.
Uses the same HIVEMQ_HOST / HIVEMQ_USER / HIVEMQ_PASS env vars.
"""

import os
import time

from sdl_client import LedLab

lab = LedLab(os.environ["HIVEMQ_HOST"], os.environ["HIVEMQ_USER"],
             os.environ["HIVEMQ_PASS"], pico_id=os.environ.get("PICO_ID", "test"))
for rgb in [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]:
    start = time.time()
    readings = lab.measure(*rgb)
    print(f"RGB={rgb} -> {readings}  ({time.time() - start:.2f} s)")
lab.close()
print("LAPTOP TEST PASSED")
