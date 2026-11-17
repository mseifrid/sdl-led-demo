# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "matplotlib",
#     "numpy",
#     "paho-mqtt>=2.0",
#     "scikit-learn",
#     "scipy",
# ]
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="medium",
    app_title="Self-driving lab: match a hidden color",
)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Self-driving lab: match a hidden color

    A **self-driving lab (SDL)** is an experiment that runs itself: a computer picks the
    next experiment, a machine does it, a sensor measures the result, and the computer uses
    that result to choose a better experiment next time. Real SDLs mix chemicals or make new
    materials. This one mixes light, which is cheap and safe
    (Baird & Sparks, *Matter* 2022).

    **On the desk:** an RGB LED shines on an 8-channel light sensor (410 to 670 nm).
    You send three numbers (red, green, blue brightness, each 0 to 255) and get back
    eight sensor readings.

    **Your goal:** find the LED color whose spectrum matches a hidden target. First you
    try by hand, then three strategies race each other: random search, grid search, and
    Bayesian optimization.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.mermaid(
        """
        flowchart LR
          A[Optimizer picks R, G, B] --> B[LED shines]
          B --> C[Sensor reads 8 channels]
          C --> D[Score: how far from target?]
          D --> A
        """
    )
    return


@app.cell(hide_code=True)
def _():
    import functools
    import json
    import os
    import queue
    import random
    import time
    import uuid
    import warnings

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np

    return (
        functools,
        json,
        mo,
        np,
        os,
        plt,
        queue,
        random,
        time,
        uuid,
        warnings,
    )


@app.cell(hide_code=True)
def _(functools, json, mo, os, queue, random, time, uuid):
    # ---------------- Instructor settings (students can skip this cell) ----------------
    # Broker details come from environment variables only. Never type real values
    # into this file: it is tracked by Git and would be pushed with your changes.
    HIVEMQ_HOST = os.environ.get("HIVEMQ_HOST", "")
    HIVEMQ_USER = os.environ.get("HIVEMQ_USER", "")
    HIVEMQ_PASS = os.environ.get("HIVEMQ_PASS", "")
    PICO_ID = os.environ.get("PICO_ID", "test")  # "test" talks to fake_pico.py
    USE_REAL_DEVICE = False  # starting position of the switch below
    TARGET_SEED = 2026  # change to pick a different hidden color

    CHANNELS = ["ch410", "ch440", "ch470", "ch510", "ch550", "ch583", "ch620", "ch670"]

    # ---------------- Real device: copy of sdl_client.py (keep in sync) ----------------
    import paho.mqtt.client as mqtt

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

    # ---------------- Simulator: same light model as fake_pico.py ----------------
    class FakeLab:
        """Offline stand-in for LedLab. Same measure() signature, no broker needed."""

        # How strongly each LED color shows up in each channel (410 ... 670 nm)
        WEIGHTS = {
            "R": [0.0, 0.0, 0.0, 0.0, 0.5, 6.0, 30.0, 8.0],
            "G": [0.0, 1.0, 4.0, 22.0, 18.0, 3.0, 0.5, 0.0],
            "B": [2.0, 18.0, 30.0, 5.0, 0.5, 0.0, 0.0, 0.0],
        }
        BACKGROUND = [12, 20, 25, 30, 35, 30, 28, 15]  # room light leaking in
        NOISE = 0.02  # 2% random noise, like a real sensor

        def __init__(self, delay=0.15):
            self.delay = delay  # pause per experiment so the live plot is visible

        def measure(self, R, G, B, timeout=30):
            for name, v in (("R", R), ("G", G), ("B", B)):
                if not 0 <= v <= 255:
                    raise ValueError(f"Invalid {name}: {v} (must be between 0 and 255)")
            time.sleep(self.delay)
            readings = []
            for i in range(8):
                signal = R * self.WEIGHTS["R"][i] + G * self.WEIGHTS["G"][i] + B * self.WEIGHTS["B"][i]
                value = (signal + self.BACKGROUND[i]) * (1 + random.gauss(0, self.NOISE))
                readings.append(max(0, min(65535, int(value))))  # sensor is 16-bit
            return readings

    @functools.cache
    def connect_real():
        """One broker connection per session, reused when the switch is toggled."""
        if not (HIVEMQ_HOST and HIVEMQ_USER and HIVEMQ_PASS):
            raise RuntimeError(
                "Broker settings are empty. Fill HIVEMQ_HOST, HIVEMQ_USER and HIVEMQ_PASS "
                "in the hidden setup cell."
            )
        return LedLab(HIVEMQ_HOST, HIVEMQ_USER, HIVEMQ_PASS, pico_id=PICO_ID)

    device_switch = mo.ui.switch(value=USE_REAL_DEVICE, label="Use real device")
    return CHANNELS, FakeLab, PICO_ID, TARGET_SEED, connect_real, device_switch


