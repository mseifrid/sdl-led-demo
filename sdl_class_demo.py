# /// script
# requires-python = ">=3.10"
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
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Self-driving lab demo: match a hidden color

    A **self-driving lab (SDL)** runs experiments by itself: a computer picks the next experiment,
    a machine does it, a sensor measures the result, and the computer uses that result to choose
    a better experiment next time. This demo follows Baird & Sparks, *"What is a minimal working
    example for a self-driving laboratory?"* (Matter, 2022): an RGB LED shines on an 8-channel
    light sensor (410 to 670 nm), and the goal is to find the LED color whose spectrum matches a
    hidden target.

    **How the pieces talk to each other** (one experiment):

    | | From | To | Message |
    |---|---|---|---|
    | 1 | this notebook | MQTT broker (cloud) | "set the LED to R, G, B" |
    | 2 | MQTT broker | device (Wokwi tab) | same command; the LED lights up, the sensor reads |
    | 3 | device | MQTT broker → this notebook | the 8 sensor readings |

    The notebook and the device never connect to each other directly: both connect to the
    broker, which passes messages between them, just like the paper's real Pico W.

    The device is a **simulated board** running in [Wokwi](https://wokwi.com) in another browser
    tab: an ESP32 (Wokwi simulates Wi-Fi only on the ESP32) running the same MicroPython code
    and the same messages as the paper's Pico W. Its LED ring changes color every time this
    notebook sends a command. Wokwi has no AS7341 sensor part, so the device computes the 8
    readings with a simple light model (each LED color adds light to certain channels, plus
    room light and 2% noise).

    **Before you start:**

    1. Open the Wokwi project, press the green ▶ button, and wait until the small screen says
       **Ready!** (up to a minute).
    2. Put Wokwi and this notebook **side by side, in two separate browser windows**, not two
       tabs of one window. Wokwi nearly pauses when its tab is hidden, and then the notebook's
       commands time out. If that happens, bring Wokwi back into view: it reconnects within a
       few seconds.
    3. This is a **marimo** notebook: cells re-run by themselves when something they use
       changes. Steps 0 to 5 run as soon as the notebook opens. If Step 2 timed out because
       Wokwi wasn't ready yet, click the ▶ button on that cell to run it again. The
       self-driving runs (Step 7) and the disconnect (Step 9) only start when you click
       their buttons.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 0. Load the tools and your settings

    **What this cell does:** loads the Python libraries and reads your broker settings from the
    `.env` file next to this notebook (see `.env.example`). Nothing secret is printed.

    **Check:** the `Device` name printed below must match `PICO_ID` in Wokwi's `config.py`.
    """)
    return


@app.cell
def _():
    import time
    import warnings

    import matplotlib.pyplot as plt
    import numpy as np

    from sdl_client import CHANNELS, LedLab, load_settings

    settings = load_settings(".env")
    print("Broker :", settings["host"] or "(missing! add MQTT_HOST to .env)", "port", settings["port"])
    print("Login  :", "yes" if settings["username"] else "none (public broker)")
    print("Device :", settings["pico_id"], "  <- must match PICO_ID in the Wokwi config.py")
    return CHANNELS, LedLab, np, plt, time, warnings


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What this cell does:** defines how the spectra are drawn (8 bars, one per sensor channel,
    colored by wavelength). Nothing happens on the board.
    """)
    return


