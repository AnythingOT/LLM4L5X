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
from core.logicspec import SpecError, format_spec, format_statement, parse_spec
from core.validator import errors, validate
from lint import check_rungs

# lint findings on generated rungs that send the model back for another attempt:
# a timer or one-shot shared between rungs cannot work as written
RETRY_CODES = {"ERR014", "ERR015"}

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
Actions: ENERGIZE X (on while the condition is true; a coil); SET X (latch); RESET X (unlatch);
  CLEAR N; N := value; N := A + B (also - * /);
  COUNT_UP(C, 10); COUNT_DOWN(C, 10); RESET_ACC C;
  ON_DELAY_TIMER(T, 5s) (TON); OFF_DELAY_TIMER(T, 5s) (TOF);
  COPY(Source, Dest, 10) copies 10 array elements.
Rules:
  - Never mix AND and OR without parentheses: write (A AND B) OR C.
  - "keeps running until", "stays on until" = seal-in: X := (Start OR X) AND NOT Stop;
  - "turn on"/"energize" with other actions = ENERGIZE; "latch"/"keep it set" = SET; "unlatch" = RESET.
  - "turn on"/"switch on X if C" with no other action = X := C; SET only for "latch"/"keep on"/"stays on".
  - The words decide the instruction, never the tag's name: "turn on Alarm_Latch" is ENERGIZE Alarm_Latch
    (or Alarm_Latch := C; when it is the only action), never SET.
  - "on-delay timer" = ON_DELAY_TIMER; "off-delay timer" = OFF_DELAY_TIMER. Match the words.
  - "either A or B, and C" = (A OR B) AND C: the part after ", and" still applies.
  - "subtract/divide/... and store the result in C" changes ONLY C: C := B - A; never B := ...
  - RISE(X) only when the request says so: "rising edge", "the moment", "each time", "once", "goes from off to on".
  - RISE covers only the signal whose edge is meant: "when A goes from off to on and B is on" = RISE(A) AND B;
    RISE(A AND B) would also fire when B turns on while A is already on.
  - "move A to B", "copy A into B", "store A in B" = B := A; (the destination is on the left).
  - Several actions under one condition: ONE IF with commas, IF c THEN a, b, c; (';' ends the IF).
  - COUNT_UP and COUNT_DOWN already count once per rising edge: do not wrap their condition in RISE.
  - "reset the counter/timer C" = RESET_ACC C.
  - Copy tag names EXACTLY as written in the request (same spelling, case and underscores).
  - Times need units: 500ms, 5s, 2min, 1h."""

_WORD = re.compile(r"[A-Za-z]+|\d+")


def _words(text: str) -> set[str]:
    """Lower-case words; tag names are split on _ and camelCase."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return {w.lower() for w in _WORD.findall(text.replace("_", " ")) if len(w) > 1}


# ---------------------------------------------------------------- Ollama


