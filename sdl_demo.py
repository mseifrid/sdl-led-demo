# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "matplotlib",
#     "numpy",
#     "paho-mqtt>=2.0",
#     "plotly==7.2.0",
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
def _(TARGET_SEED, np):
    # The secret color, picked from TARGET_SEED in the settings cell.
    # Changing the seed (or the device) starts a fresh optimizer comparison.
    _rng = np.random.default_rng(TARGET_SEED)
    target_rgb = tuple(int(v) for v in _rng.integers(30, 226, size=3))
    return (target_rgb,)


@app.cell(hide_code=True)
def _(lab, mo, spectrum_plot, target_rgb):
    mo.stop(lab is None, mo.md("Connect to a device or the simulator first."))
    target_readings = lab.measure(*target_rgb)
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
    ## 4. Eight ways to choose the next experiment

    - **Random search:** pick any color. No memory of past results.
    - **Grid search:** try evenly spaced colors (for 25 experiments: 3 levels per channel,
      the first 25 of the 27 grid points). Systematic, but it never uses what it learns.
    - **Sobol sampling:** a *quasi-random* sequence designed so that every new point
      fills the biggest remaining gap. Covers the color space more evenly than random
      search, for any number of experiments.
    - **Latin hypercube sampling (LHS):** cut each channel (R, G, B) into as many equal
      slices as there are experiments, and use every slice exactly once. No brightness
      level of any channel is skipped or repeated.

    These four are *space-filling* designs: they plan where to look without ever
    looking at the results. The next three do use the results, but without a model:

    - **Successive halving (random or grid):** the idea behind scikit-learn's
      `HalvingRandomSearchCV` and `HalvingGridSearchCV`. Measure many candidate colors once,
      keep the best third, measure the survivors 3 times each, keep the best third again, and
      so on: a quick look at everyone, careful repeated measurements for the finalists. Here
      the "resource" is how many times a color is measured (repeats average out sensor noise).
      The random version picks as many random candidates as the budget allows; the grid
      version uses the largest grid it can measure at least once (2 × 2 × 2 below 27
      experiments, 3 × 3 × 3 from 27) and drops rounds that don't fit. Experiments left
      over at the end go to re-measuring the current leaders.
    - **Nelder–Mead (simplex):** a classic local search. Start with 4 colors (a *simplex*,
      the 3-D version of a triangle), then repeatedly replace the worst corner by reflecting
      it through the others: stretch further when that works, pull in when it doesn't.
      It only compares errors, walks downhill from a random start, and can get stuck in a
      local dip.

    - **Bayesian optimization (BO):** after each experiment, fit a model (a *Gaussian
      process*) that predicts the error for every possible color **and how unsure it is**.
      Then an **acquisition function** turns that prediction and uncertainty into a
      single score, and BO runs the color with the best score. Balancing
      *exploit what looks good* against *explore what is unknown* is the core idea of a
      self-driving lab, and each acquisition function strikes that balance differently:
        - **Expected improvement (EI):** how much better than the best so far do we expect
          this color to be? Rewards both a low prediction and high uncertainty.
        - **Probability of improvement (PI):** how *likely* is this color to beat the best?
          Ignores by how much, so it tends to play it safe (exploit).
        - **Confidence bound (UCB/LCB):** an optimistic guess,
          prediction $-\;\beta \times$ uncertainty (it's called UCB when maximizing; we minimize error, so it's the
          *lower* bound). $\beta = 0$ trusts the prediction only; a large $\beta$ chases
          uncertainty. Each $\beta$ you try is saved as its own run.
        - **Thompson sampling:** draw one random but plausible error landscape from the
          model and run its lowest point. The randomness does the exploring.

    The code below is the whole algorithm.
    """)
    return


@app.cell
def _(np, objective, warnings):
    import itertools

    from scipy.stats import norm, qmc
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


    class Space:
        """Where an optimizer searches. Every optimizer below thinks in the unit cube [0, 1]^d;
        the space turns those points into actual settings, and back.

        levels=256: integer settings 0..255 in each dimension (the LED: R, G, B).
        levels=None: continuous coordinates in [0, 1] (the benchmark surfaces of section 10).
        """

        def __init__(self, d, levels=None):
            self.d = d
            self.levels = levels
            # Nelder-Mead restarts once its simplex is smaller than this (about one setting)
            self.tol = 1.5 / (levels - 1) if levels else 1e-6

        def point(self, u):
            """Unit-cube point -> setting (a tuple, so it can be compared and counted)."""
            u = np.clip(np.asarray(u, dtype=float), 0, 1)
            if self.levels:
                return tuple(int(v) for v in np.round(u * (self.levels - 1)))
            return tuple(float(v) for v in u)

        def unit(self, X):
            """Settings -> unit-cube coordinates (array of shape n x d)."""
            X = np.asarray(X, dtype=float)
            return X / (self.levels - 1) if self.levels else X


    LED_SPACE = Space(3, levels=256)  # R, G, B in 0..255


    def suggest_random(rng, space=LED_SPACE):
        """Any setting, uniformly at random."""
        return space.point(rng.random(space.d))


    def suggest_grid(i, n_total, space=LED_SPACE):
        """The i-th point of an evenly spaced k x k x ... grid, with k^d >= n_total."""
        k = int(np.ceil(n_total ** (1 / space.d) - 1e-9))
        levels = (np.arange(k) + 0.5) / k  # k=3 -> 1/6, 1/2, 5/6 (RGB 42, 128, 212)
        return space.point(levels[list(np.unravel_index(i, (k,) * space.d))])


    def sobol_design(n_total, rng, d=3):
        """Scrambled Sobol sequence: a low-discrepancy sequence that fills the cube evenly.

        Sobol points are best balanced in powers of 2, so we draw the next power of 2
        and use the first n_total points (any prefix of a Sobol sequence is still well spread).
        """
        m = int(np.ceil(np.log2(max(n_total, 1))))
        return qmc.Sobol(d=d, scramble=True, rng=rng).random_base2(m)[:n_total]


    def lhs_design(n_total, rng, d=3):
        """Latin hypercube: split each dimension into n_total equal slices and use
        every slice exactly once per dimension, in a random pairing across dimensions."""
        return qmc.LatinHypercube(d=d, rng=rng).random(n_total)


    def fit_gp(X, y, space=LED_SPACE):
        """Fit a Gaussian process that predicts log(error) from a setting.

        Settings are scaled to 0..1. Errors shrink by orders of magnitude as we get
        closer, so the model learns log(error) instead of error.
        Matern = "nearby settings give similar errors", WhiteKernel = "measurements are a bit noisy".
        """
        Xs = space.unit(X)
        ys = np.log(np.array(y))
        kernel = ConstantKernel(1.0) * Matern(
            length_scale=[0.3] * space.d, length_scale_bounds=(1e-2, 10), nu=2.5
        ) + WhiteKernel(1e-3, noise_level_bounds=(1e-6, 1e-1))
        gp = GaussianProcessRegressor(kernel, normalize_y=True, n_restarts_optimizer=3, random_state=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # hide harmless fitting warnings
            gp.fit(Xs, ys)
        return gp


    def expected_improvement(mu, sigma, best_log):
        """How much better than our best (in log error) we expect each candidate to be,
        counting both the prediction (mu) and the uncertainty (sigma).

        Returns (EI, exploit part, explore part); EI = exploit + explore.
        """
        sigma = np.maximum(sigma, 1e-9)
        improvement = best_log - mu
        z = improvement / sigma
        exploit = improvement * norm.cdf(z)  # large where the model predicts a low error
        explore = sigma * norm.pdf(z)  # large where the model is unsure
        return exploit + explore, exploit, explore


    def probability_of_improvement(mu, sigma, best_log, xi=0.0):
        """Chance that a candidate beats the best so far (ignores *how much* better)."""
        sigma = np.maximum(sigma, 1e-9)
        return norm.cdf((best_log - mu - xi) / sigma)


    def lower_confidence_bound(mu, sigma, beta):
        """Optimistic guess of the (log) error: mu - beta * sigma. Lower is better.

        This is UCB turned upside down: we minimize error, so we use the lower bound.
        beta sets the trade-off: 0 = trust the prediction only (exploit),
        large beta = chase uncertainty (explore).
        """
        return mu - beta * sigma


    ACQUISITIONS = {
        "Expected improvement (EI)": "EI",
        "Probability of improvement (PI)": "PI",
        "Confidence bound (UCB/LCB)": "LCB",
        "Thompson sampling": "TS",
    }


    def suggest_bo(X, y, rng, acq="EI", beta=2.0, n_init=5, n_candidates=3000, space=LED_SPACE):
        """Bayesian optimization with a Gaussian process and an acquisition function.

        acq: "EI" (expected improvement), "PI" (probability of improvement),
             "LCB" (lower confidence bound, uses beta), "TS" (Thompson sampling).
        """
        # 0. With almost no data the model knows nothing: start with a few random settings.
        if len(X) < n_init:
            return suggest_random(rng, space)

        # 1-2. Model: fit a Gaussian process to log(error).
        gp = fit_gp(X, y, space)
        Xs = space.unit(X)
        best_log = np.log(min(y))

        # 3. Candidates: many random settings, plus some close to the best one so far.
        #    Thompson sampling draws one joint sample over all candidates, which gets slow
        #    quickly, so it uses fewer candidates.
        if acq == "TS":
            n_candidates = 750
        best_x = Xs[int(np.argmin(y))]
        near_best = np.clip(best_x + 0.05 * rng.standard_normal((n_candidates // 3, space.d)), 0, 1)
        candidates = np.vstack([rng.random((n_candidates, space.d)), near_best])

        # 4. Score every candidate with the acquisition function (higher score = run it).
        if acq == "TS":
            # Draw one plausible error landscape from the GP and pick its lowest point.
            sample = gp.sample_y(candidates, random_state=int(rng.integers(2**31))).ravel()
            score = -sample
        else:
            mu, sigma = gp.predict(candidates, return_std=True)
            if acq == "PI":
                score = probability_of_improvement(mu, sigma, best_log)
            elif acq == "LCB":
                score = -lower_confidence_bound(mu, sigma, beta)
            else:
                score, _, _ = expected_improvement(mu, sigma, best_log)

        # 5. Run the best-scoring candidate next.
        return space.point(candidates[np.argmax(score)])


    def run_label(method, acq="EI", beta=2.0):
        """Name a run for the comparison: each BO acquisition (and each LCB beta) is its own run."""
        if method != "Bayesian optimization":
            return method
        if acq == "LCB":
            return f"BO: LCB β={beta:g}"
        return {"EI": "BO: EI", "PI": "BO: PI", "TS": "BO: Thompson"}[acq]


    def queue_entry(method, acq="EI", beta=2.0):
        """One item of an optimizer list (sections 9 and 10)."""
        acq = acq if method == "Bayesian optimization" else None
        beta = beta if acq == "LCB" else None
        return {"label": run_label(method, acq, beta), "method": method, "acq": acq, "beta": beta}


    METHODS = [
        "Random search",
        "Grid search",
        "Sobol sampling",
        "Latin hypercube",
        "Halving random search",
        "Halving grid search",
        "Nelder-Mead",
        "Bayesian optimization",
    ]


    # ---------- Successive halving (like scikit-learn's HalvingRandomSearchCV / HalvingGridSearchCV) ----------
    # The "resource" is how many times a setting is measured: repeats average out noise.
    # Round 0: every candidate is measured once. Each later round keeps the best 1/factor
    # (by average error) and measures the survivors factor times as often in total.

    def _halving_round_costs(n_candidates, factor=3):
        """Candidates per round and the experiments each round adds (1 measurement in round 0)."""
        n_rounds = 1 + int(np.floor(np.log(n_candidates) / np.log(factor) + 1e-9))
        cands = [n_candidates]
        for _ in range(n_rounds - 1):
            cands.append(int(np.ceil(cands[-1] / factor)))
        # survivors only need the *extra* measurements: factor**i - factor**(i-1)
        costs = [n * (factor**i - (factor ** (i - 1) if i else 0)) for i, n in enumerate(cands)]
        return cands, costs


    def halving_rounds(n_candidates, n_total, factor=3):
        """Schedule [(candidates, measurements per candidate), ...] that fits in n_total.

        Like scikit-learn: n_rounds = 1 + floor(log_factor(n_candidates)) and each round keeps
        ceil(n / factor). If the budget is too small, later rounds are dropped (scikit-learn's
        max_resources); if it is large, all measurement counts are scaled up ("exhaust").
        """
        cands, costs = _halving_round_costs(n_candidates, factor)
        while len(cands) > 1 and sum(costs) > n_total:
            cands.pop()
            costs.pop()
        r0 = max(1, n_total // sum(costs))
        return [(n, r0 * factor**i) for i, n in enumerate(cands)]


    def halving_design(method, n_total, rng, space=LED_SPACE, factor=3):
        """Pick the candidate settings and the schedule for a budget of n_total experiments."""
        if method == "Halving random search":
            # as many random candidates as fit with the full schedule
            n = max(k for k in range(1, n_total + 1) if sum(_halving_round_costs(k, factor)[1]) <= n_total)
            candidates = [space.point(u) for u in rng.random((n, space.d))]
        else:
            # the largest full k x k x ... grid that can be measured at least once
            k = max(k for k in range(1, n_total + 1) if k**space.d <= n_total)
            levels = (np.arange(k) + 0.5) / k  # k=2 -> RGB 64, 191; k=3 -> RGB 42, 128, 212
            candidates = [space.point(p) for p in itertools.product(levels, repeat=space.d)]
        return {"candidates": candidates, "rounds": halving_rounds(len(candidates), n_total, factor),
                "factor": factor}


    def _mean_error(point, X, y):
        vals = [yi for xi, yi in zip(X, y) if tuple(xi) == tuple(point)]
        return float(np.mean(vals)) if vals else np.inf


    def suggest_halving(X, y, design, n_total):
        """Next setting to measure under the successive-halving schedule, given the history."""
        def best(points, n, done):  # the n points with the lowest average error so far
            return sorted(points, key=lambda c: _mean_error(c, X[:done], y[:done]))[:n]

        survivors, done, prev_r = list(design["candidates"]), 0, 0
        for i, (n_i, r_i) in enumerate(design["rounds"]):
            if i > 0:
                survivors = best(survivors, n_i, done)
            cost = n_i * (r_i - prev_r)
            if len(X) < done + cost:
                return survivors[(len(X) - done) % n_i]  # take turns: one extra measurement each
            done, prev_r = done + cost, r_i
        # Budget left after the last round: keep re-measuring the current leaders.
        leaders = best(survivors, max(1, int(np.ceil(len(survivors) / design["factor"]))), done)
        return leaders[(len(X) - done) % len(leaders)]


    # ---------- Nelder-Mead (downhill simplex) ----------

    def _nelder_mead(x0, step=0.25, tol=1.5 / 255):
        """Nelder-Mead on the unit cube, written as a generator:
        it yields a point to measure and receives that point's error via send()."""
        d = len(x0)

        def clip(p):
            return np.clip(p, 0.0, 1.0)

        def start(center, h):  # a simplex of d + 1 corners around a point
            pts = [clip(np.asarray(center, dtype=float))]
            for i in range(d):
                p = pts[0].copy()
                p[i] += h if p[i] + h <= 1 else -h
                pts.append(p)
            return pts

        simplex = start(x0, step)
        f = []
        for p in simplex:
            f.append((yield p))
        while True:
            order = np.argsort(f)  # best first, worst last
            simplex, f = [simplex[i] for i in order], [f[i] for i in order]
            if max(np.abs(p - simplex[0]).max() for p in simplex) < tol:
                # collapsed to (almost) one point: restart a smaller simplex around the best
                simplex = start(simplex[0], step / 2.5)
                f = [f[0]] + [None] * d
                for i in range(1, d + 1):
                    f[i] = yield simplex[i]
                continue
            centroid = np.mean(simplex[:-1], axis=0)  # middle of all corners except the worst
            xr = clip(centroid + (centroid - simplex[-1]))  # reflect the worst corner
            fr = yield xr
            if fr < f[0]:  # best so far: try going twice as far
                xe = clip(centroid + 2 * (centroid - simplex[-1]))
                fe = yield xe
                simplex[-1], f[-1] = (xe, fe) if fe < fr else (xr, fr)
            elif fr < f[-2]:  # better than the second worst: keep the reflection
                simplex[-1], f[-1] = xr, fr
            else:  # contract toward the centroid
                xc = centroid + 0.5 * ((xr if fr < f[-1] else simplex[-1]) - centroid)
                fc = yield xc
                if fc < min(fr, f[-1]):
                    simplex[-1], f[-1] = xc, fc
                else:  # shrink every corner toward the best one
                    for i in range(1, d + 1):
                        simplex[i] = simplex[0] + 0.5 * (simplex[i] - simplex[0])
                        f[i] = yield simplex[i]


    def suggest_nelder_mead(y, x0, space=LED_SPACE):
        """Replay Nelder-Mead on the errors measured so far, return the next setting to measure."""
        gen = _nelder_mead(x0, tol=space.tol)
        p = next(gen)
        for value in y:
            p = gen.send(value)
        return space.point(p)


    def make_design(method, n_total, rng, space=LED_SPACE):
        """Plan made at the start of a run (None for methods that need no plan):
        Sobol / LHS: all points; halving: candidates + schedule; Nelder-Mead: random start."""
        if method == "Sobol sampling":
            return sobol_design(n_total, rng, space.d)
        if method == "Latin hypercube":
            return lhs_design(n_total, rng, space.d)
        if method in ("Halving random search", "Halving grid search"):
            return halving_design(method, n_total, rng, space)
        if method == "Nelder-Mead":
            return rng.random(space.d)
        return None


    def propose_next(method, X, y, rng, n_total, design=None, acq="EI", beta=2.0, space=LED_SPACE):
        """Ask the chosen optimizer for the next setting, given the history so far."""
        if method == "Random search":
            return suggest_random(rng, space)
        if method == "Grid search":
            return suggest_grid(len(X), n_total, space)
        if method in ("Sobol sampling", "Latin hypercube"):  # take the next planned point
            return space.point(design[len(X)])
        if method in ("Halving random search", "Halving grid search"):
            return suggest_halving(X, y, design, n_total)
        if method == "Nelder-Mead":
            return suggest_nelder_mead(y, design, space)
        return suggest_bo(X, y, rng, acq=acq, beta=beta, space=space)


    def optimize(method, n_total, evaluate, rng, space=LED_SPACE, acq="EI", beta=2.0,
                 X=None, y=None, on_step=None):
        """One full optimization of any problem: decide -> experiment -> score, n_total times.

        evaluate: function setting -> (error, extra info); lower error is better, error > 0.
        X, y: optional lists to fill in place, so a caller keeps partial results if stopped.
        on_step: optional function (X, y, info) called after every experiment.
        """
        X = [] if X is None else X
        y = [] if y is None else y
        design = make_design(method, n_total, rng, space)  # plan made up front (if any)
        while len(X) < n_total:
            x = propose_next(method, X, y, rng, n_total, design, acq, beta, space)  # 1. decide
            err, info = evaluate(x)  # 2. experiment + 3. score
            X.append(x)
            y.append(err)
            if on_step is not None:
                on_step(X, y, info)
        return X, y


    def run_optimization(method, n_total, measure, target, rng, acq="EI", beta=2.0,
                         X=None, y=None, on_step=None):
        """Optimize the LED: measure(R, G, B) -> 8 readings, scored against the target spectrum.

        on_step: optional function (X, y, readings) called after every experiment.
        """
        def evaluate(rgb):
            readings = measure(*rgb)  # 2. experiment
            return objective(readings, target), readings  # 3. score

        return optimize(method, n_total, evaluate, rng, LED_SPACE, acq, beta, X, y, on_step)


    return (
        ACQUISITIONS,
        METHODS,
        Space,
        expected_improvement,
        fit_gp,
        lower_confidence_bound,
        optimize,
        probability_of_improvement,
        queue_entry,
        run_label,
        run_optimization,
        suggest_bo,
    )


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
def _(ACQUISITIONS, METHODS, mo):
    method = mo.ui.dropdown(
        options=METHODS,
        value="Bayesian optimization",
        label="Optimizer",
    )
    acq = mo.ui.dropdown(
        options=ACQUISITIONS, value="Expected improvement (EI)", label="Acquisition"
    )
    beta = mo.ui.slider(0, 6, step=0.5, value=2, label="\u03b2", show_value=True)
    n_iter = mo.ui.slider(5, 100, value=25, label="Experiments", show_value=True)
    run_button = mo.ui.run_button(label="Run", kind="success")
    return acq, beta, method, n_iter, run_button


