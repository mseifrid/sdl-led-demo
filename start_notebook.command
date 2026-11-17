#!/bin/bash
# Double-click to open the SDL demo notebook. Installs uv the first time if missing.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$HOME/.homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uvx >/dev/null 2>&1; then
  echo "Installing uv (one time)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "Starting marimo (first run installs packages, about a minute)..."
uvx marimo edit --sandbox sdl_demo.py
