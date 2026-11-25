#!/bin/bash
# Double-click to open the class demo notebook (sdl_class_demo.ipynb) in JupyterLab.
# Installs uv the first time if missing. Keep this window open while you use the notebook.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$HOME/.homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (one time)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "Starting JupyterLab (the first run downloads packages, about a minute)..."
echo "Your browser will open the notebook. Keep this window open; close it to stop Jupyter."
uv run --no-project --with jupyterlab,paho-mqtt,numpy,matplotlib,scikit-learn,scipy \
  jupyter lab sdl_class_demo.ipynb