@app.cell(hide_code=True)
def _(acq, beta, method, mo, n_iter, run_button):
    # BO settings only appear when they matter.
    _bo_settings = []
    if method.value == "Bayesian optimization":
        _bo_settings.append(acq)
        if acq.value == "LCB":
            _bo_settings.append(beta)
    mo.vstack([
        mo.hstack([method, *_bo_settings], justify="start", gap=2),
        mo.hstack([n_iter, run_button], justify="start", gap=2),
    ])
    return


@app.cell(hide_code=True)
def _(lab, mo, target_rgb):
    # Runs are kept per target color and device: a new target or device starts a fresh
    # comparison. (Re-measuring the same target, e.g. after editing a plot helper, does not.)
    _ = (target_rgb, lab)
    get_runs, set_runs = mo.state({})
    return get_runs, set_runs


@app.cell(hide_code=True)
def _(mo, set_runs):
    clear_button = mo.ui.button(
        label="Clear comparison", kind="danger", on_click=lambda _: set_runs({})
    )
    return (clear_button,)


@app.cell
def _(
    acq,
    beta,
    lab,
    live_figure,
    method,
    mo,
    n_iter,
    np,
    plt,
    run_button,
    run_label,
    run_optimization,
    set_runs,
    target_readings,
):
    mo.stop(not run_button.value, mo.md("Press **Run** to start."))

    _rng = np.random.default_rng()
    _label = run_label(method.value, acq.value, beta.value)  # e.g. "BO: LCB \u03b2=2"
    _X, _y = [], []  # colors tried, and their errors (filled in as the run goes)


    def _show(X, y, readings):  # 4. show every experiment live
        _fig = live_figure(X, y, readings, target_readings, _label, n_iter.value)
        mo.output.replace(_fig)
        plt.close(_fig)


    try:
        run_optimization(
            method.value, n_iter.value, lab.measure, target_readings, _rng,
            acq=acq.value, beta=beta.value, X=_X, y=_y, on_step=_show,
        )
    finally:
        if _y:  # keep the run (even a partial one) for the comparison below
            _record = {
                "X": list(_X), "y": list(_y), "method": method.value,
                "acq": acq.value, "beta": beta.value if acq.value == "LCB" else None,
            }
            # re-running the same settings replaces that run and moves it to the end
            set_runs(lambda runs: {**{k: v for k, v in runs.items() if k != _label}, _label: _record})

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

    Press **Clear comparison** to start over. Picking a new target color
    (or switching device) clears it automatically.
    """)
    return


@app.cell(hide_code=True)
def _(clear_button, comparison_figure, get_runs, mo, np):
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
    mo.vstack([clear_button, comparison_figure(_runs), _table])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 7. Look inside Bayesian optimization

    Run **Bayesian optimization** in section 5, pick a run, then move the slider to replay it.
    At each step the Gaussian process is refit on the experiments done so far, and we
    show what it believed *before* choosing the next color.

    The color space has three dimensions (R, G, B), so we can't draw it all at once.
    Instead each column is a **slice**: one channel sweeps from 0 to 255 while the other
    two stay at the color BO picks next (the solid vertical line).

    - **Top row:** the model's predicted error (line) and how unsure it is (shaded band).
      Dots are past experiments; faint dots are far from this slice in the other two channels.
    - **Bottom row:** the acquisition function the run used. BO runs its best color:
      the peak for EI and PI, the lowest point for LCB and Thompson sampling. So the best
      spot usually lines up with the vertical line. BO only scores a few thousand
      random candidate colors, though, so sometimes a slice shows a better spot the
      candidates missed. Can you spot one? (For Thompson sampling every slice is a new
      random draw, so expect less agreement.)

    Watch the band shrink where experiments pile up, and the acquisition move from wide,
    uncertain regions (*explore*) to the neighborhood of the best color (*exploit*).
    Compare LCB with a small and a large $\beta$.
    """)
    return