@app.cell(hide_code=True)
def _(FakeLab, PICO_ID, connect_real, device_switch, mo):
    lab = None
    if device_switch.value:
        try:
            _lab = connect_real()
            _lab.measure(0, 0, 0, timeout=15)  # round trip check
            lab = _lab
            _status = mo.callout(mo.md(f"**Connected to device** `{PICO_ID}`."), kind="success")
        except Exception as _e:
            _status = mo.callout(
                mo.md(f"**Could not reach the device.** {_e}"), kind="danger"
            )
    else:
        lab = FakeLab()
        _status = mo.callout(
            mo.md(
                "**Using the simulator.** No hardware needed: readings come from a simple "
                "LED model with 2% noise."
            ),
            kind="info",
        )
    mo.vstack([device_switch, _status])
    return (lab,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Play with the LED

    Move the sliders and press **Measure**. Try pure red, pure green, pure blue.
    Which channels light up for each?
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    led_form = mo.ui.dictionary(
        {
            "R": mo.ui.slider(0, 255, value=128, label="Red", show_value=True),
            "G": mo.ui.slider(0, 255, value=64, label="Green", show_value=True),
            "B": mo.ui.slider(0, 255, value=200, label="Blue", show_value=True),
        }
    ).form(submit_button_label="Measure")
    led_form
    return (led_form,)


@app.cell
def _(lab, led_form, mo, spectrum_plot):
    mo.stop(lab is None, mo.md("Connect to a device or the simulator first."))
    mo.stop(led_form.value is None, mo.md("Pick a color and press **Measure**."))

    _rgb = (led_form.value["R"], led_form.value["G"], led_form.value["B"])
    _readings = lab.measure(*_rgb)  # one experiment: send R, G, B, get 8 numbers back
    spectrum_plot(_readings, rgb=_rgb, title=f"Measured spectrum for RGB = {_rgb}")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. The target

    Your instructor picked a secret color. This is what the sensor sees when the LED
    shows it. Your job: find a color that produces the same pattern.
    """)
    return


@app.cell(hide_code=True)
def _(TARGET_SEED, lab, mo, np, spectrum_plot):
    mo.stop(lab is None, mo.md("Connect to a device or the simulator first."))
    _rng = np.random.default_rng(TARGET_SEED)
    _secret_rgb = [int(v) for v in _rng.integers(30, 226, size=3)]
    target_readings = lab.measure(*_secret_rgb)
    spectrum_plot(target_readings, title="Target spectrum (RGB hidden)")
    return (target_readings,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Scoring a guess

    We need one number that says how far a measurement $m$ is from the target $t$.
    A bright and a dim version of the same color give the same *shape* but different
    heights, so we first divide each spectrum by its total (turning counts into shares),
    then average the gaps over the 8 channels:

    $$\text{error} = \frac{1}{8}\sum_{i=1}^{8}\left|\frac{m_i}{\sum_j m_j} - \frac{t_i}{\sum_j t_j}\right|$$

    0 means a perfect match; lower is better. Because only the shape counts, a few
    different brightness levels can score almost equally well.
    """)
    return


