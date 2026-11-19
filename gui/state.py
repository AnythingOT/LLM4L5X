"""What the GUI remembers between requests, and the settings sent with each request.

Single-user local tool: the attached file lives in memory and is forgotten when the server stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lint
from inputs.llm import BACKENDS, make_client
from l5x.reader import Project
from l5x.xref import cross_reference


@dataclass
class Session:
    project: Project | None = None
    filename: str | None = None
    raw: bytes | None = None
    _cache: dict = field(default_factory=dict)  # derived from the attached file, dropped on attach/detach

    def attach(self, project: Project, filename: str, raw: bytes) -> None:
        self.project, self.filename, self.raw = project, filename, raw
        self._cache.clear()

    def detach(self) -> None:
        self.attach(None, None, None)

    def udt_analysis(self):
        """Layout analysis of the attached file's UDTs (computed once per file)."""
        from udt.optimize import analyse
        if "udt" not in self._cache:
            self._cache["udt"] = analyse(self.raw)
        return self._cache["udt"]

    def xref(self) -> dict:
        if "xref" not in self._cache:
            self._cache["xref"] = cross_reference(self.project)
        return self._cache["xref"]


SESSION = Session()

DEFAULTS = {
    "output": "routine",        # routine (Routine.L5X) | rungs (Rung.L5X)
    "routine": "GeneratedRoutine",
    "program": "MainProgram",
    "controller": "LLM4L5X",
    "revision": "32.04",
    "scope": "controller",      # controller | program
    "display": "placeholder",   # placeholder | values
    "comments": True,
    "prefix": "L4X",
    "backend": "ollama",        # ollama | llamacpp | openai
    "llm_url": "",              # empty = the backend's usual local address
    "model": "phi4-mini",
    "think": "default",         # default | off
    "context": 16384,           # tokens the model sees (Ollama); llama.cpp: -c at server start
    "rung_format": "neutral",   # neutral | ascii: how rungs are shown and copied
    "disabled_rules": [],       # lint rule codes switched off on the Rules page
}

_CHOICES = {
    "output": ("routine", "rungs"),
    "scope": ("controller", "program"),
    "display": ("placeholder", "values"),
    "think": ("default", "off"),
    "backend": tuple(BACKENDS),
    "rung_format": ("neutral", "ascii"),
}


def settings(raw: dict | None) -> dict:
    """The request's settings over the defaults; anything unknown or out of range falls back."""
    raw = raw or {}
    s = dict(DEFAULTS)
    s.update({k: v for k, v in raw.items() if k in s and v not in (None, "")})
    for k, allowed in _CHOICES.items():
        if s[k] not in allowed:
            s[k] = DEFAULTS[k]
    s["comments"] = bool(s["comments"])
    try:
        s["context"] = min(max(int(s["context"]), 2048), 262144)
    except (TypeError, ValueError):
        s["context"] = DEFAULTS["context"]
    rules = raw.get("disabled_rules")
    s["disabled_rules"] = sorted({str(c).upper() for c in rules if str(c).upper() in lint.BY_CODE}) \
        if isinstance(rules, list) else []
    if not s["llm_url"] and raw.get("ollama") and s["backend"] == "ollama":
        s["llm_url"] = raw["ollama"]  # settings saved by the first version
    return s


def llm(s: dict):
    """The model client the settings describe (tests replace this)."""
    return make_client(s["backend"], s["llm_url"] or None, s["model"], think=False if s["think"] == "off" else None,
                       context=s["context"])


def model_info(s: dict, client) -> dict:
    """What the GUI shows about the model that answered."""
    return {"model": s["model"] or s["backend"], "backend": BACKENDS[s["backend"]]["label"],
            "grammar": bool(getattr(client, "supports_grammar", False))}


def llm_hint(s: dict, client) -> str:
    return f"{BACKENDS[s['backend']]['label']}, model '{s['model'] or 'default'}' at {client.url} (change in ⚙️ Settings)."
