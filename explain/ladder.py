"""Draw a rung as a ladder diagram (SVG), the way Logix Designer lays it out:
left and right power rails, contacts and coils as symbols, every other instruction as a box
with its operands, branches as parallel legs, outputs pushed to the right rail.

Colours come from CSS classes (lad-*), so the drawing follows the page's light/dark theme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from core.catalog import Catalog, default_catalog
from core.rung import Branch, Instr, Rung, Series

CHAR = 7.2  # width of one 12px monospace character
WIRE = 34  # wire height inside a cell, from its top
GAP = 14  # vertical gap between branch legs
PAD = 14  # space around a branch's vertical bars
RAIL = 6  # margin outside the rails
MIN_WIDTH = 560
LABEL_MAX = 24  # characters of a tag shown above a contact or coil
_CONTACTS = {"XIC": "", "XIO": "/"}
_COILS = {"OTE": "", "OTL": "L", "OTU": "U", "RES": "RES"}  # RES is a coil in Studio 5000: -(RES)-


@dataclass
class Box:
    """A laid-out element: size, and SVG fragments relative to its top-left corner."""
    w: float
    h: float
    parts: list[str] = field(default_factory=list)


def _fit(text: str, limit: int = LABEL_MAX) -> str:
    """Too long: cut in the middle, so the end that tells tags apart survives (..._LF vs ..._LR)."""
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    return text[:head] + "…" + text[len(text) - (limit - 1 - head):]


def _text(x, y, s, cls="lad-tag", anchor="middle", title=None, live=None) -> str:
    t = f"<title>{escape(title)}</title>" if title else ""
    v = f' data-live="{escape(live, quote=True)}"' if live else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}"{v}>{t}{escape(s)}</text>'


def _line(x1, y1, x2, y2, cls="lad-wire", at: str | None = None) -> str:
    """at: which power this wire carries, for a live page: "<path>:in" or "<path>:out" of an element (its
    path as the simulator's trace names it), or "rail" for the left rail's power."""
    p = f' data-p="{at}"' if at is not None else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}"{p}/>'


def _shift(parts: list[str], dx: float, dy: float) -> str:
    return f'<g transform="translate({dx:.1f},{dy:.1f})">{"".join(parts)}</g>'


class _Layout:
    def __init__(self, catalog: Catalog, presets: dict[str, int] | None = None):
        self.cat = catalog
        self.presets = presets or {}

    def series(self, s: Series, prefix: str = "", offset: int = 0, empty_at: str | None = None) -> Box:
        x, h, parts = 0.0, WIRE + 16, []
        for k, e in enumerate(s.items):
            here = f"{prefix}{k + offset}"
            b = self.branch(e, here) if isinstance(e, Branch) else self.instr(e, here)
            parts.append(_shift(b.parts, x, 0))
            x += b.w
            h = max(h, b.h)
        if not s.items:  # an empty leg is a plain wire: it carries what reaches the branch
            parts.append(_line(0, WIRE, 40, WIRE, at=empty_at))
            x = 40
        return Box(x, h, parts)

    def branch(self, b: Branch, path: str = "") -> Box:
        legs = [self.series(leg, f"{path}.{j}.", empty_at=f"{path}:in") for j, leg in enumerate(b.legs)]
        ends = [f"{path}.{j}.{len(leg.items) - 1}:out" if leg.items else f"{path}:in"
                for j, leg in enumerate(b.legs)]
        inner = max(leg.w for leg in legs)
        w = inner + 2 * PAD
        y, parts, wires = 0.0, [], []
        for leg, end in zip(legs, ends):
            parts.append(_shift(leg.parts, PAD, y))
            wires.append(y + WIRE)
            parts.append(_line(0, y + WIRE, PAD, y + WIRE, at=f"{path}:in"))
            parts.append(_line(PAD + leg.w, y + WIRE, w, y + WIRE, at=end))  # short legs run on to the bar
            y += leg.h + GAP
        parts.append(_line(0, wires[0], 0, wires[-1], "lad-bar", at=f"{path}:in"))
        parts.append(_line(w, wires[0], w, wires[-1], "lad-bar", at=f"{path}:out"))
        return Box(w, y - GAP, parts)

    def instr(self, i: Instr, path: str = "") -> Box:
        name = i.name.upper()
        if name in _CONTACTS or name in _COILS:
            return self._symbol(i, name, path)
        return self._box(i, path)

    def _symbol(self, i: Instr, name: str, path: str = "") -> Box:
        tag = i.args[0] if i.args else "?"
        label = _fit(tag)
        w = max(76, len(label) * CHAR + 16)
        c, parts = w / 2, []
        parts.append(_text(c, WIRE - 16, label, title=tag if label != tag else None))
        if name in _CONTACTS:
            parts += [_line(0, WIRE, c - 7, WIRE, at=f"{path}:in"), _line(c + 7, WIRE, w, WIRE, at=f"{path}:out"),
                      _line(c - 7, WIRE - 10, c - 7, WIRE + 10, "lad-sym"),
                      _line(c + 7, WIRE - 10, c + 7, WIRE + 10, "lad-sym")]
            if _CONTACTS[name]:
                parts.append(_line(c - 9, WIRE + 9, c + 9, WIRE - 9, "lad-sym"))
        else:
            mark = _COILS[name]
            hw = 6 if len(mark) <= 1 else len(mark) * CHAR / 2 + 5  # brackets wide enough for the mark
            # the space between the brackets, filled when the coil is on (a live page), as Logix Designer online
            # shows it: "on" is then more than the colour of a line
            parts.insert(0, f'<rect x="{c - hw + 1:.1f}" y="{WIRE - 8}" width="{2 * hw - 2:.1f}" height="16" '
                            'rx="2" class="lad-glow"/>')
            parts += [_line(0, WIRE, c - hw - 5, WIRE, at=f"{path}:in"), _line(c + hw + 5, WIRE, w, WIRE, at=f"{path}:out"),
                      f'<path d="M{c - hw:.1f},{WIRE - 10} q-6,10 0,20 M{c + hw:.1f},{WIRE - 10} q6,10 0,20" class="lad-sym"/>']
            if mark:
                parts.append(_text(c, WIRE + 4, _COILS[name], "lad-mark"))
        # the tag and kind let a live page (Energize) light the symbol: a contact that passes power, a coil that is on
        group = f'<g class="lad-el" data-kind="{name}" data-tag="{escape(tag, quote=True)}">{"".join(parts)}</g>'
        return Box(w, WIRE + 16, [group])

    def _box(self, i: Instr, path: str = "") -> Box:
        spec = self.cat.get(i.name)
        names = [o.name for o in spec.operands] if spec else []
        rows = []
        for k, arg in enumerate(i.args):
            label = names[k] if k < len(names) else ""
            shown = arg or "?"
            # exports write TON(T,?,?): the preset lives in the tag's data, so show it from there
            if shown == "?" and label == "preset" and i.args and i.args[0] in self.presets:
                shown = str(self.presets[i.args[0]])
            rows.append((label.replace("_", " ").capitalize(), _fit(shown, 28), arg))
        lw = max((len(r[0]) for r in rows), default=0) * CHAR
        vw = max((len(r[1]) for r in rows), default=0) * CHAR
        bw = max(len(i.name) * CHAR + 24, lw + vw + 26, 70)
        bh = 22 + 17 * len(rows) + 6
        top, lead = WIRE - 11, 12
        parts = [_line(0, WIRE, lead, WIRE, at=f"{path}:in"), _line(lead + bw, WIRE, 2 * lead + bw, WIRE, at=f"{path}:out"),
                 f'<rect x="{lead}" y="{top}" width="{bw:.1f}" height="{bh}" rx="3" class="lad-box"/>',
                 _text(lead + bw / 2, top + 15, i.name, "lad-op")]
        for k, (label, value, full) in enumerate(rows):
            y = top + 22 + 17 * k + 12
            parts.append(_text(lead + 8, y, label, "lad-arg-name", "start"))
            # an accumulator ("Accum ?") shows its live value on a live page
            live = f"{i.args[0]}.ACC" if label == "Accum" and i.args else None
            parts.append(_text(lead + bw - 8, y, value, "lad-arg", "end", title=full if value != full else None,
                               live=live))
        return Box(bw + 2 * lead, top + bh + 10, parts)


def _is_output(e, cat: Catalog) -> bool:
    if isinstance(e, Branch):
        return all(leg.items and all(_is_output(x, cat) for x in leg.items) for leg in e.legs)
    spec = cat.get(e.name)
    return spec is None or spec.is_output


def to_svg(rung: Rung, catalog: Catalog | None = None, number: int | None = None,
           presets: dict[str, int] | None = None) -> str:
    """One rung as a standalone <svg> element. `presets` (tag -> PRE) fills a '?' preset."""
    cat = catalog or default_catalog()
    items = list(rung.body.items)
    split = len(items)
    while split > 0 and _is_output(items[split - 1], cat):
        split -= 1
    lay = _Layout(cat, presets)
    cond = lay.series(Series(tuple(items[:split])))
    outs = lay.series(Series(tuple(items[split:])), offset=split)  # paths as in the whole rung
    if not items[:split]:
        cond = Box(0, WIRE + 16, [])
    if not items[split:]:
        outs = Box(0, WIRE + 16, [])
    left = RAIL + (28 if number is not None else 0)
    body = max(MIN_WIDTH, cond.w + outs.w + 40)
    width, height = left + body + RAIL, max(cond.h, outs.h) + 10
    right = left + body
    parts = [
        _shift(cond.parts, left, 4),
        _line(left + cond.w, WIRE + 4, right - outs.w, WIRE + 4, at=f"{split - 1}:out" if split else "rail"),
        _shift(outs.parts, right - outs.w, 4),
        # the rails last: drawn on top, so the end of a wire never shows over the supply rail
        _line(left, 4, left, height - 4, "lad-rail lad-left"),  # left: the power supply
        _line(right, 4, right, height - 4, "lad-rail lad-right"),
    ]
    if number is not None:
        parts.append(_text(RAIL + 10, WIRE + 8, str(number), "lad-num"))
    return (f'<svg class="ladder" xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Ladder diagram of the rung">'
            + "".join(parts) + "</svg>")