@app.cell
def _(CHANNELS, np, plt):
    # Plot helpers (nothing to change here)
    WAVELENGTHS = [int(c[2:]) for c in CHANNELS]
    CHANNEL_COLORS = ["#7b2fbe", "#3b3bff", "#0f8bff", "#00b84a", "#9ccc00", "#ffb300", "#ff6d00", "#d50000"]
    METHOD_COLORS = {"Random search": "#8a8a8a", "Grid search": "#e08a00", "Bayesian optimization": "#1f5fd6"}


    def swatch(ax, rgb):
        ax.set_ylim(top=ax.get_ylim()[1] * 1.45)  # room for the color square
        sw = ax.inset_axes([0.86, 0.72, 0.12, 0.24])
        sw.set_facecolor(np.array(rgb) / 255)
        sw.set_xticks([]); sw.set_yticks([])
        sw.set_title("LED", fontsize=8)


    def spectrum_plot(readings, rgb=None, title="", ax=None):
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 3))
        ax.bar([str(w) for w in WAVELENGTHS], readings, color=CHANNEL_COLORS)
        ax.set_xlabel("Sensor channel (nm)")
        ax.set_ylabel("Counts")
        ax.set_title(title)
        if rgb is not None:
            swatch(ax, rgb)
        return ax

    return CHANNEL_COLORS, METHOD_COLORS, WAVELENGTHS, spectrum_plot, swatch


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 1. Connect to the broker

    **What this cell does:** logs in to the MQTT broker (the cloud "post office" between this
    notebook and the device) and starts listening for the device's replies.

    **Watch:** nothing changes on the board yet. The notebook and the device have not talked
    to each other; they are both just connected to the broker.
    """)
    return


@app.cell
def _(LedLab):
    lab = LedLab.from_env(".env")
    print("Connected to the broker. Talking to device:", lab.pico_id)
    return (lab,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 2. First experiment: is anyone there?

    **What this cell does:** sends one command, "LED off" (R = G = B = 0), and waits for the
    8 readings to come back. With the LED off, the sensor only sees room light, so the numbers
    are small.

    **Watch:** the Wokwi screen changes to **Exp #1** with 8 tiny bars, and the serial log
    prints the same 8 numbers you see here. That's one full round trip:
    notebook → broker → device → broker → notebook.

    If this times out, check that the Wokwi simulation is running and says **Ready!**, and that
    `PICO_ID` is the same in `.env` and in Wokwi's `config.py`. Then click ▶ on the cell to
    run it again.
    """)
    return


@app.cell
def _(CHANNELS, lab, time):
    start = time.time()
    first_readings = lab.measure(0, 0, 0)
    print(f"Reply in {time.time() - start:.2f} s")
    print(dict(zip(CHANNELS, first_readings)))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 3. Send a color and watch the Wokwi tab

    **What this cell does:** sends one color and plots what the sensor measured.

    **Watch:** the LED ring turns that color, and the screen's bars match the plot below.
    Then move the `R`, `G`, `B` sliders (each 0 to 255): a new experiment runs every time you
    let go of a slider.
    """)
    return


@app.cell
def _(mo):
    r_slider = mo.ui.slider(0, 255, value=25, label="R", debounce=True, show_value=True)
    g_slider = mo.ui.slider(0, 255, value=121, label="G", debounce=True, show_value=True)
    b_slider = mo.ui.slider(0, 255, value=69, label="B", debounce=True, show_value=True)
    mo.hstack([r_slider, g_slider, b_slider], justify="start")
    return b_slider, g_slider, r_slider


@app.cell
def _(b_slider, g_slider, lab, r_slider, spectrum_plot):
    R, G, B = r_slider.value, g_slider.value, b_slider.value
    color_readings = lab.measure(R, G, B)
    spectrum_plot(color_readings, rgb=(R, G, B), title=f"Measured spectrum for RGB = {(R, G, B)}")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What this cell does:** four experiments in a row: pure red, green, blue and white,
    one second apart.

    **Watch:** the ring cycles through the four colors. **Question:** which sensor channels light
    up for each color? (Red light lands in the 620 nm channel, blue in 440 to 470 nm.)
    """)
    return


