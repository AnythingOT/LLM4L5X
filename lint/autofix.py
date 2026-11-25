"""Fix what the lint finds, where a fix is certain, and say plainly what each fix changes.

Two kinds of fix:

* **safe**: the program behaves exactly as before. A rung fix is safe only if the scan simulator runs
  the routine before and after the fix and sees no difference (core/rung_compare); a routine it cannot run
  makes the fix a "changes" one, with the reason. Deleting a tag is safe only if nothing outside the
  logic can reach it (External Access None, not produced or consumed).
* **changes**: the fix changes behaviour on purpose (it removes a fault or a hidden bug). Each one is
  offered on its own, with what changes.

Some findings are never fixed here: the right fix depends on intent (several latches, a timer used
twice, an empty branch leg, safety tags ...). docs/ROADMAP.md item 1 has the list.

The fixes edit the original L5X document in place: everything a fix does not touch is the same XML
afterwards (same canonical form: elements, attributes, text, CDATA). Only the layout inside start tags may
differ, where an export spread attributes over several lines. After the fixes the lint runs again, so a fix
that did not clear its finding shows up as still open.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from core.catalog import default_catalog
from core.rung import Branch, Instr, Rung, RungSyntaxError, Series, format_rung, is_literal, parse_rung, walk
from l5x.reader import MAX_L5X_BYTES, read_l5x

FIXABLE = ("WAR006", "ERR010", "INF001", "ERR015", "ERR012", "WAR008")


@dataclass
class Fix:
    code: str  # the lint rule it clears
    where: str  # "MainProgram / Main / Rung 3", "Controller:Old_Tag"
    what: str  # what the fix does
    safe: bool
    change: str = ""  # what behaves differently afterwards ("" for a safe fix)
    checked: str = ""  # how "safe" was established, or why it could not be
    needs: str = ""  # a value the fix needs from the user ("preset in ms"), asked before applying
    _apply: Callable[..., None] | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


@dataclass
class _RungSlot:
    owner: str  # program name or "AOI:<name>"
    routine: str
    element: object  # the <Rung> element
    rung: Rung | None  # parsed, None if the text does not parse
    text: str
    comment: str | None
    deleted: bool = False

    @property
    def where(self) -> str:
        return f"{self.owner} / {self.routine} / Rung {self.element.get('Number')}"


def _cdata_text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


class AutoFix:
    """Read an L5X, propose fixes, apply the chosen ones, write it back."""

    def __init__(self, data: bytes | str):
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > MAX_L5X_BYTES:
            raise ValueError("L5X file is above the size limit")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, strip_cdata=False)
        self.root = etree.fromstring(data, parser)
        if self.root.tag != "RSLogix5000Content":
            raise ValueError(f"not an L5X file (root element {self.root.tag})")
        self.original = data
        self.project = read_l5x(data)
        self.catalog = default_catalog()
        self.slots: dict[tuple[str, str], list[_RungSlot]] = {}
        ctrl = self.root.find("Controller")
        holders = [(p.get("Name"), p) for p in ctrl.findall("Programs/Program")] if ctrl is not None else []
        if ctrl is not None:
            holders += [(f"AOI:{a.get('Name')}", a)
                        for a in ctrl.findall("AddOnInstructionDefinitions/AddOnInstructionDefinition")]
        for owner, holder in holders:
            for rt in holder.findall("Routines/Routine"):
                slots = []
                for el in rt.findall("RLLContent/Rung"):
                    text = _cdata_text(el.find("Text"))
                    comment = _cdata_text(el.find("Comment")) or None
                    try:
                        rung = parse_rung(text, comment)
                    except RungSyntaxError:
                        rung = None
                    slots.append(_RungSlot(owner, rt.get("Name"), el, rung, text, comment))
                if slots:
                    self.slots[(owner, rt.get("Name"))] = slots

    # ------------------------------------------------------------------ proposals

    def findings(self, codes=FIXABLE) -> list:
        import lint
        return [f for f in lint.run(read_l5x(self.write())).findings if f.code in codes]

    def proposals(self) -> list[Fix]:
        found = {f.code for f in self.findings()}
        out: list[Fix] = []
        if "WAR006" in found:
            out += self._empty_rungs()
        if "ERR010" in found:
            out += self._duplicates()
        if "ERR012" in found:
            out += self._division_guards()
        if "ERR015" in found:
            out += self._oneshot_storage()
        if "INF001" in found:
            out += self._unused_tags()
        if "WAR008" in found:
            out += self._timer_presets()
        return out

    def apply(self, fixes: list[Fix], values: dict[int, str] | None = None) -> list[str]:
        """Apply fixes (values: index in `fixes` -> the value a fix needs). Returns what was done."""
        done = []
        for k, f in enumerate(fixes):
            if f.needs:
                v = (values or {}).get(k)
                if v is None:
                    continue
                f._apply(v)
            else:
                f._apply()
            done.append(f"{f.code} {f.where}: {f.what}")
        self._renumber()
        return done

    def write(self) -> bytes:
        body = etree.tostring(self.root, encoding="UTF-8", xml_declaration=False)
        return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body

    # ------------------------------------------------------------------ rung edits

    def _set_text(self, slot: _RungSlot, rung: Rung) -> None:
        text_el = slot.element.find("Text")
        text = format_rung(rung)
        text_el.text = etree.CDATA(text)
        slot.rung, slot.text = Rung(rung.body, slot.comment), text

    def _delete(self, slot: _RungSlot) -> None:
        slot.deleted = True

    def _renumber(self) -> None:
        for slots in self.slots.values():
            n = 0
            for s in slots:
                if s.deleted:
                    if s.element.getparent() is not None:
                        s.element.getparent().remove(s.element)
                    continue
                s.element.set("Number", str(n))
                n += 1
        for key in list(self.slots):
            self.slots[key] = [s for s in self.slots[key] if not s.deleted]

    def _same_behaviour(self, key, change: Callable[[list[Rung]], list[Rung]]) -> tuple[bool, str]:
        """Run the routine before and after `change` in the scan simulator."""
        from core.rung_compare import Side, compare
        slots = [s for s in self.slots[key] if not s.deleted]
        if any(s.rung is None for s in slots):
            return False, "not checked: a rung of this routine could not be read"
        before = [s.rung for s in slots]
        after = change(before)
        presets = {k: v for k, v in self.project.presets().items()}
        same, why = compare(Side(before, presets), Side(after, presets), catalog=self.catalog)
        if "not simulated" in why:
            return False, "not checked: the simulator does not run every instruction of this routine"
        return same, "same behaviour in the simulator" if same else f"the simulator sees a difference: {why}"

    def _rung_fix(self, code, slot, transform, what, change_text="") -> Fix:
        """transform(rung) -> new rung, or None to delete it. It runs on the rung as it is when the fix is
        applied, so two fixes on one rung both take effect."""
        key = (slot.owner, slot.routine)
        i = [s for s in self.slots[key] if not s.deleted].index(slot)

        def swap(rungs):
            out = list(rungs)
            new = transform(out[i])
            if new is None:
                del out[i]
            else:
                out[i] = new
            return out

        safe, checked = (False, "") if change_text else self._same_behaviour(key, swap)
        if change_text:
            checked = "changes behaviour on purpose"
        elif not safe:
            change_text = "may change behaviour: " + checked.split(": ", 1)[-1]

        def apply_():
            new = transform(slot.rung)
            if new is None:
                self._delete(slot)
            else:
                self._set_text(slot, new)

        return Fix(code, slot.where, what, safe, change_text, checked, _apply=apply_)

    # WAR006: an empty rung, which Studio 5000 does not accept. Without a comment it goes; with one it is a
    # section heading, so it keeps its comment and gets a NOP(), the usual way to write a heading rung.
    def _empty_rungs(self) -> list[Fix]:
        out = []
        for slots in self.slots.values():
            for s in slots:
                if s.rung is None or any(True for _ in walk(s.rung.body)):
                    continue
                if s.comment:
                    out.append(self._rung_fix("WAR006", s, lambda r: Rung(Series((Instr("NOP"),)), r.comment),
                                              "Put a NOP() in the empty heading rung (its comment stays)"))
                else:
                    out.append(self._rung_fix("WAR006", s, lambda r: None, "Delete the empty rung (no comment on it)"))
        return out

    # ERR010: the same condition twice in series, or identical parallel legs of conditions only
    def _is_condition(self, i: Instr) -> bool:
        spec = self.catalog.get(i.name)
        return spec is not None and not spec.is_output

    def _dedupe(self, node):
        if isinstance(node, Series):
            items, seen = [], set()
            for it in node.items:
                it = self._dedupe(it)
                if isinstance(it, Instr) and it.args and self._is_condition(it):
                    k = (it.name.upper(), tuple(a.replace(" ", "") for a in it.args))
                    if k in seen:
                        continue
                    seen.add(k)
                items.append(it)
            return Series(tuple(items))
        if isinstance(node, Branch):
            legs, seen = [], set()
            for leg in node.legs:
                leg = self._dedupe(leg)
                pure = leg.items and all(isinstance(x, Instr) and self._is_condition(x) for x in leg.items)
                k = format_rung(leg)
                if pure and k in seen:
                    continue
                seen.add(k)
                legs.append(leg)
            return legs[0] if len(legs) == 1 else Branch(tuple(legs))
        return node

    def _deduped(self, r: Rung) -> Rung:
        body = self._dedupe(r.body)
        # a branch left with one leg is that leg, inline
        body = Series(tuple(x for it in body.items for x in (it.items if isinstance(it, Series) else (it,))))
        return Rung(body, r.comment)

    def _duplicates(self) -> list[Fix]:
        out = []
        for slots in self.slots.values():
            for s in slots:
                if s.rung is not None and format_rung(self._deduped(s.rung)) != format_rung(s.rung):
                    out.append(self._rung_fix("ERR010", s, self._deduped, "Remove the repeated condition"))
        return out

    # ERR012: DIV or MOD by a tag nothing compares with 0 in that rung -> NEQ(divisor,0) just before it
    @staticmethod
    def _guarded(r: Rung) -> tuple[Rung, list[str]]:
        """NEQ(divisor,0) just before each DIV/MOD by a tag that nothing in the rung compares already."""
        compared = {a.replace(" ", "") for i in walk(r.body)
                    if i.name.upper() in ("NEQ", "NE", "GRT", "GT", "LES", "LT", "LIM", "LIMIT") for a in i.args}
        divisors: list[str] = []

        def guard(node):
            if isinstance(node, Series):
                items = []
                for it in node.items:
                    if (isinstance(it, Instr) and it.name.upper() in ("DIV", "MOD") and len(it.args) > 1
                            and not is_literal(it.args[1]) and it.args[1].replace(" ", "") not in compared):
                        divisors.append(it.args[1])
                        items.append(Instr("NEQ", (it.args[1], "0")))
                    items.append(guard(it))
                return Series(tuple(items))
            if isinstance(node, Branch):
                return Branch(tuple(guard(leg) for leg in node.legs))
            return node

        return Rung(guard(r.body), r.comment), divisors

    def _division_guards(self) -> list[Fix]:
        out = []
        for slots in self.slots.values():
            for s in slots:
                if s.rung is None:
                    continue
                _, divisors = self._guarded(s.rung)
                if divisors:
                    names = ", ".join(sorted(set(divisors)))
                    out.append(self._rung_fix(
                        "ERR012", s, lambda r: self._guarded(r)[0], f"Skip the division when {names} is 0",
                        f"when {names} is 0 the division does not run and its destination keeps its last value; "
                        "before, the controller divided by zero (overflow and a result you cannot rely on)"))
        return out

    # ERR015: one storage bit shared by several one-shots -> each one-shot after the first gets its own
    def _oneshot_storage(self) -> list[Fix]:
        uses: dict[tuple[str, str], list[tuple[_RungSlot, int]]] = {}
        for slots in self.slots.values():
            for s in slots:
                if s.rung is None or s.owner.startswith("AOI:"):
                    continue  # an AOI's storage bits are its own local tags: left to the AOI's author
                seen: dict[str, int] = {}
                for i in walk(s.rung.body):
                    if i.name.upper() == "ONS" and i.args:
                        bit = i.args[0].replace(" ", "")
                        k = seen.get(bit, 0)
                        seen[bit] = k + 1
                        scope = s.owner if self._tag_element(bit.split(".")[0].split("[")[0], s.owner) is not None \
                            else "controller"
                        uses.setdefault((scope, bit), []).append((s, k))
        out = []
        taken = {t.lower() for t in self._all_tag_names()}
        for (scope, bit), places in uses.items():
            if len(places) < 2:
                continue
            news = []
            for k in range(2, len(places) + 1):
                name = re.sub(r"\W", "_", bit) + f"_{k}"
                while name.lower() in taken:
                    name += "x"
                taken.add(name.lower())
                news.append(name)

            def apply_(places=places, news=news, scope=scope, bit=bit):
                for (slot, k), new in zip(places[1:], news):
                    self._set_text(slot, Rung(_rename_ons(slot.rung.body, bit, k, new), slot.comment))
                    self._add_bool(new, scope, f"One-shot storage, split from {bit}")

            out.append(Fix("ERR015", places[0][0].where, f"Give each one-shot on {bit} its own storage bit "
                           f"({', '.join(news)})", False,
                           f"each one-shot now sees its own rising edge; before, the {len(places)} one-shots "
                           f"shared {bit}, so one could use up the edge of another",
                           "changes behaviour on purpose", _apply=apply_))
        return out

    # INF001: an unused tag. Safe to delete only if nothing outside the logic can reach it.
    def _unused_tags(self) -> list[Fix]:
        out = []
        for f in self.findings(("INF001",)):
            m = re.match(r"'([^']+)'", f.message)
            scope, _, name = f.location.partition(":")
            el = self._tag_element(name, None if scope == "Controller" else scope)
            if not m or el is None:
                continue
            access = (el.get("ExternalAccess") or "Read/Write").lower()
            hidden = access == "none" and el.get("TagType", "Base") in ("Base", "Alias")
            change = "" if hidden else (f"External Access is {el.get('ExternalAccess') or 'Read/Write'}: an HMI, "
                                        "SCADA or another controller may still read it, and would lose it")

            def apply_(el=el):
                el.getparent().remove(el)

            out.append(Fix("INF001", f.location, f"Delete the unused tag {name}", hidden, change,
                           "External Access None: nothing outside the logic can use it" if hidden
                           else "not used in the logic; use outside it is unknown", _apply=apply_))
        return out

    # WAR008: a timer whose preset is 0 and that no logic sets -> the preset the user gives, in the tag
    def _timer_presets(self) -> list[Fix]:
        out = []
        for f in self.findings(("WAR008",)):
            scope, _, name = f.location.partition(":")
            el = self._tag_element(name, None if scope == "Controller" else scope)
            if el is None or el.get("Dimensions"):
                continue  # arrays: one preset per element, not guessed here

            def apply_(value, el=el):
                pre = int(float(value))
                if pre <= 0:
                    raise ValueError("a preset must be above 0")
                self._set_preset(el, pre)

            unit = "ms" if el.get("DataType", "").upper() == "TIMER" else "counts"
            out.append(Fix("WAR008", f.location, f"Set the preset of {name}", False,
                           f"{name} now runs to its preset; before, preset 0 made it done at once",
                           "changes behaviour on purpose", needs=f"preset in {unit}", _apply=apply_))
        return out

    # ------------------------------------------------------------------ tags

    def _all_tag_names(self) -> list[str]:
        return [t.get("Name") for t in self.root.iter("Tag") if t.get("Name")]

    def _tags_holder(self, scope: str | None):
        ctrl = self.root.find("Controller")
        if scope in (None, "controller"):
            h = ctrl.find("Tags")
            if h is None:
                h = etree.SubElement(ctrl, "Tags")
            return h
        prog = ctrl.find(f"Programs/Program[@Name='{scope}']")
        h = prog.find("Tags")
        if h is None:
            h = etree.Element("Tags")
            prog.insert(0, h)
        return h

    def _tag_element(self, name: str, program: str | None):
        holder = self._tags_holder(program)
        for t in holder.findall("Tag"):
            if t.get("Name") == name:
                return t
        return None

    def _add_bool(self, name: str, scope: str, description: str) -> None:
        from core.compiler import TagDef
        from l5x.writer import _tag_element
        _tag_element(self._tags_holder(scope), TagDef(name, "BOOL", description=description))

    def _set_preset(self, el, pre: int) -> None:
        for d in el.findall("Data"):
            if d.get("Format") == "L5K":
                parts = (d.text or "").strip().strip("[]").split(",")
                if len(parts) >= 3:
                    parts[1] = str(pre)
                    d.text = etree.CDATA("[" + ",".join(p.strip() for p in parts) + "]")
            elif d.get("Format") == "Decorated":
                for m in d.iter("DataValueMember"):
                    if m.get("Name") == "PRE":
                        m.set("Value", str(pre))


def _rename_ons(body: Series, bit: str, k: int, new: str) -> Series:
    """The k-th ONS (from 0, left to right) on storage `bit` gets storage `new`."""
    count = -1

    def swap(node):
        nonlocal count
        if isinstance(node, Instr):
            if node.name.upper() == "ONS" and node.args and node.args[0].replace(" ", "") == bit:
                count += 1
                if count == k:
                    return Instr(node.name, (new,) + node.args[1:])
            return node
        if isinstance(node, Series):
            return Series(tuple(swap(x) for x in node.items))
        return Branch(tuple(swap(x) for x in node.legs))

    return swap(body)


def fix_file(data: bytes, choose: Callable[[Fix], bool | str], safe_all: bool = False) -> tuple[bytes, list[str], list]:
    """Propose, ask `choose` per fix (True/False, or a value for a fix that needs one), apply, re-lint.

    safe_all: apply every safe fix without asking. Returns (new L5X, what was done, findings still open).
    """
    af = AutoFix(data)
    fixes = af.proposals()
    chosen, values = [], {}
    for f in fixes:
        if f.safe and safe_all:
            chosen.append(f)
            continue
        answer = choose(f)
        if answer is True or (isinstance(answer, str) and f.needs and answer.strip()):
            if f.needs:
                values[len(chosen)] = answer
            chosen.append(f)
    done = af.apply(chosen, values)
    return af.write(), done, af.findings()
