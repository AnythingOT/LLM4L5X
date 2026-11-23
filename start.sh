#!/usr/bin/env sh
# LLM4L5X start for Linux/macOS. First run creates .venv and installs requirements.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
echo "LLM4L5X at http://127.0.0.1:5000  (Ctrl+C to stop)"
echo "Keep the model server on this PC: never start llama-server or Ollama with --host 0.0.0.0"
exec .venv/bin/python app.py