@app.cell
def _(lab, plt, spectrum_plot, time):
    colors = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255)}
    primaries_fig, axes = plt.subplots(2, 2, figsize=(11, 6))
    for ax, (name, rgb) in zip(axes.flat, colors.items()):
        spectrum_plot(lab.measure(*rgb), rgb=rgb, title=name, ax=ax)
        time.sleep(1)  # time to see each color in the Wokwi tab
    primaries_fig.tight_layout()
    primaries_fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4. The hidden target

    **What this cell does:** picks a secret color and measures it once. You only get to see what
    the **sensor** saw, never the color itself. Your job: find a color that produces the same
    pattern.

    **Watch:** the board measures the target with the ring dark, and the screen says
    **TARGET (hidden)**, so the color isn't given away.
    """)
    return


@app.cell
def _(lab, np, spectrum_plot):
    TARGET_SEED = 11262026  # change to get a different secret color
    secret_rgb = tuple(int(v) for v in np.random.default_rng(TARGET_SEED).integers(30, 226, size=3))
    target = lab.measure(*secret_rgb, hidden=True)  # the device won't display this color
    spectrum_plot(target, title="Target spectrum (RGB hidden)")
    return secret_rgb, target


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 5. Scoring a guess

    We need one number that says how far a measurement $m$ is from the target $t$. A bright and
    a dim version of the same color give the same *shape* but different heights, so we first
    divide each spectrum by its total (turning counts into shares), then average the gaps over the
    8 channels:

    $$\text{error} = \frac{1}{8}\sum_{i=1}^{8}\left|\frac{m_i}{\sum_j m_j} - \frac{t_i}{\sum_j t_j}\right|$$

    0 means a perfect match; lower is better.

    **What these cells do:** define the score, then try one guess by hand (mid gray to start).

    **Watch:** the ring shows your guess. Move the sliders: can you get below 0.01?
    """)
    return


@app.cell
def _(np):
    def normalize(readings):
        # Counts -> share of the total signal in each channel
        r = np.asarray(readings, dtype=float)
        return r / r.sum()


    def objective(readings, target):
        # Normalized mean absolute error between a measurement and the target
        return float(np.mean(np.abs(normalize(readings) - normalize(target))))

    return normalize, objective


@app.cell
def _(mo):
    guess_r = mo.ui.slider(0, 255, value=128, label="R", debounce=True, show_value=True)
    guess_g = mo.ui.slider(0, 255, value=128, label="G", debounce=True, show_value=True)
    guess_b = mo.ui.slider(0, 255, value=128, label="B", debounce=True, show_value=True)
    mo.hstack([guess_r, guess_g, guess_b], justify="start")
    return guess_b, guess_g, guess_r


@app.cell
def _(guess_b, guess_g, guess_r, lab, mo, objective, target):
    guess = (guess_r.value, guess_g.value, guess_b.value)
    guess_error = objective(lab.measure(*guess), target)
    mo.md(f"Error for {guess}: **{guess_error:.4f}**")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 6. Three ways to choose the next experiment

    - **Random search:** pick any color. No memory of past results.
    - **Grid search:** try evenly spaced colors. Systematic, but it never uses what it learns.
    - **Bayesian optimization (BO):** after each experiment, fit a model (a *Gaussian process*)
      that predicts the error for every possible color **and how unsure it is**. Then run the color
      with the highest **expected improvement**: one that is either predicted to be good, or
      uncertain enough that it might be. Balancing *exploit what looks good* against
      *explore what is unknown* is the core idea of a self-driving lab.

    **What this cell does:** defines the three strategies. Nothing runs on the board yet.
    The first run takes about 15 seconds while the machine-learning libraries load.
    """)
    return


@app.cell
def _(np, warnings):
    from scipy.stats import norm
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


    def suggest_random(rng):
        # Any color, uniformly at random
        return tuple(int(v) for v in rng.integers(0, 256, size=3))


    def suggest_grid(i, n_total):
        # The i-th point of an evenly spaced k x k x k grid, with k^3 >= n_total
        k = int(np.ceil(n_total ** (1 / 3) - 1e-9))
        levels = ((np.arange(k) + 0.5) * 256 / k).astype(int)  # k=3 -> 42, 128, 213
        r, g, b = np.unravel_index(i, (k, k, k))
        return (int(levels[r]), int(levels[g]), int(levels[b]))


    def suggest_bo(X, y, rng, n_init=5, n_candidates=3000):
        # Bayesian optimization with a Gaussian process and Expected Improvement
        if len(X) < n_init:  # 0. no data yet: start with a few random colors
            return suggest_random(rng)

        Xs = np.array(X) / 255     # 1. data, scaled to 0..1;
        ys = np.log(np.array(y))   #    the model learns log(error)

        kernel = ConstantKernel(1.0) * Matern(  # 2. model: nearby colors give similar errors,
            length_scale=[0.3, 0.3, 0.3], length_scale_bounds=(1e-2, 10), nu=2.5
        ) + WhiteKernel(1e-3, noise_level_bounds=(1e-6, 1e-1))  # and measurements are noisy
        gp = GaussianProcessRegressor(kernel, normalize_y=True, n_restarts_optimizer=3, random_state=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gp.fit(Xs, ys)

        best_x = Xs[np.argmin(ys)]  # 3. candidates: random colors + some near the best so far
        near_best = np.clip(best_x + 0.05 * rng.standard_normal((n_candidates // 3, 3)), 0, 1)
        candidates = np.vstack([rng.random((n_candidates, 3)), near_best])

        mu, sigma = gp.predict(candidates, return_std=True)  # 4. expected improvement
        sigma = np.maximum(sigma, 1e-9)
        improvement = ys.min() - mu
        z = improvement / sigma
        ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)

        return tuple(int(v) for v in np.round(candidates[np.argmax(ei)] * 255))  # 5. best EI


    def propose_next(method, X, y, rng, n_total):
        if method == "Random search":
            return suggest_random(rng)
        if method == "Grid search":
            return suggest_grid(len(X), n_total)
        return suggest_bo(X, y, rng)

    return (propose_next,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What this cell does:** defines the self-driving loop that runs in Step 7. Each turn it
    **decides** a color (with the chosen strategy), **runs the experiment** on the board,
    **scores** the result, and **redraws** the plot, with no human in the loop. Nothing runs yet.
    """)
    return


