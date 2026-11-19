"""The local web GUI: pages and the JSON API behind them. Routes stay thin; the work is in
logic.py (rungs), project.py (the attached L5X) and udts.py (UDTs)."""

from __future__ import annotations

import base64
import json
import time

from flask import Flask, Response, jsonify, render_template, request

import lint
from gui import logic, project, state, udts
from gui.state import SESSION
from inputs.llm import BACKENDS, LLMError
from l5x.reader import read_l5x
from udt.excel import read_excel, template
from udt.model import UdtError

MAX_UPLOAD = 50 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

    # ------------------------------------------------------------ pages

    @app.get("/")
    def index():
        return render_template("index.html", page="chat")

    @app.get("/settings")
    def settings_page():
        return render_template("settings.html", page="settings")

    @app.get("/rules")
    def rules_page():
        return render_template("rules.html", page="rules")

    # ------------------------------------------------------------ chat box

    @app.post("/api/process")
    def process():
        """One endpoint for the chat box: a command, logic (English, LogicSpec, rungs) or a UDT."""
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        s = state.settings(data.get("settings"))
        if not text:
            return jsonify(kind="error", message="Nothing to process.")
        t0 = time.perf_counter()
        out = _dispatch(text, data.get("mode"), s)
        out["seconds"] = round(time.perf_counter() - t0, 3)
        return jsonify(out)

    # ------------------------------------------------------------ attached file

    @app.post("/api/project")
    def attach():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify(kind="error", message="No file received.")
        name = f.filename
        if name.lower().endswith((".xlsx", ".xlsm")):  # a UDT sheet: build UDTs, the attached file stays
            try:
                found = read_excel(f.read())
            except UdtError as e:
                return jsonify(kind="error", message=f"{name}: {e}", hint="Download the template: ⓘ in UDT mode.")
            return jsonify(udts.created(found, state.settings(json.loads(request.form.get("settings") or "{}")),
                                        source=f"Excel sheet {name}"))
        if not name.lower().endswith(".l5x"):
            return jsonify(kind="error", message="Attach an .L5X export from Studio 5000, or an Excel UDT sheet (.xlsx).")
        raw = f.read()
        try:
            p = read_l5x(raw)
        except Exception as e:  # noqa: BLE001 - any format error is shown to the user; the server keeps running
            return jsonify(kind="error", message=f"Could not read {name}: {e}")
        SESSION.attach(p, name, raw)
        out = project.summary()
        if p.target_type == "DataType":  # a UDT export: show what reordering would do straight away
            out["udt_plan"] = udts.plan()
        return jsonify(out)

    @app.delete("/api/project")
    def detach():
        SESSION.detach()
        return jsonify(kind="info", message="File detached. New tags are no longer checked against it.")

    @app.get("/api/status")
    def status():
        p = SESSION.project
        return jsonify(project=SESSION.filename, programs=sorted({r.program for r in p.routines}) if p else [],
                       default_program=project.default_program())

    # ------------------------------------------------------------ UDT files

    @app.post("/api/udt/download")
    def udt_download():
        if SESSION.raw is None:
            return jsonify(kind="error", message="No attached file."), 400
        d = request.get_json(silent=True) or {}
        try:
            body, name, mime, notes = udts.download(d.get("selected") or [], d.get("output") or "zip")
        except ValueError as e:
            return jsonify(kind="error", message=str(e)), 400
        r = _file(body, name, mime)
        if notes is not None:
            r.headers["X-Notes"] = base64.b64encode(json.dumps(notes).encode()).decode()
        return r

    @app.get("/api/udt/template")
    def udt_template():
        return _file(template(), "UDT_template.xlsx", XLSX)

    # ------------------------------------------------------------ settings and rules pages

    @app.post("/api/llm/models")
    def llm_models():
        """Models on the chosen local backend, and whether it is reachable."""
        s = state.settings((request.get_json(silent=True) or {}).get("settings"))
        client = state.llm(s)
        info = {"url": client.url, "backend": BACKENDS[s["backend"]]["label"],
                "grammar": bool(getattr(client, "supports_grammar", False))}
        try:
            return jsonify(ok=True, models=client.list_models(), **info)
        except LLMError as e:
            return jsonify(ok=False, models=[], error=str(e), **info)

    @app.get("/api/rules")
    def rules_list():
        return jsonify(rules=[{"code": r.code, "title": r.title, "description": r.description,
                               "severity": r.severity, "scope": r.scope, "group": r.group} for r in lint.RULES])

    return app


def _dispatch(text: str, mode: str | None, s: dict) -> dict:
    head, _, rest = text.partition(" ")
    head, rest = head.lower(), rest.strip()
    if head in ("help", "?") and not rest:
        return {"kind": "help"}
    if head in ("summary", "decompile", "validate", "optimize", "xref") and (not rest or head == "xref"):
        if SESSION.project is None:
            return {"kind": "error", "message": f"'{head}' needs an attached L5X. Use Attach first."}
        if head == "xref":
            return project.xref(rest)
        if head == "optimize":
            return udts.plan()
        if head == "validate":
            return project.validate(s)
        return project.summary() if head == "summary" else project.decompile()
    if mode == "udt" or udts.UDT_TEXT.match(text):
        return udts.from_text(text, s)
    return logic.handle(text, s)


def _file(body: bytes, name: str, mime: str) -> Response:
    r = Response(body, mimetype=mime)
    r.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return r
