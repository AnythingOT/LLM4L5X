"""LLM4L5X local web GUI.

Run from the repo root:   python app.py
Then open:                 http://127.0.0.1:5000

Single-user local tool: the attached file lives in memory and is forgotten when the server
stops. Nothing is sent anywhere except to the model server you choose in Settings.
"""

from gui import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)  # 127.0.0.1: reachable from this PC only