@app.cell
def _(
    CHANNEL_COLORS,
    WAVELENGTHS,
    lab,
    mo,
    normalize,
    np,
    objective,
    plt,
    propose_next,
    swatch,
    target,
):
    def live_figure(X, y, readings, method, n_total):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 3.8))
        it = np.arange(1, len(y) + 1)
        ax1.scatter(it, y, s=30, c=[np.array(x) / 255 for x in X], edgecolors="0.3", linewidths=0.6,
                    zorder=3, label="each experiment")
        ax1.plot(it, np.minimum.accumulate(y), color="black", lw=2, label="best so far")
        ax1.set_yscale("log"); ax1.set_xlim(0.5, n_total + 0.5)
        ax1.set_xlabel("Experiment"); ax1.set_ylabel("Error (log scale)"); ax1.legend(fontsize=8)

        x = np.arange(len(WAVELENGTHS)); w = 0.4
        ax2.bar(x - w / 2, normalize(target), w, color="white", edgecolor="black", label="target")
        ax2.bar(x + w / 2, normalize(readings), w, color=CHANNEL_COLORS, label="this experiment")
        ax2.set_xticks(x, [str(v) for v in WAVELENGTHS])
        ax2.set_xlabel("Sensor channel (nm)"); ax2.set_ylabel("Share of total signal")
        ax2.legend(loc="upper left", fontsize=8)
        swatch(ax2, X[-1])
        fig.suptitle(f"{method}: experiment {len(y)}/{n_total}, RGB = {X[-1]}, error = {y[-1]:.4f}")
        fig.tight_layout()
        return fig


    def run_sdl(method, n_experiments=20):
        # The self-driving loop: decide -> experiment -> score -> repeat
        rng = np.random.default_rng()
        X, y = [], []
        for _ in range(n_experiments):
            rgb = propose_next(method, X, y, rng, n_experiments)  # 1. decide
            readings = lab.measure(*rgb)                          # 2. experiment (watch Wokwi!)
            X.append(rgb)
            y.append(objective(readings, target))                 # 3. score
            fig = live_figure(X, y, readings, method, n_experiments)
            mo.output.replace(fig)                                # 4. show it live
            plt.close(fig)
        best = int(np.argmin(y))
        print(f"{method}: best error {y[best]:.4f} with RGB = {X[best]}, found at experiment {best + 1}")
        return {"X": X, "y": y}


    N_EXPERIMENTS = 20
    return N_EXPERIMENTS, run_sdl


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 7. Run the self-driving lab

    Each button below runs 20 experiments on its own, about 15 to 30 seconds per strategy. The
    plot redraws after every experiment: on the left, each experiment's error (dots colored like
    the LED) and the best so far; on the right, the latest spectrum against the target. Click a
    button again to repeat that run.

    ### 7a. Random search

    **Watch:** the ring jumps between unrelated colors; the error goes down only by luck.
    """)
    return


@app.cell
def _(mo):
    random_button = mo.ui.run_button(label="Run random search")
    random_button
    return (random_button,)


@app.cell
def _(N_EXPERIMENTS, random_button, run_sdl):
    random_run = run_sdl("Random search", N_EXPERIMENTS) if random_button.value else None
    return (random_run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7b. Grid search

    **Watch:** the colors step through a fixed pattern (low, medium, high for each of red, green,
    blue), whatever the results say.
    """)
    return