@app.cell
def _(np):
    def normalize(readings):
        """Counts -> share of the total signal in each channel."""
        r = np.asarray(readings, dtype=float)
        return r / r.sum()


    def objective(readings, target):
        """Normalized mean absolute error between a measurement and the target."""
        return float(np.mean(np.abs(normalize(readings) - normalize(target))))

    return normalize, objective


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Three ways to choose the next experiment

    - **Random search:** pick any color. No memory of past results.
    - **Grid search:** try evenly spaced colors (for 25 experiments: 3 levels per channel,
      the first 25 of the 27 grid points). Systematic, but it never uses what it learns.
    - **Bayesian optimization (BO):** after each experiment, fit a model (a *Gaussian
      process*) that predicts the error for every possible color **and how unsure it is**.
      Then run the color with the highest **expected improvement**: one that is either
      predicted to be good, or uncertain enough that it might be. Balancing
      *exploit what looks good* against *explore what is unknown* is the core idea of a
      self-driving lab.

    The code below is the whole algorithm.
    """)
    return


@app.cell
def _(np, warnings):
    from scipy.stats import norm
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


    def suggest_random(rng):
        """Any color, uniformly at random."""
        return tuple(int(v) for v in rng.integers(0, 256, size=3))


    def suggest_grid(i, n_total):
        """The i-th point of an evenly spaced k x k x k grid, with k^3 >= n_total."""
        k = int(np.ceil(n_total ** (1 / 3) - 1e-9))
        levels = ((np.arange(k) + 0.5) * 256 / k).astype(int)  # k=3 -> 42, 128, 213
        r, g, b = np.unravel_index(i, (k, k, k))
        return (int(levels[r]), int(levels[g]), int(levels[b]))


    def suggest_bo(X, y, rng, n_init=5, n_candidates=3000):
        """Bayesian optimization with a Gaussian process and Expected Improvement."""
        # 0. With almost no data the model knows nothing: start with a few random colors.
        if len(X) < n_init:
            return suggest_random(rng)

        # 1. Data: scale colors to 0..1. Errors shrink by orders of magnitude as we
        #    get closer, so the model learns log(error) instead of error.
        Xs = np.array(X) / 255
        ys = np.log(np.array(y))

        # 2. Model: a Gaussian process. Matern = "nearby colors give similar errors",
        #    WhiteKernel = "measurements are a bit noisy".
        kernel = ConstantKernel(1.0) * Matern(
            length_scale=[0.3, 0.3, 0.3], length_scale_bounds=(1e-2, 10), nu=2.5
        ) + WhiteKernel(1e-3, noise_level_bounds=(1e-6, 1e-1))
        gp = GaussianProcessRegressor(kernel, normalize_y=True, n_restarts_optimizer=3, random_state=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # hide harmless fitting warnings
            gp.fit(Xs, ys)

        # 3. Candidates: many random colors, plus some close to the best one so far.
        best_x = Xs[np.argmin(ys)]
        near_best = np.clip(best_x + 0.05 * rng.standard_normal((n_candidates // 3, 3)), 0, 1)
        candidates = np.vstack([rng.random((n_candidates, 3)), near_best])

        # 4. Expected Improvement: how much better than our best do we expect each
        #    candidate to be, counting both the prediction (mu) and the uncertainty (sigma)?
        mu, sigma = gp.predict(candidates, return_std=True)
        sigma = np.maximum(sigma, 1e-9)
        improvement = ys.min() - mu
        z = improvement / sigma
        ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)

        # 5. Run the candidate with the highest EI next.
        return tuple(int(v) for v in np.round(candidates[np.argmax(ei)] * 255))


    def propose_next(method, X, y, rng, n_total):
        """Ask the chosen optimizer for the next color, given the history so far."""
        if method == "Random search":
            return suggest_random(rng)
        if method == "Grid search":
            return suggest_grid(len(X), n_total)
        return suggest_bo(X, y, rng)

    return (propose_next,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Run the self-driving lab

    Pick an optimizer and press **Run**. The plot updates after every experiment:
    on the left, the error of each experiment (dots are colored like the LED) and the
    best so far; on the right, the latest spectrum against the target.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    method = mo.ui.dropdown(
        options=["Random search", "Grid search", "Bayesian optimization"],
        value="Bayesian optimization",
        label="Optimizer",
    )
    n_iter = mo.ui.slider(5, 60, value=25, label="Experiments", show_value=True)
    run_button = mo.ui.run_button(label="Run", kind="success")
    mo.hstack([method, n_iter, run_button], justify="start", gap=2)
    return method, n_iter, run_button


@app.cell(hide_code=True)
def _(mo, target_readings):
    _ = target_readings  # a new target (or device) starts a fresh comparison
    get_runs, set_runs = mo.state({})
    return get_runs, set_runs


@app.cell
def _(
    lab,
    live_figure,
    method,
    mo,
    n_iter,
    np,
    objective,
    plt,
    propose_next,
    run_button,
    set_runs,
    target_readings,
):
    mo.stop(not run_button.value, mo.md("Press **Run** to start."))

    _rng = np.random.default_rng()
    _X, _y = [], []  # colors tried, and their errors
    try:
        for _ in range(n_iter.value):
            _rgb = propose_next(method.value, _X, _y, _rng, n_iter.value)  # 1. decide
            _readings = lab.measure(*_rgb)  # 2. experiment
            _X.append(_rgb)
            _y.append(objective(_readings, target_readings))  # 3. score

            _fig = live_figure(_X, _y, _readings, target_readings, method.value, n_iter.value)
            mo.output.replace(_fig)  # 4. show it live
            plt.close(_fig)
    finally:
        if _y:  # keep the run (even a partial one) for the comparison below
            set_runs(lambda runs: {**runs, method.value: {"X": list(_X), "y": list(_y)}})

    _best = int(np.argmin(_y))
    mo.output.append(
        mo.md(f"**Best:** error {_y[_best]:.4f} with RGB = {_X[_best]}, found at experiment {_best + 1}.")
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Compare the optimizers

    Run each optimizer at least once. The latest run of each is kept here.
    Which one reaches a low error in the fewest experiments? Run them again: does the
    ranking hold?
    """)
    return


