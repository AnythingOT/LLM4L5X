"""Plain English -> LogicSpec with a local model through Ollama.

The model only writes LogicSpec. Everything after that is checked code:
parse, compile, validate. When a check fails, the exact error goes back to
the model for another try. Nothing the model writes reaches an L5X unchecked.

    gen = Generator(OllamaClient(model="phi4-mini"))
    result = gen.generate("start the pump with start, stop with stop", known_tags={...})
"""

from __future__ import annotations

import difflib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.catalog import Catalog
from core.compiler import CompileError, CompileResult, Compiler
from core.logicspec import SpecError, format_spec, parse_spec
from core.validator import errors, validate

EXAMPLES_FILE = Path(__file__).parent / "examples.yaml"

SYSTEM_PROMPT = """You turn plain-English PLC control descriptions into LogicSpec.
Reply with LogicSpec statements only, each ending with ';'. No explanations, no code fences.

LogicSpec:
  X := condition;                      X is on while the condition is true
  IF condition THEN action, action;    do the actions while the condition is true
  IF TRUE THEN action;                 always
Conditions: Tag, NOT Tag, AND, OR, comparisons (= <> > < >= <=),
  RISE(condition) = only at the moment it becomes true,
  DELAY(condition, 5s) = condition has been true for 5 s,
  OFFDELAY(condition, 5s) = condition is true or went false less than 5 s ago.
Actions: SET X; RESET X; CLEAR N; N := value; N := A + B (also - * /);
  COUNT_UP(C, 10); COUNT_DOWN(C, 10); RESET_ACC C; START_TIMER(T, 5s);
  COPY(Source, Dest, 10) copies 10 array elements.
Rules:
  - Never mix AND and OR without parentheses: write (A AND B) OR C.
  - "keeps running until", "stays on until" = seal-in: X := (Start OR X) AND NOT Stop;
  - "latch"/"set" = SET, "unlatch"/"reset"/"clear a bit" = RESET.
  - Times need units: 500ms, 5s, 2min, 1h."""

_WORD = re.compile(r"[A-Za-z]+|\d+")