@app.cell
def _(mo):
    grid_button = mo.ui.run_button(label="Run grid search")
    grid_button
    return (grid_button,)


@app.cell
def _(N_EXPERIMENTS, grid_button, run_sdl):
    grid_run = run_sdl("Grid search", N_EXPERIMENTS) if grid_button.value else None
    return (grid_run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7c. Bayesian optimization

    **Watch:** the first 5 colors are random, to get some data. After that the model picks each
    color, and the ring settles on similar shades as it closes in on the target.
    """)
    return


@app.cell
def _(mo):
    bo_button = mo.ui.run_button(label="Run Bayesian optimization")
    bo_button
    return (bo_button,)


@app.cell
def _(N_EXPERIMENTS, bo_button, run_sdl):
    bo_run = run_sdl("Bayesian optimization", N_EXPERIMENTS) if bo_button.value else None
    return (bo_run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 8. Compare the optimizers

    **What this cell does:** puts the "best so far" curves of every strategy you have run on one
    plot, lists each strategy's best color, and finally reveals the secret color. It updates
    by itself after each run in Step 7.

    **Question:** which strategy reaches a low error in the fewest experiments? Run Step 7 again:
    does the ranking hold?
    """)
    return


@app.cell
def _(METHOD_COLORS, bo_run, grid_run, mo, np, plt, random_run, secret_rgb):
    runs = {
        name: run
        for name, run in [
            ("Random search", random_run),
            ("Grid search", grid_run),
            ("Bayesian optimization", bo_run),
        ]
        if run is not None
    }
    mo.stop(not runs, mo.md("*Run at least one strategy in Step 7 to compare.*"))

    compare_fig, compare_ax = plt.subplots(figsize=(7, 3.6))
    for method, run in runs.items():
        steps = np.arange(1, len(run["y"]) + 1)
        compare_ax.plot(steps, np.minimum.accumulate(run["y"]), lw=2, label=method,
                        color=METHOD_COLORS.get(method))
    compare_ax.set_yscale("log")
    compare_ax.set_xlabel("Experiment")
    compare_ax.set_ylabel("Best error so far (log scale)")
    compare_ax.legend(fontsize=9)
    compare_fig.tight_layout()

    rows = []
    for method, run in runs.items():
        i = int(np.argmin(run["y"]))
        rows.append({"Optimizer": method, "Best error": round(run["y"][i], 4),
                     "Best RGB": str(run["X"][i]), "Found at": i + 1})

    mo.vstack([
        compare_fig,
        mo.ui.table(rows, selection=None),
        mo.md(f"The secret color was **RGB = {secret_rgb}**"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 9. Disconnect

    **What this cell does:** turns the LED off and logs out of the broker.

    **Watch:** the ring goes dark.
    """)
    return


@app.cell
def _(mo):
    disconnect_button = mo.ui.run_button(label="Disconnect")
    disconnect_button
    return (disconnect_button,)


@app.cell
def _(disconnect_button, lab, mo):
    mo.stop(not disconnect_button.value)
    lab.measure(0, 0, 0)  # LED off
    lab.close()
    print("Disconnected.")
    return


if __name__ == "__main__":
    app.run()