class LLMError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(f"{url}: HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise LLMError(f"cannot reach {url} ({getattr(e, 'reason', e)})") from None


class _HTTPFailure(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _post_json(url: str, body: dict, timeout: float) -> dict:
    """POST JSON, return JSON. HTTP errors -> _HTTPFailure (the caller words them); no connection -> OSError."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _HTTPFailure(e.code, e.read().decode("utf-8", "replace")[:300]) from None


_UNREACHABLE = (urllib.error.URLError, TimeoutError, ConnectionError)
MAX_TOKENS = 400  # one LogicSpec answer; UDTs ask for more


BACKENDS = {
    "ollama": {"label": "Ollama", "url": "http://127.0.0.1:11434"},
    "llamacpp": {"label": "llama.cpp server (GGUF, grammar-constrained)", "url": "http://127.0.0.1:8080"},
    "openai": {"label": "OpenAI-compatible (LM Studio, Jan, vLLM...)", "url": "http://127.0.0.1:1234"},
}


@dataclass
class OllamaClient:
    model: str = "phi4-mini"
    url: str = "http://127.0.0.1:11434"
    timeout: float = 300.0  # CPU-only machines can be slow
    think: bool | None = None  # None = model default; False = ask thinking models not to think
    context: int = 16384  # Ollama's own default (2048-4096) can cut a prompt with a project's tags
    supports_grammar = False  # Ollama only constrains to JSON schemas

    def list_models(self) -> list[str]:
        data = _get_json(f"{self.url.rstrip('/')}/api/tags")
        return sorted(m.get("name") or m.get("model") for m in data.get("models", []))

    def chat(self, messages: list[dict], grammar: str | None = None, max_tokens: int = MAX_TOKENS) -> str:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": self.context}}
        if self.think is not None:
            body["think"] = self.think
        try:
            data = _post_json(f"{self.url.rstrip('/')}/api/chat", body, self.timeout)
        except _HTTPFailure as e:
            if e.code == 404 and "not found" in e.detail:
                raise LLMError(f"Ollama has no model '{self.model}'. Run: ollama pull {self.model}") from None
            raise LLMError(f"Ollama error {e.code}: {e.detail}") from None
        except _UNREACHABLE as e:
            raise LLMError(f"Cannot reach Ollama at {self.url} ({e}). Is Ollama running?") from None
        return (data.get("message") or {}).get("content", "")


@dataclass
class OpenAICompatClient:
    """Any local server with the OpenAI chat API: llama.cpp's llama-server, LM Studio, Jan, vLLM.

    With grammar=True (llama-server) each request carries a GBNF grammar, so the
    reply is guaranteed to be valid LogicSpec over the allowed tags.
    """
    model: str = ""
    url: str = "http://127.0.0.1:8080"
    timeout: float = 300.0
    grammar: bool = False
    think: bool | None = None  # False: ask the chat template not to think (Qwen3 & co.)

    @property
    def supports_grammar(self) -> bool:
        return self.grammar

    def list_models(self) -> list[str]:
        data = _get_json(f"{self.url.rstrip('/')}/v1/models")
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    def chat(self, messages: list[dict], grammar: str | None = None, max_tokens: int = MAX_TOKENS) -> str:
        body = {"messages": messages, "temperature": 0, "max_tokens": max_tokens, "stream": False}
        if self.model:
            body["model"] = self.model
        if grammar and self.grammar:
            body["grammar"] = grammar
        if self.think is False:
            # Qwen-style templates: skip the <think> block in the prompt itself, so the
            # server does not have to force-close it (forced tokens and grammars clash)
            body["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            data = _post_json(f"{self.url.rstrip('/')}/v1/chat/completions", body, self.timeout)
        except _HTTPFailure as e:
            if grammar and e.code in (400, 500) and "grammar" in e.detail.lower():
                raise LLMError(f"the server rejected the grammar: {e.detail}") from None
            raise LLMError(f"server error {e.code}: {e.detail}") from None
        except _UNREACHABLE as e:
            raise LLMError(f"Cannot reach the model server at {self.url} ({e}). Is it running?") from None
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content", "") or ""


def make_client(backend: str = "ollama", url: str | None = None, model: str = "", think: bool | None = None,
                context: int = 16384):
    """context: tokens the model may see (Ollama only; llama.cpp fixes it with -c at server start)."""
    backend = backend if backend in BACKENDS else "ollama"
    url = url or BACKENDS[backend]["url"]
    if backend == "ollama":
        return OllamaClient(model=model or "phi4-mini", url=url, think=think, context=context)
    if backend == "llamacpp" and think is None:
        think = False  # the grammar allows no thinking text, and forced think tags break it
    return OpenAICompatClient(model=model, url=url, grammar=(backend == "llamacpp"), think=think)


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
    """LogicSpec statements from a model reply: drops thinking, fences and prose.

    A statement may span lines ("IF ... THEN" newline "X := Y;"), so lines are joined
    until the ';' that ends the statement.
    """
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S | re.I)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    keep: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        line = re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", line)  # list markers
        if not line:
            continue
        # "IF" in capitals only: "If you need..." is prose
        if not buf and not re.match(r"(IF\b|[A-Za-z_][\w.\[\]:]*\s*:=)", line):
            continue
        buf.append(line)
        if ";" in line:
            stmt = " ".join(buf)
            keep.append(stmt[: stmt.rindex(";") + 1])
            buf = []
    return "\n".join(keep)


# ---------------------------------------------------------------- generator


_TAGLIKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b|\b[A-Za-z]*[a-z][A-Z][A-Za-z0-9]*\b"
                      r"|\b[A-Z]{1,4}\d{2,}[A-Za-z0-9_]*\b")


def request_identifiers(request: str) -> set[str]:
    """Tag-like names written in the request: Pump_Run, FlowRate, PT101_PV."""
    from core.logicspec import KEYWORDS
    return {m for m in _TAGLIKE.findall(request) if m.upper() not in KEYWORDS}


_PLAIN = re.compile(r"(?<![\w.])[A-Z][A-Za-z0-9]*(?![\w(])")
_NOT_TAGS = {
    "A", "AN", "THE", "IF", "WHEN", "WHILE", "THEN", "ELSE", "OTHERWISE", "AND", "OR", "NOT", "EITHER",
    "BOTH", "IS", "ARE", "ON", "OFF", "TRUE", "FALSE", "TURN", "SWITCH", "SET", "RESET", "CLEAR", "STORE",
    "COPY", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "RUN", "START", "STOP", "COUNT", "LATCH",
    "UNLATCH", "ENERGIZE", "KEEP", "HOLD", "WAIT", "AFTER", "BEFORE", "FOR", "WITH", "TO", "IN", "AT", "OF",
}


def plain_names(request: str) -> set[str]:
    """Capitalised words that may be tag names although they do not look like one: Beacon, D.
    "A" counts only as a subject ("A is on"), since it is usually the article."""
    from core.logicspec import KEYWORDS
    out = set()
    for m in _PLAIN.finditer(request):
        w = m.group(0)
        if w == "A" and not re.match(r"\s+(is|are|was)\b", request[m.end():]):
            continue
        if w.upper() in KEYWORDS or (w.upper() in _NOT_TAGS and w != "A"):
            continue
        out.add(w)
    return out


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def spec_tags(spec: str) -> set[str]:
    """Base tag names used in LogicSpec text."""
    from core.logicspec import tokenize
    out = set()
    for t in tokenize(spec):
        if t.kind == "TAG":
            out.add(re.split(r"[.\[]", t.value)[0])
    return out


def snap_tags(spec: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Fix tag names that differ from an allowed name only in case or underscores
    (Press_Hi_Limit -> PressHiLimit, SPEED_REF -> Speed_Ref). Unambiguous matches only."""
    from core.logicspec import tokenize
    by_norm: dict[str, list[str]] = {}
    for a in allowed:
        by_norm.setdefault(_norm(a), []).append(a)
    fixes, out, last = [], [], 0
    for t in tokenize(spec):
        if t.kind != "TAG":
            continue
        base = re.split(r"[.\[]", t.value)[0]
        if base in allowed:
            continue
        cand = by_norm.get(_norm(base), [])
        if len(cand) == 1:
            out.append(spec[last:t.pos] + cand[0])
            last = t.pos + len(base)
            fixes.append(f"{base} -> {cand[0]}")
    out.append(spec[last:])
    return "".join(out), sorted(set(fixes))


@dataclass
class Attempt:
    reply: str  # raw model reply, kept for diagnosis
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

    def shown_examples(self, request: str) -> list[dict]:
        return pick_examples(request, self.examples, k=4)

    def messages(self, request: str, tags: list[tuple[str, str, str]]) -> list[dict]:
        system = SYSTEM_PROMPT
        if tags:
            listing = "\n".join(f"  {n} ({t})" + (f" - {d}" if d else "") for n, t, d in tags)
            system += ("\nExisting tags in this project. Use them whenever they match; "
                       f"invent a new short name only if none fits:\n{listing}")
        else:
            system += "\nInvent short, clear tag names like Pump_Run or Tank_Level (letters, digits, single _)."
        msgs = [{"role": "system", "content": system}]
        for ex in self.shown_examples(request):
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
        idents = request_identifiers(request)
        allowed = set(known_tags or {}) | idents
        # statements of the examples shown; a reply that repeats one copied the example
        example_stmts = set()
        for ex in self.shown_examples(request):
            try:
                example_stmts |= {format_statement(s) for s in parse_spec(ex["spec"])}
            except SpecError:
                pass
        grammar = None
        if getattr(self.client, "supports_grammar", False):
            from inputs.gbnf import build_gbnf
            types = dict(known_tags or {})
            # names the request writes but that do not look like tags (Beacon, A, D) must be writable too,
            # or the grammar forces the model onto some other existing tag
            types.update({i: "ANY" for i in idents | plain_names(request) if i not in types})
            grammar = build_gbnf(types, allow_new_tags=not allowed)
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            if grammar:
                try:
                    reply = self.client.chat(msgs, grammar=grammar)
                except LLMError as e:
                    if "rejected the grammar" not in str(e):
                        raise
                    res.warnings.append(f"grammar not accepted by the server, continuing without it: {e}")
                    grammar = None
                    reply = self.client.chat(msgs)
            else:
                reply = self.client.chat(msgs)
            spec = extract_spec(reply)
            error = None
            if not spec:
                error = "no LogicSpec statement found; reply with statements ending in ';' only"
            else:
                try:
                    if allowed:
                        spec, fixes = snap_tags(spec, allowed)
                        res.warnings += [f"tag name corrected: {f}" for f in fixes]
                    used = spec_tags(spec)
                    # an example repeated word for word is fine if it is about this request
                    # (same words in its tag names); otherwise the model copied an unrelated example
                    rw = _words(request)
                    copied = []
                    for st in parse_spec(spec):
                        text = format_statement(st)
                        if text in example_stmts:
                            tw = set().union(*(_words(t) for t in spec_tags(text))) or {""}
                            if len(tw & rw) / len(tw) < 0.5:
                                copied.append(text)
                    if copied:
                        raise SpecError(f"'{copied[0]}' is copied from the examples; "
                                        "write logic only for this request, using its tag names")
                    if allowed and not last:
                        # a name written in the request counts, even a plain word (Beacon) or a letter (D)
                        written = {u for u in used if re.search(rf"(?<![\w.]){re.escape(u)}(?![\w])", request)}
                        for u in sorted(used - allowed - written):
                            close = difflib.get_close_matches(u, sorted(allowed), n=1, cutoff=0.6)
                            if close:
                                raise SpecError(f"tag {u} is not in the request; did you mean {close[0]}? "
                                                "Use tag names exactly as written")
                    # every tag the request names is a condition or an output; one left out is usually a
                    # dropped interlock ("..., and Batch_Request is on"), which no other check would see
                    have = {_norm(u) for u in used}
                    missing = sorted(n for n in idents if _norm(n) not in have)
                    if missing and not last:
                        raise SpecError(f"the request names {', '.join(missing)} but the logic does not use "
                                        f"{'it' if len(missing) == 1 else 'them'}; every condition and "
                                        "output in the request must be in the logic")
                    if missing:
                        res.warnings.append(f"the request names {', '.join(missing)}, which the logic does not use")
                    stmts = parse_spec(spec)
                    for problem in output_problems(stmts, request, idents):
                        if not last:
                            raise SpecError(problem)
                        res.warnings.append(problem)
                    compiled = Compiler(known_tags=known_tags, catalog=catalog,
                                        **(compiler_kw or {})).compile(stmts)
                    types = dict(known_tags or {})
                    types.update({t.name: t.datatype for t in compiled.tags.values()})
                    bad = errors(validate(compiled.rungs, types if known_tags else None, catalog=catalog,
                                          revision=(compiler_kw or {}).get("revision"), string_types=string_types))
                    # logic that cannot work as written: worth another attempt (other lint findings are shown)
                    bad += [f for f in check_rungs(compiled.rungs, types, catalog) if f.code in RETRY_CODES]
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
            res.warnings += near_miss_warnings(res.compiled, known_tags, request)
        res.seconds = round(time.perf_counter() - t0, 2)
        return res


_LATCH_WORDS = re.compile(r"\b(latch\w*|set|sets|keep\w*|kept|stay\w*|remain\w*|hold\w*|seal\w*|until)\b",
                          re.IGNORECASE)


def _written(stmts) -> tuple[list[str], list[str]]:
    """(tags the logic writes, tags it latches and never unlatches), in order, each once."""
    from core import logicspec as ls
    out, latched, unlatched = [], [], set()
    for st in stmts:
        acts = [st.target] if isinstance(st, ls.Assign) else []
        if isinstance(st, ls.IfThen):
            for a in st.actions:
                acts.append(getattr(a, "dest", None) or getattr(a, "tag", None))
                if isinstance(a, ls.SetBit):
                    latched.append(a.tag)
                if isinstance(a, ls.ResetBit):
                    unlatched.add(a.tag)
        out += [t.split(".")[0].split("[")[0] for t in acts if t]
    return list(dict.fromkeys(out)), [t for t in dict.fromkeys(latched) if t not in unlatched]


def output_problems(stmts, request: str, idents: set[str]) -> list[str]:
    """Outputs the request did not ask for: checked in code because prompts did not stop them.

    * SET (latch) with no RESET of the same tag, when the request never says latch/set/keep/
      stay/until: "energize Fault_Latch" was latched in every run, pulled by the tag's name.
      ("open X when A, close it when B" is a SET/RESET pair and passes.)
    * A written tag the request does not name, when the request names its tags: a stray rung
      "Batch_Request := Box_CTR.DN" for "the batch is done". A tag made of the request's words
      ("run the pump" -> Pump_Run) is a fair pick from the project and passes."""
    written, latched = _written(stmts)
    problems = []
    if not _LATCH_WORDS.search(request):
        for t in latched:
            problems.append(f"the request does not ask to latch {t}: for 'turn on'/'energize' write "
                            f"{t} := condition; or ENERGIZE {t} (SET only for latch, keep or stay on)")
    if idents:
        said = {_norm(i) for i in idents}
        rw = _words(request)
        for t in written:
            if t.startswith(("L4X_", "REF_")) or _norm(t) in said:
                continue
            if re.search(rf"(?<![\w.]){re.escape(t)}(?!\w)", request):
                continue
            tw = _words(t)
            if tw and tw <= rw:
                continue
            problems.append(f"the logic writes {t}, which the request does not name; write only the "
                            "outputs the request asks for")
    return problems


def near_miss_warnings(compiled: CompileResult, known_tags: dict[str, str], request: str = "") -> list[str]:
    """A new tag that looks like an existing one is probably a typo by the model.

    A name the request writes exactly is the user's choice, not a typo (Cooker2_... next to Cooker1_...),
    so only the case clash is reported for it: Logix names ignore case."""
    out = []
    names = list(known_tags)
    lower = {n.lower(): n for n in names}
    for t in compiled.tags.values():
        if t.allocated:
            continue
        if t.name.lower() in lower:
            out.append(f"new tag {t.name} differs only in case from existing {lower[t.name.lower()]}")
            continue
        if re.search(rf"(?<![\w.]){re.escape(t.name)}(?!\w)", request):
            continue
        close = difflib.get_close_matches(t.name, names, n=2, cutoff=0.8)
        if close:
            out.append(f"new tag {t.name} will be created - did you mean {' or '.join(close)}?")
    return out
