#!/usr/bin/env sh
# LLM4L5X start for Linux/macOS.
# The packages live outside this folder (~/.local/share/llm4l5x/venv, or $LLM4L5X_VENV), so a new download
# of the repo starts at once: they are installed once, and again only when requirements.txt changes.
cd "$(dirname "$0")" || exit 1
VENV="${LLM4L5X_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/llm4l5x/venv}"
PY="$VENV/bin/python"

# a venv made by a Python that is gone (upgraded, removed) does not run: make it again
if [ -x "$PY" ] && ! "$PY" -c "import sys" >/dev/null 2>&1; then
    echo "The package folder no longer works with this Python: making it again."
    rm -rf "$VENV"
fi
if [ ! -x "$PY" ]; then
    echo "First start: installing the packages into $VENV (once)."
    python3 -m venv "$VENV" || exit 1
fi
if ! cmp -s requirements.txt "$VENV/requirements.txt"; then
    echo "Installing packages: requirements.txt is new or changed."
    "$PY" -m pip install --upgrade pip >/dev/null && "$PY" -m pip install -r requirements.txt || exit 1
    cp requirements.txt "$VENV/requirements.txt"
fi
echo "LLM4L5X at http://127.0.0.1:5000  (Ctrl+C to stop)"
echo "Keep the model server on this PC: never start llama-server or Ollama with --host 0.0.0.0"
exec "$PY" app.py
