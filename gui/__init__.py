"""The local web GUI: pages and the JSON API behind them. Routes stay thin; the work is in
logic.py (rungs), project.py (the attached L5X) and udts.py (UDTs)."""

from __future__ import annotations

import base64
import io
import json
import os
import time
import zipfile
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, render_template, request

import lint
from gui import jobs, logic, project, spec, state, udts
from gui.state import SESSION
from core.rung import RungSyntaxError, parse_rung
from explain.ladder import to_svg
from inputs.llm import BACKENDS, LLMError
from l5x.reader import read_l5x
from inputs.spec_excel import SpecSheetError, read_requirements, sample
from udt.excel import is_udt_sheet, read_excel, template
from udt.model import UdtError

MAX_UPLOAD = 50 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Listening on 127.0.0.1 keeps other machines out, not other web pages: the user's own browser will
# send a form post from any site to this app. So requests are refused unless they come from it.
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CHANGES = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_hosts() -> set[str]:
    extra = os.environ.get("LLM4L5X_ALLOWED_HOSTS", "")  # comma-separated, for a deliberate LAN setup
    return LOOPBACK | {h.strip().lower() for h in extra.split(",") if h.strip()}


def _foreign(req) -> str | None:
    """Why a request may not come in, or None. Host stops DNS rebinding; Origin stops other sites."""
    host = (urlsplit(f"//{req.host}").hostname or "").lower()
    if host not in _allowed_hosts():
        return f"host {req.host} is not this app"
    if req.method in CHANGES:
        origin = req.headers.get("Origin")
        if origin and origin != "null":
            o = urlsplit(origin)
            if (o.hostname or "").lower() not in _allowed_hosts() or o.netloc.lower() != req.host.lower():
                return f"request from another site ({origin})"
        elif origin == "null" or req.headers.get("Sec-Fetch-Site") == "cross-site":
            return "request from another site"
    return None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

    @app.before_request
    def _only_this_app():
        why = _foreign(request)
        if why:
            return jsonify(kind="error", message=f"Refused: {why}."), 403

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

    @app.get("/energise")
    def energise_page():
        return render_template("energise.html", page="energise")

    # ------------------------------------------------------------ energise: whole program + plant, live

    @app.post("/api/energise/load")
    def energise_load():
        from gui import energise
        files = []
        for f in request.files.getlist("files"):
            data = f.read()
            if f.filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as z:  # a Routines.zip from a requirements run
                    files += [z.read(n) for n in z.namelist() if n.lower().endswith(".l5x")]
            else:
                files.append(data)
        try:
            ses = energise.load(files, request.form.get("plant", ""), request.form.get("scenarios", ""),
                                float(request.form.get("scan_ms") or 10))
        except Exception as e:  # noqa: BLE001 - a bad file is the user's to fix: say what is wrong
            return jsonify(error=str(e)), 400
        ENERGISE["session"] = ses
        return jsonify(inputs=ses.inputs, outputs=ses.outputs, feedbacks=ses.feedbacks, skipped=ses.skipped,
                       rungs=[{"routine": p.routine, "number": p.number, "text": p.text} for p in ses.places],
                       has_scenarios=bool(ses.scenarios_text.strip()), snapshot=ses.snapshot())

    @app.post("/api/energise/step")
    def energise_step():
        ses = ENERGISE.get("session")
        if ses is None:
            return jsonify(error="load a program first"), 400
        body = request.get_json(silent=True) or {}
        try:
            if body.get("reset"):
                return jsonify(ses.reset())
            ms = min(max(float(body.get("ms") or 0), 0), 60000)
            return jsonify(ses.step(ms, body.get("writes") or {}))
        except Exception as e:  # noqa: BLE001
            return jsonify(error=str(e)), 400

    @app.post("/api/energise/scenarios")
    def energise_scenarios():
        ses = ENERGISE.get("session")
        if ses is None:
            return jsonify(error="load a program first"), 400
        out = ses.run_scenarios()
        out["trace"] = {k: [list(x) for x in v] for k, v in out["trace"].items()}
        return jsonify(out)

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
        if name.lower().endswith((".xlsx", ".xlsm")):  # Excel: UDTs or requirements; the attached L5X stays
            data = f.read()
            s = state.settings(json.loads(request.form.get("settings") or "{}"))
            if is_udt_sheet(data):
                try:
                    return jsonify(udts.created(read_excel(data), s, source=f"Excel sheet {name}"))
                except UdtError as e:
                    return jsonify(kind="error", message=f"{name}: {e}", hint="Compare with the UDT sample in the examples list.")
            try:
                sheets = read_requirements(data)
            except SpecSheetError as e:
                return jsonify(kind="error", message=f"{name} is neither a UDT sheet nor a requirements sheet: {e}",
                               hint="Start from one of the samples in the examples list.")
            job = spec.start(sheets, s, name)
            return jsonify(kind="spec_started", job=job.id, filename=name, project=SESSION.filename,
                           sheets=[{"routine": sh.routine, "title": sh.title, "rows": len(sh.rows),
                                    "model_rows": sum(1 for r in sh.rows if not r.logic)} for sh in sheets])
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
        return _file(template(), "UDT_sample.xlsx", XLSX)

    # ------------------------------------------------------------ requirements workbook (background job)

    @app.get("/api/spec/sample")
    def spec_sample():
        return _file(sample(), "Requirements_sample.xlsx", XLSX)

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id):
        job = jobs.JOBS.get(job_id)
        if job is None:
            return jsonify(kind="error", message="That job is no longer known (the server was restarted?)."), 404
        return jsonify(job.view(int(request.args.get("since", 0))))

    @app.delete("/api/jobs/<job_id>")
    def job_cancel(job_id):
        job = jobs.JOBS.get(job_id)
        if job is not None:
            job.cancel.set()
        return jsonify(ok=job is not None)

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

    @app.post("/api/ladder")
    def ladder():
        """Ladder diagrams for rung texts (the attached file's AOIs are known), drawn when asked for."""
        texts = (request.get_json(silent=True) or {}).get("rungs") or []
        catalog = SESSION.project.catalog() if SESSION.project else None
        presets = SESSION.project.presets() if SESSION.project else {}
        out = []
        for item in texts[:200]:
            try:
                out.append(to_svg(parse_rung(item.get("text", "")), catalog, number=item.get("number"),
                                  presets=presets))
            except RungSyntaxError:
                out.append(None)
        return jsonify(svgs=out)

    @app.get("/api/rules")
    def rules_list():
        return jsonify(rules=[{"code": r.code, "title": r.title, "description": r.description,
                               "severity": r.severity, "scope": r.scope, "group": r.group} for r in lint.RULES])

    return app


ENERGISE: dict = {}  # one live session: the app serves one user on this PC


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