@app.cell(hide_code=True)
def _(get_runs, mo):
    _runs = get_runs()
    bo_runs = {
        _name: _r for _name, _r in _runs.items()
        if _r.get("method", _name) == "Bayesian optimization" and len(_r["y"]) >= 5
    }
    mo.stop(
        not bo_runs,
        mo.md("Run **Bayesian optimization** (at least 5 experiments) in section 5 first."),
    )
    bo_choice = mo.ui.dropdown(
        options=list(bo_runs), value=list(bo_runs)[-1], label="BO run to replay"
    )
    return bo_choice, bo_runs


@app.cell(hide_code=True)
def _(bo_choice, bo_runs, mo):
    bo_run = bo_runs[bo_choice.value]
    bo_step = mo.ui.slider(
        5, len(bo_run["y"]), value=5, step=1, show_value=True, full_width=True, debounce=True,
        label="Experiments the model has seen",
    )
    mo.vstack([bo_choice, bo_step])
    return bo_run, bo_step


@app.cell(hide_code=True)
def _(
    bo_choice,
    bo_run,
    bo_step,
    expected_improvement,
    fit_gp,
    gp_slices_figure,
    mo,
    np,
    probability_of_improvement,
    suggest_bo,
):
    _k = bo_step.value
    _acq, _beta = bo_run.get("acq", "EI"), bo_run.get("beta") or 2.0
    _X, _y = bo_run["X"][:_k], bo_run["y"][:_k]
    _gp = fit_gp(_X, _y)
    _next = suggest_bo(_X, _y, np.random.default_rng(_k), acq=_acq, beta=_beta)
    _actual = bo_run["X"][_k] if _k < len(bo_run["X"]) else None

    # Why this color? Explain the pick in terms of the run's acquisition function.
    _best_log = np.log(min(_y))
    _mu, _sd = _gp.predict(np.array([_next]) / 255, return_std=True)
    _mu, _sd = float(_mu[0]), float(_sd[0])
    if _acq == "EI":
        _, _exploit, _explore = expected_improvement(np.array([_mu]), np.array([_sd]), _best_log)
        _why = (
            "is mostly **exploiting**: the model predicts a low error here"
            if _exploit[0] >= _explore[0]
            else "is mostly **exploring**: the model is unsure about this region"
        )
    elif _acq == "PI":
        _p = float(probability_of_improvement(_mu, _sd, _best_log))
        _why = (
            f"has a {_p:.0%} chance of beating the best so far. PI ignores *how much* better, "
            "so it tends to pick safe colors close to the best one"
        )
    elif _acq == "LCB":
        _why = (
            f"has the lowest optimistic guess: prediction {_mu:.2f} minus "
            f"\u03b2\u00b7\u03c3 = {_beta:g} \u00d7 {_sd:.2f} = {_beta * _sd:.2f} (log units). "
            + ("The uncertainty bonus dominates, so it is **exploring**"
               if _beta * _sd > abs(_mu - _best_log) else
               "The prediction dominates, so it is **exploiting**")
        )
    else:
        _why = (
            "is the lowest point of one random landscape drawn from the GP. "
            "Where the model is unsure, draws vary a lot, which makes Thompson sampling explore"
        )
    _note = (
        "" if _actual is None or tuple(_actual) == _next
        else f" The run actually used RGB = {tuple(_actual)} (dashed line): the replay draws a new "
        "random set of candidate colors"
        + (" and a new random landscape" if _acq == "TS" else "")
        + ", so it can land on a different color."
    )
    mo.vstack([
        gp_slices_figure(_X, _y, _gp, _next, x_actual=_actual, acq=_acq, beta=_beta,
                         rng=np.random.default_rng(_k)),
        mo.md(f"**{bo_choice.value}**: next pick RGB = {_next} {_why} "
              f"(predicted error {np.exp(_mu):.4f}, uncertainty \u03c3 = {_sd:.2f} in log units).{_note}"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 8. The whole color cube in 3-D

    Section 7 showed three lines through the color cube. Here is the whole cube, sampled
    on a coarse 11 × 11 × 11 grid of colors (a step of about 25 per channel). The three
    axes are the LED channels R, G and B, so every point *is* a color, and the point's
    color shows a number the Gaussian process computes there:

    - **Predicted error:** log₁₀ of the error the model expects for that color.
    - **Uncertainty:** how unsure the model is (σ, in log units).
    - **Acquisition:** the function the run used to pick colors (log₁₀ EI, log₁₀ PI,
      the LCB value, or one Thompson sample).

    In all three, **bright means interesting**: low predicted error, high uncertainty,
    or most worth trying next. Past experiments are shown in their LED color with a black
    outline; the red **✕** is the color BO picks next.

    The run and step are the same as in section 7 (the sliders are linked). A full cube hides
    its own inside, so lower **Show top %** to keep only the most interesting points:
    at 10 % you see where the model thinks the good colors are, where it is unsure, and where
    BO wants to go next. Drag to rotate, scroll to zoom, hover for values.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    cube_top = mo.ui.slider(5, 100, value=100, step=5, label="Show top %", show_value=True)
    cube_opacity = mo.ui.slider(0.05, 1.0, value=0.35, step=0.05, label="Opacity", show_value=True)
    return cube_opacity, cube_top


@app.cell(hide_code=True)
def _(bo_choice, bo_step, cube_opacity, cube_top, mo):
    mo.vstack([
        mo.hstack([bo_choice, bo_step], justify="start", gap=2, widths=[1, 3]),
        mo.hstack([cube_top, cube_opacity], justify="start", gap=2),
    ])
    return


@app.cell(hide_code=True)
def _(
    bo_run,
    bo_step,
    expected_improvement,
    fit_gp,
    lower_confidence_bound,
    np,
    probability_of_improvement,
    suggest_bo,
):
    # Evaluate the GP and the run's acquisition function on an 11 x 11 x 11 grid of colors.
    _k = bo_step.value
    _acq, _beta = bo_run.get("acq", "EI"), bo_run.get("beta") or 2.0
    _X, _y = bo_run["X"][:_k], bo_run["y"][:_k]
    _gp = fit_gp(_X, _y)

    _levels = np.linspace(0, 255, 11)
    _pts = np.stack(np.meshgrid(_levels, _levels, _levels, indexing="ij"), axis=-1).reshape(-1, 3)
    _mu, _sd = _gp.predict(_pts / 255, return_std=True)
    _best_log = np.log(min(_y))

    if _acq in ("EI", "PI"):  # higher is better; spans many orders of magnitude -> log10
        if _acq == "EI":
            _a, _, _ = expected_improvement(_mu, _sd, _best_log)
        else:
            _a = probability_of_improvement(_mu, _sd, _best_log)
        _acq_value = np.log10(np.maximum(_a, _a.max() * 1e-6))  # floor: 6 decades below the top
        _acq_name, _acq_label, _higher = (
            ("Expected improvement", "log\u2081\u2080 EI", True) if _acq == "EI"
            else ("Probability of improvement", "log\u2081\u2080 PI", True)
        )
    elif _acq == "LCB":  # lower is better, already a log error
        _acq_value = lower_confidence_bound(_mu, _sd, _beta) / np.log(10)
        _acq_name, _acq_label, _higher = (f"LCB (\u03b2={_beta:g})", "log\u2081\u2080 optimistic error", False)
    else:  # Thompson sampling: one random landscape, lower is better
        _s = _gp.sample_y(_pts / 255, random_state=_k).ravel()
        _acq_value = _s / np.log(10)
        _acq_name, _acq_label, _higher = ("Thompson sample", "log\u2081\u2080 sampled error", False)

    cube = {
        "pts": _pts,
        "mean": _mu / np.log(10),  # GP models ln(error); show log10(error)
        "sigma": _sd,
        "acq": _acq_value, "acq_name": _acq_name, "acq_label": _acq_label, "acq_higher": _higher,
        "X": _X,
        "next": suggest_bo(_X, _y, np.random.default_rng(_k), acq=_acq, beta=_beta),  # same pick as section 7
        "k": _k,
    }
    return (cube,)


@app.cell(hide_code=True)
def _(bo_choice, cube, cube_figure, cube_opacity, cube_top, mo):
    mo.vstack([
        cube_figure(cube, top_pct=cube_top.value, opacity=cube_opacity.value),
        mo.md(
            f"**{bo_choice.value}** after {cube['k']} experiments; next pick RGB = {cube['next']} (red \u2715). "
            f"Showing the top {cube_top.value}% of {len(cube['pts'])} grid colors in each panel."
        ),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 9. Replicates: is the winner really better?

    A single run is partly luck: a different first random color, or a bit of sensor noise,
    can change the ranking. Here you build a **list of optimizations**, choose how many
    **replicates** to run of each, and compare the **average** best-so-far curve, with a
    band of ± one standard deviation (SD) showing how much the replicates spread.

    - Every replicate of a method that uses randomness (random search, halving random search,
      Sobol, Latin hypercube, Nelder–Mead's start, and BO's first 5 colors) gets a
      **different random starting point**.
    - Replicate *i* uses the same seed for every optimization in the list, so, e.g., all BO
      variants in replicate 3 start from the same 5 random colors (a fair, paired comparison).
    - Grid search and halving grid search have no randomness: their replicates differ
      only by sensor noise.
    - On the simulator, the 0.15 s pause per experiment is skipped here. Bayesian optimization
      still takes a few seconds per run (Thompson sampling longer), so start with a short list.

    Overlapping bands mean the difference between two optimizers could easily be luck.
    """)
    return


@app.cell(hide_code=True)
def _(ACQUISITIONS, METHODS, mo):
    method9 = mo.ui.dropdown(
        options=METHODS,
        value="Bayesian optimization", label="Optimizer",
    )
    acq9 = mo.ui.dropdown(options=ACQUISITIONS, value="Expected improvement (EI)", label="Acquisition")
    beta9 = mo.ui.slider(0, 6, step=0.5, value=2, label="\u03b2", show_value=True)
    reps9 = mo.ui.slider(2, 20, value=5, label="Replicates", show_value=True)
    n_iter9 = mo.ui.slider(5, 100, value=25, label="Experiments per run", show_value=True)
    run_all = mo.ui.run_button(label="Run all", kind="success")
    return acq9, beta9, method9, n_iter9, reps9, run_all


@app.cell(hide_code=True)
def _(mo):
    get_queue, set_queue = mo.state([])  # the list of optimizations to run
    return get_queue, set_queue


@app.cell(hide_code=True)
def _(acq9, beta9, method9, mo, queue_entry, set_queue):
    def _add(entries):  # append, replacing any entry with the same label
        labels = {e["label"] for e in entries}
        set_queue(lambda q: [e for e in q if e["label"] not in labels] + entries)


    _current = queue_entry(method9.value, acq9.value, beta9.value)
    add_button = mo.ui.button(label=f"Add {_current['label']}", on_click=lambda _: _add([_current]))
    preset_button = mo.ui.button(
        label="Add all five methods (BO with EI)",
        on_click=lambda _: _add([queue_entry(m) for m in
                                 ["Random search", "Grid search", "Sobol sampling",
                                  "Latin hypercube", "Bayesian optimization"]]),
    )
    clear_queue_button = mo.ui.button(label="Clear list", on_click=lambda _: set_queue([]))
    return add_button, clear_queue_button, preset_button


@app.cell(hide_code=True)
def _(get_queue, mo):
    queue_table = mo.ui.table(
        [{"Optimization": e["label"]} for e in get_queue()],
        selection="multi", show_column_summaries=False, label="Optimizations to run",
    )
    return (queue_table,)


@app.cell(hide_code=True)
def _(mo, queue_table, set_queue):
    remove_button = mo.ui.button(
        label="Remove selected",
        on_click=lambda _: set_queue(
            lambda q: [e for e in q
                       if e["label"] not in {row["Optimization"] for row in queue_table.value}]
        ),
    )
    return (remove_button,)


@app.cell(hide_code=True)
def _(
    acq9,
    add_button,
    beta9,
    clear_queue_button,
    get_queue,
    method9,
    mo,
    n_iter9,
    preset_button,
    queue_table,
    remove_button,
    reps9,
    run_all,
):
    _settings = [method9]
    if method9.value == "Bayesian optimization":
        _settings.append(acq9)
        if acq9.value == "LCB":
            _settings.append(beta9)
    _n = len(get_queue())
    mo.vstack([
        mo.md("**1. Build the list**"),
        mo.hstack([*_settings, add_button], justify="start", gap=2),
        mo.hstack([preset_button, remove_button, clear_queue_button], justify="start", gap=1),
        queue_table if _n else mo.md("*The list is empty: add optimizations above.*"),
        mo.md("**2. Run**"),
        mo.hstack([reps9, n_iter9, run_all], justify="start", gap=2),
        mo.md(f"{_n} optimization(s) \u00d7 {reps9.value} replicates \u00d7 {n_iter9.value} experiments "
              f"= **{_n * reps9.value * n_iter9.value} experiments** in total."),
    ])
    return


@app.cell(hide_code=True)
def _(lab, mo, target_rgb):
    # Replicate results, kept per target color and device (like the runs in section 6).
    _ = (target_rgb, lab)
    get_batch, set_batch = mo.state({})
    return get_batch, set_batch


@app.cell(hide_code=True)
def _(
    FakeLab,
    get_queue,
    lab,
    mo,
    n_iter9,
    np,
    reps9,
    run_all,
    run_optimization,
    set_batch,
    target_readings,
    time,
):
    mo.stop(not run_all.value, mo.md("Build a list, then press **Run all**."))
    _queue = get_queue()
    mo.stop(not _queue, mo.md("The list is empty: add at least one optimization."))

    # The simulator's pause only exists to make the live plot watchable; skip it here.
    _measure = FakeLab(delay=0).measure if isinstance(lab, FakeLab) else lab.measure

    # One seed per replicate, shared by every optimization in the list (paired comparison).
    _seed = int(np.random.SeedSequence().entropy % 2**32)
    _rep_seeds = np.random.SeedSequence(_seed).spawn(reps9.value)

    _done = {}
    _t0 = time.time()
    try:
        with mo.status.progress_bar(
            total=len(_queue) * reps9.value, title="Running replicates", remove_on_exit=True
        ) as _bar:
            for _e in _queue:
                _Y, _Xs = [], []
                for _r, _ss in enumerate(_rep_seeds):
                    _rng = np.random.default_rng(_ss)  # replicate r: its own random start
                    _X, _y = run_optimization(
                        _e["method"], n_iter9.value, _measure, target_readings, _rng,
                        acq=_e["acq"] or "EI", beta=_e["beta"] or 2.0,
                    )
                    _Xs.append(_X)
                    _Y.append(_y)
                    _bar.update(subtitle=f"{_e['label']}: replicate {_r + 1}/{reps9.value}")
                _done[_e["label"]] = {**_e, "X": _Xs, "Y": _Y, "seed": _seed}
    finally:
        if _done:  # keep every optimization that finished all its replicates
            set_batch(lambda b: {**{k: v for k, v in b.items() if k not in _done}, **_done})

    mo.md(
        f"Finished {len(_done)} optimization(s) \u00d7 {reps9.value} replicates in "
        f"{time.time() - _t0:.0f} s (seed {_seed})."
    )
    return


@app.cell(hide_code=True)
def _(mo, set_batch):
    clear_batch_button = mo.ui.button(
        label="Clear replicate results", kind="danger", on_click=lambda _: set_batch({})
    )
    return (clear_batch_button,)


@app.cell(hide_code=True)
def _(clear_batch_button, get_batch, mo, replicate_figure, replicate_table):
    _batch = get_batch()
    mo.stop(not _batch, mo.md("No replicate results yet."))
    mo.vstack([clear_batch_button, replicate_figure(_batch), replicate_table(_batch)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 10. Benchmark surfaces

    Real experiments are slow, so optimization methods are usually compared on **test
    functions** whose best value is known. Each subsection below is one classic surface:
    what it looks like, what it tests, and a **Run** button. Build the optimizer list once,
    here (same controls as section 9), then run it on any surface.

    - **Same optimizers, no changes:** every surface is rescaled to the unit box $[0,1]^d$,
      the same box the optimizers search for the LED. An optimizer never knows what it is
      optimizing, only the error it gets back.
    - **Error = gap to the best:** each surface reports $f(x)-f^*$, so 0 means the global
      minimum was found. Plots use a log scale, like sections 6 and 9.
    - **Choose the dimension** where the surface allows it. Watch grid search fall apart as
      $d$ grows: a 3-level grid in 10 dimensions has 59,049 points.
    - **Noise-free:** repeated measurements give the same value, so successive halving's
      repeats are wasted budget here.
    - **A known trap:** many surfaces have their minimum exactly at the center of the box.
      Grid search with an odd number of levels lands right on it, which flatters it. Tick
      **Random shift** to move the optimum to a random spot in the middle 80% of the box in
      every replicate (the same spot for every optimizer in that replicate), as the BBOB/COCO
      benchmark suite does. Schwefel, Michalewicz and Eggholder already have off-center optima
      and are never shifted. Shifted and unshifted results are kept separately.
    - **Heatmaps** (always unshifted): color shows $\log_{10}(f-f^*)$ in equal-area bands, so
      each color covers the same share of the plot; bright = close to the best, red stars =
      global minima. For $d>2$ the heatmap is a 2-D slice through the minimum.
    """)
    return


@app.cell(hide_code=True)
def _(ACQUISITIONS, METHODS, mo):
    method10 = mo.ui.dropdown(options=METHODS, value="Bayesian optimization", label="Optimizer")
    acq10 = mo.ui.dropdown(options=ACQUISITIONS, value="Expected improvement (EI)", label="Acquisition")
    beta10 = mo.ui.slider(0, 6, step=0.5, value=2, label="β", show_value=True)
    reps10 = mo.ui.slider(2, 20, value=5, label="Replicates", show_value=True)
    n_iter10 = mo.ui.slider(5, 100, value=30, label="Experiments per run", show_value=True)
    shift10 = mo.ui.checkbox(value=False, label="Random shift (move the optimum in each replicate)")
    return acq10, beta10, method10, n_iter10, reps10, shift10


@app.cell(hide_code=True)
def _(mo):
    get_queue10, set_queue10 = mo.state([])  # the optimizer list for all benchmark surfaces
    return get_queue10, set_queue10


@app.cell(hide_code=True)
def _(METHODS, acq10, beta10, method10, mo, queue_entry, set_queue10):
    def _add10(entries):  # append, replacing any entry with the same label
        labels = {e["label"] for e in entries}
        set_queue10(lambda q: [e for e in q if e["label"] not in labels] + entries)


    _current10 = queue_entry(method10.value, acq10.value, beta10.value)
    add10 = mo.ui.button(label=f"Add {_current10['label']}", on_click=lambda _: _add10([_current10]))
    preset10 = mo.ui.button(
        label="Add all eight methods (BO with EI)",
        on_click=lambda _: _add10([queue_entry(m) for m in METHODS]),
    )
    clear_queue10 = mo.ui.button(label="Clear list", on_click=lambda _: set_queue10([]))
    return add10, clear_queue10, preset10


@app.cell(hide_code=True)
def _(get_queue10, mo):
    queue_table10 = mo.ui.table(
        [{"Optimization": e["label"]} for e in get_queue10()],
        selection="multi", show_column_summaries=False, label="Optimizations to run",
    )
    return (queue_table10,)


@app.cell(hide_code=True)
def _(mo, queue_table10, set_queue10):
    remove10 = mo.ui.button(
        label="Remove selected",
        on_click=lambda _: set_queue10(
            lambda q: [e for e in q
                       if e["label"] not in {row["Optimization"] for row in queue_table10.value}]
        ),
    )
    return (remove10,)


@app.cell(hide_code=True)
def _():
    # Replicate results for every (surface, dimension); filled by the Run buttons below.
    surface_results = {}
    return (surface_results,)


@app.cell(hide_code=True)
def _(mo, surface_results):
    clear10 = mo.ui.button(
        value=0, label="Clear all surface results", kind="danger",
        on_click=lambda v: (surface_results.clear(), (v or 0) + 1)[1],
    )
    return (clear10,)


@app.cell(hide_code=True)
def _(
    acq10,
    add10,
    beta10,
    clear10,
    clear_queue10,
    get_queue10,
    method10,
    mo,
    n_iter10,
    preset10,
    queue_table10,
    remove10,
    reps10,
    shift10,
):
    _settings = [method10]
    if method10.value == "Bayesian optimization":
        _settings.append(acq10)
        if acq10.value == "LCB":
            _settings.append(beta10)
    _n = len(get_queue10())
    mo.vstack([
        mo.md("**Optimizer list for all surfaces**"),
        mo.hstack([*_settings, add10], justify="start", gap=2),
        mo.hstack([preset10, remove10, clear_queue10], justify="start", gap=1),
        queue_table10 if _n else mo.md("*The list is empty: add optimizations above.*"),
        mo.hstack([reps10, n_iter10, shift10, clear10], justify="start", gap=2),
        mo.md(f"Each **Run** below: {_n} optimization(s) × {reps10.value} replicates × "
              f"{n_iter10.value} experiments = **{_n * reps10.value * n_iter10.value} evaluations**."),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Classic surfaces (choose the dimension)
    """)
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    sphere_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    sphere_run = mo.ui.run_button(label="Run the list on Sphere", kind="success")
    surface_header(1, SURFACES["sphere"], [sphere_d, sphere_run])
    return sphere_d, sphere_run


@app.cell(hide_code=True)
def _(SURFACES, sphere_d, surface_heatmap):
    surface_heatmap(SURFACES["sphere"], sphere_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    sphere_d,
    sphere_run,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["sphere"], sphere_d.value, get_queue10(), reps10.value, n_iter10.value,
        sphere_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    rosenbrock_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    rosenbrock_run = mo.ui.run_button(label="Run the list on Rosenbrock", kind="success")
    surface_header(2, SURFACES["rosenbrock"], [rosenbrock_d, rosenbrock_run])
    return rosenbrock_d, rosenbrock_run


@app.cell(hide_code=True)
def _(SURFACES, rosenbrock_d, surface_heatmap):
    surface_heatmap(SURFACES["rosenbrock"], rosenbrock_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    rosenbrock_d,
    rosenbrock_run,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["rosenbrock"], rosenbrock_d.value, get_queue10(), reps10.value, n_iter10.value,
        rosenbrock_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    rastrigin_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    rastrigin_run = mo.ui.run_button(label="Run the list on Rastrigin", kind="success")
    surface_header(3, SURFACES["rastrigin"], [rastrigin_d, rastrigin_run])
    return rastrigin_d, rastrigin_run


@app.cell(hide_code=True)
def _(SURFACES, rastrigin_d, surface_heatmap):
    surface_heatmap(SURFACES["rastrigin"], rastrigin_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    n_iter10,
    rastrigin_d,
    rastrigin_run,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["rastrigin"], rastrigin_d.value, get_queue10(), reps10.value, n_iter10.value,
        rastrigin_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    ackley_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    ackley_run = mo.ui.run_button(label="Run the list on Ackley", kind="success")
    surface_header(4, SURFACES["ackley"], [ackley_d, ackley_run])
    return ackley_d, ackley_run


@app.cell(hide_code=True)
def _(SURFACES, ackley_d, surface_heatmap):
    surface_heatmap(SURFACES["ackley"], ackley_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    ackley_d,
    ackley_run,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["ackley"], ackley_d.value, get_queue10(), reps10.value, n_iter10.value,
        ackley_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    griewank_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    griewank_run = mo.ui.run_button(label="Run the list on Griewank", kind="success")
    surface_header(5, SURFACES["griewank"], [griewank_d, griewank_run])
    return griewank_d, griewank_run


@app.cell(hide_code=True)
def _(SURFACES, griewank_d, surface_heatmap):
    surface_heatmap(SURFACES["griewank"], griewank_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    griewank_d,
    griewank_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["griewank"], griewank_d.value, get_queue10(), reps10.value, n_iter10.value,
        griewank_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    schwefel_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    schwefel_run = mo.ui.run_button(label="Run the list on Schwefel", kind="success")
    surface_header(6, SURFACES["schwefel"], [schwefel_d, schwefel_run])
    return schwefel_d, schwefel_run


@app.cell(hide_code=True)
def _(SURFACES, schwefel_d, surface_heatmap):
    surface_heatmap(SURFACES["schwefel"], schwefel_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    schwefel_d,
    schwefel_run,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["schwefel"], schwefel_d.value, get_queue10(), reps10.value, n_iter10.value,
        schwefel_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    levy_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    levy_run = mo.ui.run_button(label="Run the list on Levy", kind="success")
    surface_header(7, SURFACES["levy"], [levy_d, levy_run])
    return levy_d, levy_run


@app.cell(hide_code=True)
def _(SURFACES, levy_d, surface_heatmap):
    surface_heatmap(SURFACES["levy"], levy_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    levy_d,
    levy_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["levy"], levy_d.value, get_queue10(), reps10.value, n_iter10.value,
        levy_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    styblinski_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    styblinski_run = mo.ui.run_button(label="Run the list on Styblinski–Tang", kind="success")
    surface_header(8, SURFACES["styblinski"], [styblinski_d, styblinski_run])
    return styblinski_d, styblinski_run


@app.cell(hide_code=True)
def _(SURFACES, styblinski_d, surface_heatmap):
    surface_heatmap(SURFACES["styblinski"], styblinski_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    styblinski_d,
    styblinski_run,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["styblinski"], styblinski_d.value, get_queue10(), reps10.value, n_iter10.value,
        styblinski_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    michalewicz_d = mo.ui.slider(2, 10, value=2, label="Dimensions d", show_value=True)
    michalewicz_run = mo.ui.run_button(label="Run the list on Michalewicz", kind="success")
    surface_header(9, SURFACES["michalewicz"], [michalewicz_d, michalewicz_run])
    return michalewicz_d, michalewicz_run


@app.cell(hide_code=True)
def _(SURFACES, michalewicz_d, surface_heatmap):
    surface_heatmap(SURFACES["michalewicz"], michalewicz_d.value)
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    michalewicz_d,
    michalewicz_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["michalewicz"], michalewicz_d.value, get_queue10(), reps10.value, n_iter10.value,
        michalewicz_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Fixed-dimension surfaces
    """)
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    branin_run = mo.ui.run_button(label="Run the list on Branin", kind="success")
    surface_header(10, SURFACES["branin"], [branin_run])
    return (branin_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["branin"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    branin_run,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["branin"], None, get_queue10(), reps10.value, n_iter10.value,
        branin_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    camel_run = mo.ui.run_button(label="Run the list on Six-hump camel", kind="success")
    surface_header(11, SURFACES["camel"], [camel_run])
    return (camel_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["camel"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    camel_run,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["camel"], None, get_queue10(), reps10.value, n_iter10.value,
        camel_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    himmelblau_run = mo.ui.run_button(label="Run the list on Himmelblau", kind="success")
    surface_header(12, SURFACES["himmelblau"], [himmelblau_run])
    return (himmelblau_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["himmelblau"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    himmelblau_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["himmelblau"], None, get_queue10(), reps10.value, n_iter10.value,
        himmelblau_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    goldstein_run = mo.ui.run_button(label="Run the list on Goldstein–Price", kind="success")
    surface_header(13, SURFACES["goldstein"], [goldstein_run])
    return (goldstein_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["goldstein"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    goldstein_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["goldstein"], None, get_queue10(), reps10.value, n_iter10.value,
        goldstein_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    beale_run = mo.ui.run_button(label="Run the list on Beale", kind="success")
    surface_header(14, SURFACES["beale"], [beale_run])
    return (beale_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["beale"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    beale_run,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["beale"], None, get_queue10(), reps10.value, n_iter10.value,
        beale_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    booth_run = mo.ui.run_button(label="Run the list on Booth", kind="success")
    surface_header(15, SURFACES["booth"], [booth_run])
    return (booth_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["booth"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    booth_run,
    clear10,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["booth"], None, get_queue10(), reps10.value, n_iter10.value,
        booth_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    easom_run = mo.ui.run_button(label="Run the list on Easom", kind="success")
    surface_header(16, SURFACES["easom"], [easom_run])
    return (easom_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["easom"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    easom_run,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["easom"], None, get_queue10(), reps10.value, n_iter10.value,
        easom_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    eggholder_run = mo.ui.run_button(label="Run the list on Eggholder", kind="success")
    surface_header(17, SURFACES["eggholder"], [eggholder_run])
    return (eggholder_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["eggholder"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    eggholder_run,
    get_queue10,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["eggholder"], None, get_queue10(), reps10.value, n_iter10.value,
        eggholder_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    hartmann3_run = mo.ui.run_button(label="Run the list on Hartmann-3", kind="success")
    surface_header(18, SURFACES["hartmann3"], [hartmann3_run])
    return (hartmann3_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["hartmann3"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    hartmann3_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["hartmann3"], None, get_queue10(), reps10.value, n_iter10.value,
        hartmann3_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(SURFACES, mo, surface_header):
    hartmann6_run = mo.ui.run_button(label="Run the list on Hartmann-6", kind="success")
    surface_header(19, SURFACES["hartmann6"], [hartmann6_run])
    return (hartmann6_run,)


@app.cell(hide_code=True)
def _(SURFACES, surface_heatmap):
    surface_heatmap(SURFACES["hartmann6"])
    return


@app.cell(hide_code=True)
def _(
    SURFACES,
    clear10,
    get_queue10,
    hartmann6_run,
    n_iter10,
    reps10,
    shift10,
    surface_results,
    surface_run,
):
    surface_run(
        SURFACES["hartmann6"], None, get_queue10(), reps10.value, n_iter10.value,
        hartmann6_run.value, surface_results, refresh=clear10.value, shift=shift10.value,
    )
    return


@app.cell(hide_code=True)
def _(
    CHANNELS,
    expected_improvement,
    lower_confidence_bound,
    mo,
    normalize,
    np,
    plt,
    probability_of_improvement,
):
    # ---------------- Plot helpers ----------------
    WAVELENGTHS = [int(c[2:]) for c in CHANNELS]
    CHANNEL_COLORS = ["#7b2fbe", "#3b3bff", "#0f8bff", "#00b84a", "#9ccc00", "#ffb300", "#ff6d00", "#d50000"]
    METHOD_COLORS = {
        "Random search": "#8a8a8a",
        "Grid search": "#e08a00",
        "Sobol sampling": "#2a9d8f",
        "Latin hypercube": "#b5179e",
        "Halving random search": "#4d4d4d",
        "Halving grid search": "#8a4b00",
        "Nelder-Mead": "#d62728",
        "Bayesian optimization": "#1f5fd6",
    }


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


    BO_COLORS = {"BO: EI": "#1f5fd6", "BO: PI": "#6a3d9a", "BO: Thompson": "#8c564b"}


    def run_color(name):
        """One fixed color per optimization, the same in every plot (LCB: darker green = larger beta)."""
        if name in METHOD_COLORS:
            return METHOD_COLORS[name]
        if name in BO_COLORS:
            return BO_COLORS[name]
        if name.startswith("BO: LCB"):
            beta = float(name.split("=")[-1])
            return plt.cm.Greens(0.4 + 0.55 * min(beta, 6) / 6)
        return "#444444"


    def comparison_figure(runs):
        fig, ax = plt.subplots(figsize=(8.5, 3.6))
        for name, r in runs.items():
            it = np.arange(1, len(r["y"]) + 1)
            ax.plot(it, np.minimum.accumulate(r["y"]), lw=2, label=name, color=run_color(name))
        ax.set_yscale("log")
        ax.set_xlabel("Experiment")
        ax.set_ylabel("Best error so far (log scale)")
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))
        fig.tight_layout()
        plt.close(fig)
        return fig


    def best_so_far(Y):
        """replicates x experiments errors -> running minimum along each replicate."""
        return np.minimum.accumulate(np.asarray(Y, dtype=float), axis=1)


    def replicate_figure(batch, ylabel="Best error so far (log scale)\nmean ± 1 SD over replicates"):
        """Mean best-so-far across replicates (line) +/- one standard deviation (band)."""
        fig, ax = plt.subplots(figsize=(8, 4))
        floor = min(best_so_far(r["Y"]).min() for r in batch.values()) * 0.5
        for name, r in batch.items():
            best = best_so_far(r["Y"])
            mean = best.mean(axis=0)
            sd = best.std(axis=0, ddof=1) if len(best) > 1 else np.zeros_like(mean)
            it = np.arange(1, best.shape[1] + 1)
            color = run_color(name)
            ax.plot(it, mean, lw=2, color=color, label=f"{name} (n={len(best)})")
            # on a log axis mean - sd can go below zero; clip the band at a small positive value
            ax.fill_between(it, np.maximum(mean - sd, floor), mean + sd, color=color, alpha=0.15, lw=0)
        ax.set_yscale("log")
        ax.set_xlabel("Experiment")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))
        fig.tight_layout()
        plt.close(fig)
        return fig


    def replicate_table(batch):
        """Summary table: final best error per optimization, across replicates."""
        rows = []
        for name, r in batch.items():
            final = best_so_far(r["Y"])[:, -1]  # best error at the end of each replicate
            sd = final.std(ddof=1) if len(final) > 1 else 0.0
            rows.append(
                f"| {name} | {len(final)} | {len(r['Y'][0])} | "
                f"{final.mean():.3g} ± {sd:.3g} | {final.min():.3g} | {final.max():.3g} |"
            )
        return mo.md(
            "| Optimization | Replicates | Experiments | Final best, mean ± SD | Best replicate | Worst replicate |\n"
            "|---|---|---|---|---|---|\n" + "\n".join(rows)
        )


    def gp_slices_figure(X, y, gp, x_next, x_actual=None, acq="EI", beta=2.0, rng=None):
        """1-D slices of the GP and EI through x_next, one column per LED channel.

        The color space is 3-D, so each panel varies one channel 0..255 while the
        other two stay at x_next. Dots are past experiments, faded by how far they
        are from the slice in the other two channels. The bottom row shows the
        acquisition function `acq` the run used.
        """
        rng = np.random.default_rng() if rng is None else rng
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        x_next = np.asarray(x_next, dtype=float)
        best_log = np.log(y.min())
        grid = np.arange(256)
        names = ["Red", "Green", "Blue"]
        line_colors = ["#d62728", "#2ca02c", "#1f5fd6"]

        fig, axes = plt.subplots(2, 3, figsize=(12, 5.6), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]})
        for j in range(3):
            pts = np.tile(x_next, (len(grid), 1))
            pts[:, j] = grid
            mu, sd = gp.predict(pts / 255, return_std=True)
            others = [k for k in range(3) if k != j]

            ax = axes[0, j]
            ax.fill_between(grid, np.exp(mu - 2 * sd), np.exp(mu + 2 * sd),
                            color=line_colors[j], alpha=0.18, lw=0, label="uncertainty (±2σ)")
            ax.plot(grid, np.exp(mu), color=line_colors[j], lw=2, label="GP prediction")
            ax.axhline(y.min(), color="0.4", ls=":", lw=1, label="best so far")
            dist = np.linalg.norm((X[:, others] - x_next[others]) / 255, axis=1)
            alpha = np.clip(1 - dist / 0.4, 0.15, 1)
            face = np.column_stack([X / 255, alpha])
            edge = np.column_stack([np.full((len(X), 3), 0.25), alpha])
            ax.scatter(X[:, j], y, s=30, c=face, edgecolors=edge, linewidths=0.7,
                       zorder=3, label="experiments")
            ax.set_yscale("log")
            ax.set_title(f"vary {names[j]}  ({names[others[0]][0]}={int(x_next[others[0]])}, "
                         f"{names[others[1]][0]}={int(x_next[others[1]])} fixed)", fontsize=9)
            if j == 0:
                ax.set_ylabel("Error (log scale)")
                ax.legend(fontsize=7, loc="lower left")

            ax = axes[1, j]
            if acq in ("EI", "PI"):  # higher is better
                if acq == "EI":
                    score, _, _ = expected_improvement(mu, sd, best_log)
                    ylabel = "Expected\nimprovement"
                else:
                    score = probability_of_improvement(mu, sd, best_log)
                    ylabel = "Probability of\nimprovement"
                ax.fill_between(grid, score, color="#7a4cc2", alpha=0.35, lw=0)
                ax.plot(grid, score, color="#7a4cc2", lw=1.5)
                ax.set_ylim(bottom=0)
            else:  # lower is better, shown in error units like the top row
                if acq == "LCB":
                    curve = np.exp(lower_confidence_bound(mu, sd, beta))
                    ylabel = f"LCB = \u03bc \u2212 {beta:g}\u03c3\n(lower is better)"
                else:
                    seed = int(rng.integers(2**31))
                    curve = np.exp(gp.sample_y(pts / 255, random_state=seed).ravel())
                    ylabel = "Thompson sample\n(lower is better)"
                ax.plot(grid, curve, color="#7a4cc2", lw=1.5)
                ax.axhline(y.min(), color="0.4", ls=":", lw=1)
                ax.set_yscale("log")
            ax.set_xlabel(f"{names[j]} (0-255)")
            if j == 0:
                ax.set_ylabel(ylabel, fontsize=9)

            for row in (0, 1):
                axes[row, j].axvline(x_next[j], color="black", lw=1.5,
                                     label="next pick" if (row, j) == (1, 0) else None)
                if x_actual is not None and tuple(x_actual) != tuple(int(v) for v in x_next):
                    axes[row, j].axvline(x_actual[j], color="black", ls="--", lw=1,
                                         label="color the run used" if (row, j) == (1, 0) else None)
            axes[0, j].set_xlim(0, 255)
        axes[1, 0].legend(fontsize=7, loc="upper left")

        fig.suptitle(f"What the GP believes after {len(y)} experiments "
                     f"(best error {y.min():.4f}); next pick RGB = {tuple(int(v) for v in x_next)}")
        fig.tight_layout()
        plt.close(fig)
        return fig


    return (
        comparison_figure,
        gp_slices_figure,
        live_figure,
        replicate_figure,
        replicate_table,
        spectrum_plot,
    )


@app.cell(hide_code=True)
def _(np):
    # ---------------- 3-D plot helpers (section 8) ----------------
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots


    def cube_figure(cube, top_pct=100, opacity=0.35):
        """Three rotatable 3-D scatter plots of the color cube: GP mean, GP uncertainty, acquisition.

        Each panel colors the grid so that bright = interesting, and keeps only its
        top_pct % most interesting points so the inside of the cube becomes visible.
        """
        panels = [
            ("Predicted error", cube["mean"], "log\u2081\u2080 error", False),  # low error is interesting
            ("Uncertainty", cube["sigma"], "\u03c3 (log error)", True),  # high uncertainty is interesting
            (cube["acq_name"], cube["acq"], cube["acq_label"], cube["acq_higher"]),
        ]
        fig = make_subplots(
            rows=1, cols=3, specs=[[{"type": "scene"}] * 3],
            subplot_titles=[p[0] for p in panels], horizontal_spacing=0.01,
        )
        X = np.asarray(cube["X"], dtype=float)
        nxt = cube["next"]
        led = [f"rgb({int(r)},{int(g)},{int(b)})" for r, g, b in X]

        for i, (title, val, cbar, higher) in enumerate(panels):
            interest = val if higher else -val
            keep = interest >= np.percentile(interest, 100 - top_pct)
            p = cube["pts"][keep]
            fig.add_trace(go.Scatter3d(
                x=p[:, 0], y=p[:, 1], z=p[:, 2], mode="markers", showlegend=False,
                marker=dict(
                    size=4, color=val[keep], colorscale="Viridis", reversescale=not higher,
                    cmin=float(val.min()), cmax=float(val.max()), opacity=opacity,
                    colorbar=dict(title=dict(text=cbar, side="top"), orientation="h",
                                  x=(i + 0.5) / 3, xanchor="center", y=-0.02, yanchor="top",
                                  len=0.27, thickness=12),
                ),
                hovertemplate="RGB (%{x:.0f}, %{y:.0f}, %{z:.0f})<br>" + cbar
                              + ": %{marker.color:.3g}<extra></extra>",
            ), row=1, col=i + 1)
            fig.add_trace(go.Scatter3d(
                x=X[:, 0], y=X[:, 1], z=X[:, 2], mode="markers", name="experiments",
                legendgroup="exp", showlegend=(i == 0),
                marker=dict(size=5, color=led, line=dict(color="black", width=1.5)),
                hovertemplate="experiment RGB (%{x:.0f}, %{y:.0f}, %{z:.0f})<extra></extra>",
            ), row=1, col=i + 1)
            fig.add_trace(go.Scatter3d(
                x=[nxt[0]], y=[nxt[1]], z=[nxt[2]], mode="markers", name="next pick",
                legendgroup="next", showlegend=(i == 0),
                marker=dict(size=8, symbol="x", color="red"),
                hovertemplate="next pick RGB (%{x:.0f}, %{y:.0f}, %{z:.0f})<extra></extra>",
            ), row=1, col=i + 1)

        axis = dict(range=[0, 255], tickvals=[0, 128, 255])
        scene = dict(
            xaxis=dict(title="R", **axis), yaxis=dict(title="G", **axis), zaxis=dict(title="B", **axis),
            aspectmode="cube", camera=dict(eye=dict(x=1.6, y=1.6, z=1.1)),
        )
        fig.update_layout(
            scene=scene, scene2=scene, scene3=scene, height=520,
            margin=dict(l=0, r=0, t=40, b=70),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=1.08),
        )
        return fig

    return (cube_figure,)


@app.cell(hide_code=True)
def _(np):
    # ---------------- Benchmark surfaces (section 10) ----------------
    from scipy.optimize import minimize, minimize_scalar


    class Surface:
        """A benchmark function to minimize on a box. Optimizers see it through the unit cube.

        f: vectorized function of x with shape (..., d), in the surface's own coordinates.
        bounds: (lo, hi) for every dimension, or a list with one (lo, hi) per dimension.
        dims: an int (fixed dimension) or (smallest, largest) when the user may choose.
        argmins: function d -> list of known global minimizers (polished numerically).
        zoom: optional half-width of a zoomed-in heatmap around the first minimizer.
        shiftable: False if moving the function would expose values below f* from outside
            the box (only for surfaces whose optimum is already off-center).
        """

        def __init__(self, key, name, f, bounds, dims, argmins, blurb, zoom=None, shiftable=True):
            self.key, self.name, self.f, self.bounds = key, name, f, bounds
            self.dims, self.argmins, self.blurb, self.zoom = dims, argmins, blurb, zoom
            self.shiftable = shiftable
            self._best = {}  # d -> (f*, minimizers)

        @property
        def fixed(self):
            return isinstance(self.dims, int)

        def dim(self, d=None):
            return self.dims if self.fixed else int(d)

        def box(self, d):
            b = self.bounds if isinstance(self.bounds[0], (list, tuple)) else [self.bounds] * d
            b = np.array(b, dtype=float)
            return b[:, 0], b[:, 1]

        def _solve(self, d):
            if d not in self._best:
                lo, hi = self.box(d)
                pts = []
                for x0 in self.argmins(d):
                    x0 = np.asarray(x0, dtype=float)
                    res = minimize(lambda x: float(self.f(x)), x0, method="L-BFGS-B",
                                   bounds=list(zip(lo, hi)), options=dict(ftol=1e-15, gtol=1e-12))
                    pts.append(res.x if res.fun < float(self.f(x0)) else x0)
                self._best[d] = (min(float(self.f(p)) for p in pts), pts)
            return self._best[d]

        def f_min(self, d):
            """Global minimum value f* (known minimizers, polished to ~1e-12)."""
            return self._solve(d)[0]

        def minimizers(self, d):
            return self._solve(d)[1]

        def to_x(self, u, d):
            lo, hi = self.box(d)
            return lo + np.asarray(u, dtype=float) * (hi - lo)

        def random_shift(self, d, rng):
            """Offset that moves the first global minimizer to a random spot in the middle 80%
            of the box (like the BBOB benchmark suite). The function becomes f(x - shift)."""
            return self.to_x(rng.uniform(0.1, 0.9, d), d) - self.minimizers(d)[0]

        def error(self, u, d, shift=None):
            """What the optimizers minimize: the gap to the global minimum, f(x) - f* (> 0)."""
            x = self.to_x(u, d)
            if shift is not None:
                x = x - shift
            return float(max(self.f(x) - self.f_min(d), 1e-12))


    # --- the functions; x has shape (..., d) ---

    def _sphere(x):
        return np.sum(x**2, axis=-1)


    def _rosenbrock(x):
        return np.sum(100 * (x[..., 1:] - x[..., :-1] ** 2) ** 2 + (1 - x[..., :-1]) ** 2, axis=-1)


    def _rastrigin(x):
        return 10 * x.shape[-1] + np.sum(x**2 - 10 * np.cos(2 * np.pi * x), axis=-1)


    def _ackley(x):
        return (-20 * np.exp(-0.2 * np.sqrt(np.mean(x**2, axis=-1)))
                - np.exp(np.mean(np.cos(2 * np.pi * x), axis=-1)) + 20 + np.e)


    def _griewank(x):
        i = np.arange(1, x.shape[-1] + 1)
        return np.sum(x**2, axis=-1) / 4000 - np.prod(np.cos(x / np.sqrt(i)), axis=-1) + 1


    def _schwefel(x):
        return 418.9829 * x.shape[-1] - np.sum(x * np.sin(np.sqrt(np.abs(x))), axis=-1)


    def _levy(x):
        w = 1 + (x - 1) / 4
        wi, wd = w[..., :-1], w[..., -1]
        return (np.sin(np.pi * w[..., 0]) ** 2
                + np.sum((wi - 1) ** 2 * (1 + 10 * np.sin(np.pi * wi + 1) ** 2), axis=-1)
                + (wd - 1) ** 2 * (1 + np.sin(2 * np.pi * wd) ** 2))


    def _styblinski_tang(x):
        return 0.5 * np.sum(x**4 - 16 * x**2 + 5 * x, axis=-1)


    def _michalewicz(x, m=10):
        i = np.arange(1, x.shape[-1] + 1)
        return -np.sum(np.sin(x) * np.sin(i * x**2 / np.pi) ** (2 * m), axis=-1)


    def _michalewicz_argmin(d, m=10):
        """Michalewicz is a sum of 1-D terms, so its minimizer is found one coordinate at a time."""
        xs = np.linspace(0, np.pi, 200001)
        out = []
        for i in range(1, d + 1):
            def g(x, i=i):
                return -np.sin(x) * np.sin(i * x**2 / np.pi) ** (2 * m)
            j = int(np.argmin(g(xs)))
            a, b = xs[max(j - 1, 0)], xs[min(j + 1, len(xs) - 1)]
            out.append(minimize_scalar(g, bounds=(a, b), method="bounded", options=dict(xatol=1e-12)).x)
        return [np.array(out)]


    def _branin(x):
        x1, x2 = x[..., 0], x[..., 1]
        b, c, t = 5.1 / (4 * np.pi**2), 5 / np.pi, 1 / (8 * np.pi)
        return (x2 - b * x1**2 + c * x1 - 6) ** 2 + 10 * (1 - t) * np.cos(x1) + 10


    def _six_hump_camel(x):
        x1, x2 = x[..., 0], x[..., 1]
        return (4 - 2.1 * x1**2 + x1**4 / 3) * x1**2 + x1 * x2 + (-4 + 4 * x2**2) * x2**2


    def _himmelblau(x):
        x1, x2 = x[..., 0], x[..., 1]
        return (x1**2 + x2 - 11) ** 2 + (x1 + x2**2 - 7) ** 2


    def _goldstein_price(x):
        x1, x2 = x[..., 0], x[..., 1]
        a = 1 + (x1 + x2 + 1) ** 2 * (19 - 14 * x1 + 3 * x1**2 - 14 * x2 + 6 * x1 * x2 + 3 * x2**2)
        b = 30 + (2 * x1 - 3 * x2) ** 2 * (18 - 32 * x1 + 12 * x1**2 + 48 * x2 - 36 * x1 * x2 + 27 * x2**2)
        return a * b


    def _beale(x):
        x1, x2 = x[..., 0], x[..., 1]
        return ((1.5 - x1 + x1 * x2) ** 2 + (2.25 - x1 + x1 * x2**2) ** 2
                + (2.625 - x1 + x1 * x2**3) ** 2)


    def _booth(x):
        x1, x2 = x[..., 0], x[..., 1]
        return (x1 + 2 * x2 - 7) ** 2 + (2 * x1 + x2 - 5) ** 2


    def _easom(x):
        x1, x2 = x[..., 0], x[..., 1]
        return -np.cos(x1) * np.cos(x2) * np.exp(-((x1 - np.pi) ** 2) - (x2 - np.pi) ** 2)


    def _eggholder(x):
        x1, x2 = x[..., 0], x[..., 1]
        return (-(x2 + 47) * np.sin(np.sqrt(np.abs(x2 + x1 / 2 + 47)))
                - x1 * np.sin(np.sqrt(np.abs(x1 - (x2 + 47)))))


    _H3_A = np.array([[3, 10, 30], [0.1, 10, 35], [3, 10, 30], [0.1, 10, 35]])
    _H3_P = 1e-4 * np.array([[3689, 1170, 2673], [4699, 4387, 7470], [1091, 8732, 5547], [381, 5743, 8828]])
    _H6_A = np.array([[10, 3, 17, 3.5, 1.7, 8], [0.05, 10, 17, 0.1, 8, 14],
                      [3, 3.5, 1.7, 10, 17, 8], [17, 8, 0.05, 10, 0.1, 14]])
    _H6_P = 1e-4 * np.array([[1312, 1696, 5569, 124, 8283, 5886], [2329, 4135, 8307, 3736, 1004, 9991],
                             [2348, 1451, 3522, 2883, 3047, 6650], [4047, 8828, 8732, 5743, 1091, 381]])
    _H_ALPHA = np.array([1.0, 1.2, 3.0, 3.2])


    def _hartmann(A, P):
        def f(x):
            inner = np.sum(A * (np.asarray(x)[..., None, :] - P) ** 2, axis=-1)
            return -np.sum(_H_ALPHA * np.exp(-inner), axis=-1)
        return f


    def _same(v):  # minimizer with every coordinate equal to v
        return lambda d: [np.full(d, float(v))]


    SURFACES = {s.key: s for s in [
        # ---- classics: any dimension ----
        Surface("sphere", "Sphere", _sphere, (-5.12, 5.12), (2, 10), _same(0), r"""
    $f(x)=\sum_i x_i^2$. One smooth bowl with no traps. This is the sanity check: every
    reasonable optimizer should solve it, so it shows raw efficiency, and whether a method
    wastes experiments when the problem is easy."""),
        Surface("rosenbrock", "Rosenbrock (banana)", _rosenbrock, (-2.048, 2.048), (2, 10), _same(1), r"""
    $f(x)=\sum_{i=1}^{d-1}\left[100\,(x_{i+1}-x_i^2)^2+(1-x_i)^2\right]$, minimum 0 at $(1,\dots,1)$.
    A long, curved valley with an almost flat floor. Finding the valley is easy; following it
    to the minimum is hard, because the floor bends and barely slopes. Tests whether a method
    can travel along a narrow curved valley."""),
        Surface("rastrigin", "Rastrigin", _rastrigin, (-5.12, 5.12), (2, 10), _same(0), r"""
    $f(x)=10d+\sum_i\left[x_i^2-10\cos(2\pi x_i)\right]$. A bowl covered by a regular egg crate
    of local minima, about 10 per dimension. Tests escaping local minima: local methods such
    as Nelder–Mead tend to settle in the nearest dip."""),
        Surface("ackley", "Ackley", _ackley, (-32.768, 32.768), (2, 10), _same(0), r"""
    $f(x)=-20\,e^{-0.2\sqrt{\frac1d\sum x_i^2}}-e^{\frac1d\sum\cos 2\pi x_i}+20+e$. Nearly flat
    far from the center, with small ripples everywhere and a sharp hole in the middle. Tests
    searching with little guidance: far out, the surface barely says which way to go.
    The right panel zooms in on the center.""", zoom=5),
        Surface("griewank", "Griewank", _griewank, (-600, 600), (2, 10), _same(0), r"""
    $f(x)=\frac{1}{4000}\sum x_i^2-\prod\cos\left(x_i/\sqrt i\right)+1$. A huge, gentle bowl with
    tiny dense ripples that are only visible zoomed in (right panel). Many local minima,
    but they get shallower relative to the bowl as $d$ grows, so in a sense it gets
    *easier* in higher dimensions.""", zoom=30),
        Surface("schwefel", "Schwefel", _schwefel, (-500, 500), (2, 10), _same(420.968746), r"""
    $f(x)=418.9829\,d-\sum x_i\sin\sqrt{|x_i|}$, minimum near $x_i=420.97$. Rugged and deceptive:
    the best point sits near a corner of the box, and the second-best basin is far away on
    the other side. Methods that drift toward the center, or trust nearby points, are misled.""",
                shiftable=False),
        Surface("levy", "Levy", _levy, (-10, 10), (2, 10), _same(1), r"""
    With $w_i=1+(x_i-1)/4$: $f=\sin^2(\pi w_1)+\sum_{i<d}(w_i-1)^2\left[1+10\sin^2(\pi w_i+1)\right]
    +(w_d-1)^2\left[1+\sin^2(2\pi w_d)\right]$, minimum 0 at $(1,\dots,1)$. Many local minima
    arranged in ridges and terraces: a standard multimodal test in Bayesian optimization papers."""),
        Surface("styblinski", "Styblinski–Tang", _styblinski_tang, (-5, 5), (2, 10), _same(-2.903534), r"""
    $f(x)=\tfrac12\sum\left(x_i^4-16x_i^2+5x_i\right)$, minimum $\approx-39.166\,d$ at $x_i\approx-2.9035$.
    Each coordinate has two dips, a deeper one at $-2.90$ and a shallower one at $+2.75$, so
    there are $2^d$ basins and only one is the best. Tests choosing the right basin."""),
        Surface("michalewicz", "Michalewicz", _michalewicz, (0, np.pi), (2, 10), _michalewicz_argmin, r"""
    $f(x)=-\sum_i\sin(x_i)\,\sin^{20}\!\left(i\,x_i^2/\pi\right)$. Mostly flat, with steep, narrow
    valleys that get narrower in later dimensions: a needle in a haystack. Methods that rely
    on smooth trends see almost nothing until they happen to land in a valley.""", shiftable=False),
        # ---- fixed dimension ----
        Surface("branin", "Branin (Branin–Hoo)", _branin, [(-5, 10), (0, 15)], 2,
                lambda d: [np.array([-np.pi, 12.275]), np.array([np.pi, 2.275]), np.array([9.42478, 2.475])], r"""
    $f=\left(x_2-\frac{5.1}{4\pi^2}x_1^2+\frac5\pi x_1-6\right)^2+10\left(1-\frac1{8\pi}\right)\cos x_1+10$.
    Smooth, with three equally good minima (0.3979). The classic Bayesian optimization demo:
    easy to picture, and a test of finding *one* of several equal optima."""),
        Surface("camel", "Six-hump camel", _six_hump_camel, [(-3, 3), (-2, 2)], 2,
                lambda d: [np.array([0.0898, -0.7126]), np.array([-0.0898, 0.7126])], r"""
    $f=\left(4-2.1x_1^2+\tfrac{x_1^4}{3}\right)x_1^2+x_1x_2+\left(-4+4x_2^2\right)x_2^2$. Six local
    minima, two of them global (mirror images, $-1.0316$). Values climb steeply toward the
    edges, so the log color scale is needed to see the humps."""),
        Surface("himmelblau", "Himmelblau", _himmelblau, (-5, 5), 2,
                lambda d: [np.array(p) for p in [(3, 2), (-2.805118, 3.131312), (-3.779310, -3.283186),
                                                 (3.584428, -1.848126)]], r"""
    $f=(x_1^2+x_2-11)^2+(x_1+x_2^2-7)^2$. Four equally good minima (all 0), one in each part of
    the box. Good for seeing that different replicates can end in different minima."""),
        Surface("goldstein", "Goldstein–Price", _goldstein_price, (-2, 2), 2, lambda d: [np.array([0.0, -1.0])], r"""
    A product of two polynomials; minimum 3 at $(0,-1)$. Values span about six orders of
    magnitude (3 to $10^6$), so anything that looks at raw values is dominated by the huge
    ones. This is why the Gaussian process here models log(error)."""),
        Surface("beale", "Beale", _beale, (-4.5, 4.5), 2, lambda d: [np.array([3.0, 0.5])], r"""
    $f=(1.5-x_1+x_1x_2)^2+(2.25-x_1+x_1x_2^2)^2+(2.625-x_1+x_1x_2^3)^2$, minimum 0 at $(3,0.5)$.
    A narrow, curved valley between sharp peaks in the corners: a teaching staple."""),
        Surface("booth", "Booth", _booth, (-10, 10), 2, lambda d: [np.array([1.0, 3.0])], r"""
    $f=(x_1+2x_2-7)^2+(2x_1+x_2-5)^2$, minimum 0 at $(1,3)$. A stretched, tilted bowl (a quadratic).
    Easy; tests coping with a valley that is not lined up with the axes."""),
        Surface("easom", "Easom", _easom, (-100, 100), 2, lambda d: [np.array([np.pi, np.pi])], r"""
    $f=-\cos x_1\cos x_2\,e^{-(x_1-\pi)^2-(x_2-\pi)^2}$, minimum $-1$ at $(\pi,\pi)$. Flat almost
    everywhere with one tiny hole: a needle in a haystack. In a few dozen tries, finding it
    is mostly luck. The right panel zooms in on the hole.""", zoom=6),
        Surface("eggholder", "Eggholder", _eggholder, (-512, 512), 2, lambda d: [np.array([512.0, 404.2319])], r"""
    $f=-(x_2+47)\sin\sqrt{|x_2+x_1/2+47|}-x_1\sin\sqrt{|x_1-(x_2+47)|}$, minimum $-959.64$ at
    $(512, 404.23)$, on the edge of the box. Extremely rugged: deep local minima everywhere,
    and the best one sits on the boundary.""", shiftable=False),
        Surface("hartmann3", "Hartmann-3", _hartmann(_H3_A, _H3_P), (0, 1), 3,
                lambda d: [np.array([0.114614, 0.555649, 0.852547])], r"""
    $f=-\sum_{i=1}^{4}\alpha_i\exp\left(-\sum_{j}A_{ij}(x_j-P_{ij})^2\right)$ on $[0,1]^3$,
    minimum $-3.8628$. Four Gaussian-shaped dips of different depths and widths: smooth, but with
    local minima. Its 3-D unit cube matches the LED problem exactly, so it is the closest
    synthetic cousin of our color matching."""),
        Surface("hartmann6", "Hartmann-6", _hartmann(_H6_A, _H6_P), (0, 1), 6,
                lambda d: [np.array([0.20169, 0.150011, 0.476874, 0.275332, 0.311652, 0.6573])], r"""
    The same form in 6 dimensions, minimum $-3.3224$. The standard medium-dimensional benchmark
    for Bayesian optimization: smooth and moderately multimodal, it tests how methods cope
    beyond 3 dimensions."""),
    ]}

    return (SURFACES,)


@app.cell(hide_code=True)
def _(Space, mo, np, optimize, plt, replicate_figure, replicate_table):
    # ---------------- Section 10 helpers: heatmaps and replicate runs ----------------

    from matplotlib.colors import BoundaryNorm


    def _fmt_point(p, max_dims=4):
        p = list(p)
        s = ", ".join(f"{v:.4g}" for v in p[:max_dims])
        return f"({s}{', …' if len(p) > max_dims else ''})"


    def surface_header(number, s, controls):
        """Title, explanation and controls of one benchmark subsection."""
        return mo.vstack([
            mo.md(f"### 10.{number} {s.name}\n{s.blurb}"),
            mo.hstack(controls, justify="start", gap=2),
        ])


    def surface_heatmap(s, d=None, res=241):
        """2-D heatmap of log10(f - f*); for d > 2 a slice through the global minimum."""
        d = s.dim(d)
        lo, hi = s.box(d)
        f_star, mins = s.f_min(d), s.minimizers(d)
        panels = [("Whole domain", (lo[0], hi[0]), (lo[1], hi[1]))]
        if s.zoom:
            c = mins[0]
            panels.append((f"Zoom around the minimum (±{s.zoom:g})",
                           (max(lo[0], c[0] - s.zoom), min(hi[0], c[0] + s.zoom)),
                           (max(lo[1], c[1] - s.zoom), min(hi[1], c[1] + s.zoom))))
        fig, axes = plt.subplots(1, len(panels), figsize=(5.3 * len(panels), 4.3), squeeze=False)
        shown = mins if d == 2 else mins[:1]  # for d > 2 only the slice's own minimum lies on it
        for ax, (title, b0, b1) in zip(axes[0], panels):
            g0, g1 = np.linspace(*b0, res), np.linspace(*b1, res)
            G0, G1 = np.meshgrid(g0, g1)
            pts = np.tile(mins[0], (res * res, 1))
            pts[:, 0], pts[:, 1] = G0.ravel(), G1.ravel()
            z = np.log10(np.maximum(s.f(pts) - f_star, 1e-12)).reshape(res, res)
            # Equal-area color bands: band edges at quantiles of z, so every color covers the
            # same share of the plot and faint structure stays visible. Bright = close to the best.
            levels = np.unique(np.quantile(z, np.linspace(0, 1, 25)))
            if len(levels) < 8:  # mostly one flat plateau (e.g. Easom): use evenly spaced bands
                levels = np.linspace(z.min(), z.max() + 1e-9, 25)
            cmap = plt.get_cmap("viridis_r")
            im = ax.contourf(g0, g1, z, levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N))
            ax.contour(g0, g1, z, levels=levels[::2], colors="k", linewidths=0.3, alpha=0.35)
            for m in shown:
                if b0[0] <= m[0] <= b0[1] and b1[0] <= m[1] <= b1[1]:
                    ax.plot(m[0], m[1], marker="*", ms=14, color="red", mec="white", mew=0.8)
            ax.set_xlabel("$x_1$")
            ax.set_ylabel("$x_2$")
            ax.set_title(title, fontsize=10)
            cb = fig.colorbar(im, ax=ax, spacing="uniform", label="log$_{10}$(f \u2212 f*)")
            cb.set_ticks(levels[:: max(1, len(levels) // 6)])
            cb.ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.2g"))
        if d > 2:
            fig.suptitle(f"{s.name}, d = {d}: slice through the minimum "
                         f"($x_3 \\dots x_{{{d}}}$ at their best values)", fontsize=10)
        fig.tight_layout()
        plt.close(fig)
        where = "; ".join(_fmt_point(m) for m in mins)
        dom = " × ".join(f"[{a:g}, {b:g}]" for a, b in zip(lo[:2], hi[:2])) + (" × …" if d > 2 else "")
        return mo.vstack([
            fig,
            mo.md(f"Domain {dom} (d = {d}). Global minimum f* = {f_star:.6g} at {where} (red star). "
                  "Colors are equal-area bands of log\u2081\u2080(f \u2212 f*) (each color covers the same share "
                  "of the plot); bright = close to the best."),
        ])


    def surface_run(s, d, queue, reps, n_iter, run, results, refresh=None, shift=False):
        """Run every optimizer in the list `reps` times on surface s, then show the comparison.

        shift: move the optimum to a random spot in each replicate (the same spot for every
            optimizer in that replicate), so a method can't win by always trying the center.
        Results are kept per (surface, d, shifted) in `results`, so they survive slider changes.
        `refresh` is only there so that clearing all results redraws this cell.
        """
        d = s.dim(d)
        shifted = bool(shift and s.shiftable)
        key = (s.key, d, shifted)
        if run:
            if not queue:
                return mo.md("The optimizer list at the top of section 10 is empty.")
            space = Space(d)  # continuous unit cube [0, 1]^d
            # one seed per replicate, shared by every optimizer in the list (paired comparison)
            seed = int(np.random.SeedSequence().entropy % 2**32)
            rep_seeds = np.random.SeedSequence(seed).spawn(reps)
            shifts = [s.random_shift(d, np.random.default_rng([seed, r])) if shifted else None
                      for r in range(reps)]
            store = results.setdefault(key, {})
            with mo.status.progress_bar(total=len(queue) * reps, title=f"{s.name}, d = {d}",
                                        remove_on_exit=True) as bar:
                for e in queue:
                    Xs, Y = [], []
                    for r, ss in enumerate(rep_seeds):
                        def evaluate(u, delta=shifts[r]):
                            return s.error(u, d, delta), None

                        X, y = optimize(e["method"], n_iter, evaluate, np.random.default_rng(ss), space=space,
                                        acq=e["acq"] or "EI", beta=e["beta"] or 2.0)
                        Xs.append(X)
                        Y.append(y)
                        bar.update(subtitle=f"{e['label']}: replicate {r + 1}/{reps}")
                    store.pop(e["label"], None)  # re-running replaces and moves to the end
                    store[e["label"]] = {**e, "X": Xs, "Y": Y, "seed": seed, "shifts": shifts}
        note = []
        if shift and not s.shiftable:
            note = [mo.md("*Not shifted: this surface's optimum is already off-center, and moving it "
                          "would bring in values below f\\* from outside the box.*")]
        stored = results.get(key)
        kind = "randomly shifted" if shifted else "unshifted"
        if not stored:
            return mo.vstack(note + [mo.md(f"*No {kind} results for {s.name} with d = {d} yet: press **Run**.*")])
        return mo.vstack(note + [
            mo.md(f"**{s.name}, d = {d}, {kind}**"),
            replicate_figure(stored, ylabel="Best f \u2212 f* so far (log scale)\nmean \u00b1 1 SD over replicates"),
            replicate_table(stored),
        ])


    return surface_header, surface_heatmap, surface_run


if __name__ == "__main__":
    app.run()
