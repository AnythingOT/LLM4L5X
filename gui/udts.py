"""UDTs: create (text form, Excel or plain English) and optimize (the attached file's UDTs)."""

from __future__ import annotations

import base64
import io
import re
import zipfile

from gui import state
from gui.state import SESSION
from inputs.llm import LLMError
from inputs.udt_llm import generate
from udt.model import UdtError, check, dependency_order, parse_spec
from udt.optimize import file_name, full_program, single_file, zip_files
from udt.writer import ordered, sizes, write_udt

UDT_TEXT = re.compile(r"\s*UDT\s+[A-Za-z_]\w*\s*(\"[^\"]*\")?\s*;")


def project_types() -> dict[str, str]:
    """Types of the attached file a new UDT may use as members."""
    p = SESSION.project
    if not p:
        return {}
    out = {n: ("STRING" if (d.family or "") == "StringFamily" else "UDT") for n, d in p.datatypes.items()}
    out.update({n: "AOI" for n in p.aois})
    return out


def from_text(text: str, s: dict) -> dict:
    """UDT mode: the UDT text form directly, or plain English through the model."""
    if UDT_TEXT.match(text):
        try:
            return created(parse_spec(text), s, source="UDT text")
        except UdtError as e:
            return {"kind": "error", "message": f"Not a valid UDT: {e}"}
    client = state.llm(s)
    try:
        r = generate(client, text, known=project_types())
    except LLMError as e:
        return {"kind": "error", "message": str(e), "hint": state.llm_hint(s, client)}
    attempts = [{"error": a["error"]} for a in r.attempts]
    if r.udts is None:
        return {"kind": "error", "message": f"The model could not produce a valid UDT: {r.error}",
                "hint": "Try rewording, or name the members and their types.", "attempts": attempts}
    out = created(r.udts, s, source="your description")
    if out["kind"] == "udt_created":
        out.update(attempts=attempts, model_seconds=r.seconds, **state.model_info(s, client))
        out["warnings"] = r.warnings + out["warnings"]
    return out


def created(udts, s: dict, source: str) -> dict:
    """New UDTs: checked, put in the best order, sized and written (one file, or a zip)."""
    known = project_types()
    problems = check(udts, known)
    if problems:
        return {"kind": "error", "message": f"{len(problems)} problem(s) in the UDTs from {source}:",
                "details": problems}
    known_sizes = SESSION.udt_analysis().sizes if SESSION.project else {}
    best, as_written = sizes(udts, known_sizes), sizes(udts, known_sizes, optimal=False)
    user = {u.name for u in udts} | set(known)
    p = SESSION.project
    out = {"kind": "udt_created", "source": source, "seconds": None, "udts": [],
           "warnings": [f"{u.name} already exists in {SESSION.filename}: importing replaces it"
                        for u in udts if p and u.name in p.datatypes]}
    for u in dependency_order(udts):
        out["udts"].append({
            "name": u.name, "description": u.description, "size": best[u.name], "size_as_written": as_written[u.name],
            "members": [{"name": m.name, "type": f"{m.datatype}[{m.dim}]" if m.dim else m.datatype,
                         "description": m.description} for m in ordered(u, user)]})
    files = {f"{u.name}.L5X": write_udt(u, udts, controller=s["controller"], revision=s["revision"],
                                        project_types=set(known)) for u in udts}
    if len(files) == 1:
        ((name, text),) = files.items()
        out.update(filename=name, l5x=text)
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, text in files.items():
                z.writestr(name, text.encode("utf-8"))
        out.update(filename="UDTs.zip", zip_b64=base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


def plan() -> dict:
    """What reordering would do to every UDT of the attached file."""
    if SESSION.raw is None:
        return {"kind": "error", "message": "'optimize' needs an attached L5X with UDTs. Use Attach first."}
    an = SESSION.udt_analysis()
    if not an.plans:
        return {"kind": "error", "message": f"{SESSION.filename} has no UDTs."}
    plans = [x.to_dict() for x in an.plans.values()]
    for x in plans:
        # tick only what pays: a reorder that saves nothing still moves offsets
        x["default"] = x["status"] == "reordered" and not x["risks"] and bool(x["saved"])
    plans.sort(key=lambda x: (x["status"] != "reordered", -(x["total_saved"] or x["saved"]), x["name"]))
    return {"kind": "udt_plan", "filename": SESSION.filename, "target": an.target, "full": an.full_program,
            "plans": plans}


def download(selected: list[str], output: str) -> tuple[bytes, str, str, list[str] | None]:
    """(content, file name, mimetype, notes) for the chosen UDTs. Raises ValueError with a message for the user."""
    an = SESSION.udt_analysis()
    chosen = {n for n in selected if n in an.plans and an.plans[n].status == "reordered"}
    if not chosen:
        raise ValueError("Select at least one UDT that changes.")
    stem = re.sub(r"\.l5x$", "", SESSION.filename or "Project", flags=re.I)
    if output == "program":
        if not an.full_program:
            raise ValueError("The whole-program file needs a controller export.")
        text, notes = full_program(an, chosen)
        return text.encode("utf-8"), file_name(stem), "application/xml", notes
    if output == "single" and len(chosen) == 1:
        (n,) = chosen
        return single_file(an, n, chosen).encode("utf-8"), file_name(n), "application/xml", None
    return zip_files(an, chosen), f"{stem[:28]}_UDTs_opt.zip", "application/zip", None
