"""Output checks that send the model back: unrequested latches, OR-splits, stray RISE, unnamed outputs."""

from __future__ import annotations

import difflib
import re


from core.compiler import CompileResult
from .names import _norm, _words


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
                if isinstance(a, ls.Math) and a.op is None and a.a in ("0", "1"):
                    # "IF c THEN X := 1;" compiles to MOVE(1,X): it holds like SET until a move of 0
                    if a.a == "1" and st.cond is not None:
                        latched.append(a.dest)
                    else:
                        unlatched.add(a.dest)
        out += [t.split(".")[0].split("[")[0] for t in acts if t]
    return list(dict.fromkeys(out)), [t for t in dict.fromkeys(latched) if t not in unlatched]


_EDGE_WORDS = re.compile(r"\b(rising|edge|moment|each time|every time|once|one[- ]shot|pulse|from off to on|"
                         r"turns on|turns off|goes (?:on|off|true|false|high|low)|becomes (?:true|on|active)|"
                         # events are instants: "when the batch starts", "at the start of each shift"
                         r"starts|start of|begins|beginning of|ends|end of|finishes)\b", re.IGNORECASE)


def _clauses(request: str, names) -> list[tuple[str, set[str]]]:
    """(clause text with tag names blanked, tags it names). Blanking keeps "Latch_Cmd" from reading as "latch"."""
    out = []
    for c in re.split(r"[,;.:]|\band\b|\bthen\b", request):
        named = {n for n in names if re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)", c)}
        for n in sorted(named, key=len, reverse=True):
            c = re.sub(rf"(?<![\w.]){re.escape(n)}(?!\w)", " ", c)
        out.append((c, named))
    return out


def _asks_latch(tag: str, request: str, names) -> bool:
    """A latch word in the tag's own clause ("latch Divert_Gate"), or in a clause naming no tag
    ("... and it stays on until reset"). "latch Divert_Gate, turn on Motor_Run" asks it of one tag only."""
    for text, named in _clauses(request, set(names) | {tag}):
        if _LATCH_WORDS.search(text) and (tag in named or not named):
            return True
    return False


def _rises(e) -> bool:
    from core import logicspec as ls
    if isinstance(e, ls.Rise):
        return True
    return any(_rises(v) for v in getattr(e, "__dict__", {}).values()
               if v is not None and not isinstance(v, (str, int, float, bool)))


def output_problems(stmts, request: str, idents: set[str]) -> list[str]:
    """Outputs the request did not ask for: checked in code because prompts did not stop them.

    * SET (latch), or "IF c THEN X := 1;" (MOVE 1, which holds the same way), with no RESET or
      move of 0 to the same tag, when the request never says latch/set/keep/stay/until: "energize Fault_Latch" was latched in every run, pulled by the tag's name.
      ("open X when A, close it when B" is a SET/RESET pair and passes.)
      The latch word must belong to that tag: "latch Divert_Gate and turn on Motor_Run" latches one.
    * One tag turned on by two statements, when the request names it once: "latch X if (A or B),
      and C" came back as two SETs, which is A OR B OR C.
    * RISE when the request has no edge word: a one-shot ran a timer for one scan.
    * A written tag the request does not name, when the request names its tags: a stray rung
      "Batch_Request := Box_CTR.DN" for "the batch is done". A tag made of the request's words
      ("run the pump" -> Pump_Run) is a fair pick from the project and passes."""
    from core import logicspec as ls
    written, latched = _written(stmts)
    problems = []
    if re.search(r"(?<![\w.])1(?![\w.])", request):
        latched = []  # "move 1 to Mode": the value is asked for, not a latch
    names = set(idents) | set(written)
    for t in latched:
        if not _asks_latch(t, request, names):
            problems.append(f"the request does not ask to latch {t}: for 'turn on'/'energize' write "
                            f"ENERGIZE {t} (or {t} := condition;), never SET or {t} := 1 (SET only for "
                            "latch, keep or stay on)")
    ons = {}  # (tag, kind) -> statements that turn it on
    for i, st in enumerate(stmts):
        acts = [(st.target, "assign")] if isinstance(st, ls.Assign) else []
        if isinstance(st, ls.IfThen):
            acts += [(a.tag, "set") for a in st.actions if isinstance(a, ls.SetBit)]
            acts += [(a.tag, "energize") for a in st.actions if isinstance(a, ls.Energize)]
        for key in acts:
            ons.setdefault(key, set()).add(i)
    for (t, _kind), where in ons.items():
        said = len(re.findall(rf"(?<![\w.]){re.escape(t)}(?!\w)", request))
        if len(where) > 1 and said <= 1:
            problems.append(f"{t} is turned on by {len(where)} separate statements, and separate statements "
                            f"act as OR (any one turns it on); the request gives one condition for {t}: "
                            f"write one IF whose condition has all of it (... AND ...)")
    if not _EDGE_WORDS.search(request) and any(
            _rises(st.expr if isinstance(st, ls.Assign) else st.cond) for st in stmts):
        problems.append("the request asks for no edge (no 'rising edge', 'the moment', 'each time', 'once'): "
                        "do not use RISE; the outputs must follow the condition every scan")
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