def _words(text: str) -> set[str]:
    """Lower-case words; tag names are split on _ and camelCase."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return {w.lower() for w in _WORD.findall(text.replace("_", " ")) if len(w) > 1}


# ---------------------------------------------------------------- Ollama


class LLMError(RuntimeError):
    pass


@dataclass
class OllamaClient:
    model: str = "phi4-mini"
    url: str = "http://127.0.0.1:11434"
    timeout: float = 300.0  # CPU-only machines can be slow
    think: bool | None = None  # None = model default; False = ask thinking models not to think

    def chat(self, messages: list[dict]) -> str:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0, "num_predict": 400}}
        if self.think is not None:
            body["think"] = self.think
        req = urllib.request.Request(f"{self.url.rstrip('/')}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 404 and "not found" in detail:
                raise LLMError(f"Ollama has no model '{self.model}'. Run: ollama pull {self.model}") from None
            raise LLMError(f"Ollama error {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMError(f"Cannot reach Ollama at {self.url} ({e}). Is Ollama running?") from None
        return (data.get("message") or {}).get("content", "")


# ---------------------------------------------------------------- prompt pieces


def load_examples(path: Path = EXAMPLES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text("utf-8")) or []


def pick_examples(request: str, examples: list[dict], k: int = 5) -> list[dict]:
    """Most similar examples by word overlap; always at least the first (basic) one."""
    rw = _words(request)
    scored = sorted(examples, key=lambda e: -len(rw & _words(e["english"])))
    chosen = scored[:k]
    if examples and examples[0] not in chosen:
        chosen[-1] = examples[0]
    return chosen


def pick_tags(request: str, tags: dict[str, str], descriptions: dict[str, str] | None = None,
              k: int = 30) -> list[tuple[str, str, str]]:
    """Project tags most related to the request: (name, type, description)."""
    descriptions = descriptions or {}
    rw = _words(request)
    lower = request.lower()
    scored = []
    for name, dtype in tags.items():
        if dtype in ("ALIAS", "") or ":" in name:
            continue
        tw = _words(name) | _words(descriptions.get(name, ""))
        score = 3 * len(rw & _words(name)) + len(rw & tw)
        if name.lower() in lower:
            score += 10
        if score:
            scored.append((score, name, dtype))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(n, t, descriptions.get(n, "")) for _, n, t in scored[:k]]


def extract_spec(reply: str) -> str:
    """LogicSpec statements from a model reply: drops thinking, fences and prose."""
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S | re.I)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    keep = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        line = re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", line)  # list markers
        if re.match(r"(IF\b|[A-Za-z_][\w.\[\]:]*\s*:=)", line, flags=re.I) and ";" in line:
            keep.append(line[: line.rindex(";") + 1])
    return "\n".join(keep)


# ---------------------------------------------------------------- generator


@dataclass
class Attempt:
    reply: str
    spec: str
    error: str | None


@dataclass
class Result:
    request: str
    spec: str | None  # final, compiled LogicSpec
    compiled: CompileResult | None
    attempts: list[Attempt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None


class Generator:
    def __init__(self, client, examples: list[dict] | None = None, retries: int = 2):
        self.client = client
        self.examples = load_examples() if examples is None else examples
        self.retries = retries

    def messages(self, request: str, tags: list[tuple[str, str, str]]) -> list[dict]:
        system = SYSTEM_PROMPT
        if tags:
            listing = "\n".join(f"  {n} ({t})" + (f" - {d}" if d else "") for n, t, d in tags)
            system += ("\nExisting tags in this project. Use them whenever they match; "
                       f"invent a new short name only if none fits:\n{listing}")
        else:
            system += "\nInvent short, clear tag names like Pump_Run or Tank_Level (letters, digits, single _)."
        msgs = [{"role": "system", "content": system}]
        for ex in pick_examples(request, self.examples):
            msgs += [{"role": "user", "content": ex["english"]},
                     {"role": "assistant", "content": ex["spec"]}]
        msgs.append({"role": "user", "content": request})
        return msgs

    def generate(self, request: str, known_tags: dict[str, str] | None = None,
                 descriptions: dict[str, str] | None = None, catalog: Catalog | None = None,
                 compiler_kw: dict | None = None, string_types: set[str] | None = None) -> Result:
        t0 = time.perf_counter()
        res = Result(request, None, None)
        tags = pick_tags(request, known_tags or {}, descriptions)
        msgs = self.messages(request, tags)
        for _ in range(self.retries + 1):
            reply = self.client.chat(msgs)
            spec = extract_spec(reply)
            error = None
            if not spec:
                error = "no LogicSpec statement found; reply with statements ending in ';' only"
            else:
                try:
                    stmts = parse_spec(spec)
                    compiled = Compiler(known_tags=known_tags, catalog=catalog,
                                        **(compiler_kw or {})).compile(stmts)
                    types = dict(known_tags or {})
                    types.update({t.name: t.datatype for t in compiled.tags.values()})
                    bad = errors(validate(compiled.rungs, types if known_tags else None, catalog=catalog,
                                          revision=(compiler_kw or {}).get("revision"), string_types=string_types))
                    if bad:
                        error = "; ".join(i.message for i in bad[:3])
                    else:
                        res.spec, res.compiled = format_spec(stmts), compiled
                except (SpecError, CompileError) as e:
                    error = str(e).replace("\n", " ")
            res.attempts.append(Attempt(reply, spec, error))
            if error is None:
                break
            msgs = msgs + [{"role": "assistant", "content": reply},
                           {"role": "user", "content": f"That LogicSpec has an error: {error}\n"
                                                       "Reply with the corrected LogicSpec only."}]
        else:
            res.error = f"no valid LogicSpec after {len(res.attempts)} attempts: {res.attempts[-1].error}"
        if res.compiled and known_tags:
            res.warnings += near_miss_warnings(res.compiled, known_tags)
        res.seconds = round(time.perf_counter() - t0, 2)
        return res


def near_miss_warnings(compiled: CompileResult, known_tags: dict[str, str]) -> list[str]:
    """A new tag that looks like an existing one is probably a typo by the model."""
    out = []
    names = list(known_tags)
    lower = {n.lower(): n for n in names}
    for t in compiled.tags.values():
        if t.allocated:
            continue
        if t.name.lower() in lower:
            out.append(f"new tag {t.name} differs only in case from existing {lower[t.name.lower()]}")
            continue
        close = difflib.get_close_matches(t.name, names, n=2, cutoff=0.8)
        if close:
            out.append(f"new tag {t.name} will be created - did you mean {' or '.join(close)}?")
    return out