@app.cell(hide_code=True)
def _(comparison_figure, get_runs, mo, np):
    _runs = get_runs()
    mo.stop(not _runs, mo.md("No runs yet."))

    _rows = []
    for _name, _r in _runs.items():
        _i = int(np.argmin(_r["y"]))
        _rows.append(
            f"| {_name} | {len(_r['y'])} | {_r['y'][_i]:.4f} | {_r['X'][_i]} | {_i + 1} |"
        )
    _table = mo.md(
        "| Optimizer | Experiments | Best error | Best RGB | Found at |\n"
        "|---|---|---|---|---|\n" + "\n".join(_rows)
    )
    mo.vstack([comparison_figure(_runs), _table])
    return


@app.cell(hide_code=True)
def _(CHANNELS, normalize, np, plt):
    # ---------------- Plot helpers ----------------
    WAVELENGTHS = [int(c[2:]) for c in CHANNELS]
    CHANNEL_COLORS = ["#7b2fbe", "#3b3bff", "#0f8bff", "#00b84a", "#9ccc00", "#ffb300", "#ff6d00", "#d50000"]
    METHOD_COLORS = {"Random search": "#8a8a8a", "Grid search": "#e08a00", "Bayesian optimization": "#1f5fd6"}


    def _swatch(ax, rgb):
        ax.set_ylim(top=ax.get_ylim()[1] * 1.45)  # headroom so the swatch never covers bars
        sw = ax.inset_axes([0.86, 0.72, 0.12, 0.24])
        sw.set_facecolor(np.array(rgb) / 255)
        sw.set_xticks([])
        sw.set_yticks([])
        sw.set_title("LED", fontsize=8)


    def spectrum_plot(readings, rgb=None, title=""):
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.bar([str(w) for w in WAVELENGTHS], readings, color=CHANNEL_COLORS)
        ax.set_xlabel("Sensor channel (nm)")
        ax.set_ylabel("Counts")
        ax.set_title(title)
        if rgb is not None:
            _swatch(ax, rgb)
        fig.tight_layout()
        plt.close(fig)
        return fig


    def live_figure(X, y, readings, target, method, n_total):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8))
        it = np.arange(1, len(y) + 1)

        ax1.scatter(it, y, s=28, c=[np.array(x) / 255 for x in X], edgecolors="0.3",
                    linewidths=0.6, zorder=3, label="each experiment")
        ax1.plot(it, np.minimum.accumulate(y), color="black", lw=2, label="best so far")
        ax1.set_yscale("log")
        ax1.set_xlim(0.5, n_total + 0.5)
        ax1.set_xlabel("Experiment")
        ax1.set_ylabel("Error (log scale)")
        ax1.legend(loc="best", fontsize=8)

        x = np.arange(len(WAVELENGTHS))
        w = 0.4
        ax2.bar(x - w / 2, normalize(target), w, color="white", edgecolor="black", label="target")
        ax2.bar(x + w / 2, normalize(readings), w, color=CHANNEL_COLORS, label="this experiment")
        ax2.set_xticks(x, [str(v) for v in WAVELENGTHS])
        ax2.set_xlabel("Sensor channel (nm)")
        ax2.set_ylabel("Share of total signal")
        ax2.legend(loc="upper left", fontsize=8)
        _swatch(ax2, X[-1])

        fig.suptitle(f"{method}: experiment {len(y)}/{n_total}, RGB = {X[-1]}, error = {y[-1]:.4f}")
        fig.tight_layout()
        return fig


    def comparison_figure(runs):
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for name, r in runs.items():
            it = np.arange(1, len(r["y"]) + 1)
            ax.plot(it, np.minimum.accumulate(r["y"]), lw=2, label=name,
                    color=METHOD_COLORS.get(name))
        ax.set_yscale("log")
        ax.set_xlabel("Experiment")
        ax.set_ylabel("Best error so far (log scale)")
        ax.legend(fontsize=9)
        fig.tight_layout()
        plt.close(fig)
        return fig

    return comparison_figure, live_figure, spectrum_plot


if __name__ == "__main__":
    app.run()
