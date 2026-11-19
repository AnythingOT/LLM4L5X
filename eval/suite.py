"""Instruction-coverage test suite: English requests with expected rungs.

Successor to the earlier ILinSeries generator, with four fixes:
  * single, series, PARALLEL, nested and multi-output rungs (not series only)
  * scored by behaviour (eval/rung_compare.py), not string EXACT
  * realistic tag names and whole requirements, not "check if var12 = var7"
  * Studio 5000 export format: TON(T,?,?) with preset in tag data, ONS with
    its own storage bit, v35 or v36 mnemonics

Expected rungs are built here by a small reference builder that does not use
the LogicSpec compiler, so `--self-test` checks the compiler against an
independent implementation instead of against itself.

Instruction set (as in the earlier training matrix): XIC XIO OTE OTL OTU ONS
EQ NE GT LT GE LE ADD SUB MUL DIV MOVE COP CLR TON TOF CTU CTD, plus RES.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from core.rung import Branch, Instr, Rung, Series, format_rung

INSTRUCTIONS = ["XIC", "XIO", "OTE", "OTL", "OTU", "ONS", "EQ", "NE", "GT", "LT", "GE", "LE",
                "ADD", "SUB", "MUL", "DIV", "MOVE", "COP", "CLR", "TON", "TOF", "CTU", "CTD", "RES"]
STRUCTURES = ["single", "series", "parallel", "nested", "multi_output"]

BOOL_IN = ["Start_PB", "Stop_PB", "Reset_PB", "Auto_Mode", "Manual_Mode", "Guard_Closed", "EStop_OK",
           "Door_Open", "Pump_Fault", "Motor_Overload", "Level_High_LS", "Level_Low_LS", "Flow_Switch",
           "Valve_Open_LS", "Part_Present", "Jam_Sensor", "Heat_Request", "Cycle_Start", "Box_Eye",
           "Air_Pressure_OK", "Remote_Enable", "Batch_Request"]
BOOL_OUT = ["Pump_Run", "Motor_Run", "Alarm_Horn", "Fill_Valve", "Ready_Light", "Fault_Latch",
            "Conveyor_Run", "Agitator_Run", "Drain_Valve", "Beacon", "Heater_On", "Batch_Done",
            "Interlock_OK", "Cooling_Fan", "Vent_Valve", "Siren", "Stack_Light_Red", "Stack_Light_Green",
            "Feed_Motor", "Mixer_Run", "Steam_Valve", "Reject_Gate", "Cycle_Done", "Low_Level_Alarm"]
NUM_REAL = ["PressurePV", "PressureSP", "PressHiLimit", "Tank_Level", "Level_SP", "FlowRate", "Temp_PV",
            "Temp_SP", "Speed_Ref", "Net_Weight", "Gross_Weight", "Tare_Weight", "Scaled_Value",
            "Scale_Factor", "Offset_Value", "PT101_PV", "TT205_PV", "FT110_PV", "LT120_PV", "Valve_Pos",
            "Pump_Speed", "Dosing_Rate", "Mix_Ratio", "Steam_SP", "Cool_SP"]
NUM_DINT = ["Batch_Count", "Recipe_No", "Step_No", "Reject_Total", "Shift_Total", "Cycle_Count",
            "Product_Code", "Lane_No", "Fault_Code", "Order_No", "Pallet_Count", "Shift_No", "Zone_No",
            "Retry_Count"]
TIMERS = ["Start_Delay_TMR", "Alarm_TMR", "Purge_TMR", "Run_On_TMR", "Fill_TMR", "Settle_TMR",
          "Drain_TMR", "Mix_TMR", "Heat_TMR", "Cool_TMR", "Flush_TMR", "Dwell_TMR"]
COUNTERS = ["Part_CTR", "Bottle_CTR", "Batch_CTR", "Reject_CTR", "Case_CTR", "Cap_CTR", "Label_CTR",
            "Pallet_CTR"]
ARRAYS = [("Recipe_Buffer", "Active_Recipe"), ("Setpoint_Table", "Live_Setpoints"), ("Raw_Data", "Log_Data")]

CMP_OP = {"EQ": "=", "NE": "<>", "GT": ">", "LT": "<", "GE": ">=", "LE": "<="}
V35 = {"EQ": "EQU", "NE": "NEQ", "GT": "GRT", "LT": "LES", "GE": "GEQ", "LE": "LEQ", "MOVE": "MOV"}
CMP_WORDS = {
    "EQ": ["equals", "is equal to"],
    "NE": ["is not equal to", "differs from"],
    "GT": ["is greater than", "is above", "exceeds"],
    "LT": ["is less than", "is below"],
    "GE": ["is at least", "is greater than or equal to"],
    "LE": ["is at most", "is less than or equal to", "does not exceed"],
}


# ---------------------------------------------------------------- case model


@dataclass
class Case:
    id: str
    feature: str  # the instruction this case is about
    structure: str
    english: str
    spec: str  # expected LogicSpec
    rungs: list[str]  # expected neutral text (reference builder)
    presets: dict[str, int] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)  # project tags offered to the model
    context: list[str] = field(default_factory=list)  # rungs already in the "project" (helper timers)
    context_spec: list[str] = field(default_factory=list)  # the same, as LogicSpec

    @property
    def answer(self) -> str:
        """What a model should write: the spec without the project's existing logic."""
        return "\n".join(x for x in self.spec.splitlines() if x not in self.context_spec)


# ---------------------------------------------------------------- atoms


class Builder:
    def __init__(self, rng: random.Random, version: int):
        self.rng = rng
        self.version = version
        self.tags: dict[str, str] = {}
        self.used: set[str] = set()
        self.presets: dict[str, int] = {}
        self.pre_rungs: list[Rung] = []  # helper rungs (timers) in the reference
        self.pre_specs: list[str] = []
        self.n_ref = 0

    def mn(self, name: str) -> str:
        return V35.get(name, name) if self.version < 36 else name

    def pick(self, pool, kind: str) -> str:
        free = [x for x in pool if x not in self.used] or list(pool)
        x = self.rng.choice(free)
        self.used.add(x)
        if kind:
            self.tags[x] = kind
        return x

    def bool_in(self):
        return self.pick(BOOL_IN, "BOOL")

    def bool_out(self):
        return self.pick(BOOL_OUT, "BOOL")

    def num(self, real: bool | None = None):
        real = self.rng.random() < 0.7 if real is None else real
        return self.pick(NUM_REAL, "REAL") if real else self.pick(NUM_DINT, "DINT")

    # condition atom: (english, logicspec, [Instr]); kind decides the instruction
    def atom(self, kind: str):
        r = self.rng
        if kind == "XIC":
            t = self.bool_in()
            return (r.choice([f"{t} is on", f"{t} is active", f"{t} is true"]), t, [Instr("XIC", (t,))])
        if kind == "XIO":
            t = self.bool_in()
            return (r.choice([f"{t} is off", f"{t} is not active", f"{t} is false"]), f"NOT {t}",
                    [Instr("XIO", (t,))])
        if kind in CMP_OP:
            a = self.num()
            b = str(r.choice([0, 5, 10, 50, 80, 100, 250])) if r.random() < 0.5 else self.num()
            return (f"{a} {r.choice(CMP_WORDS[kind])} {b}", f"{a} {CMP_OP[kind]} {b}",
                    [Instr(self.mn(kind), (a, b))])
        if kind == "ONS":
            t = self.bool_in()
            self.n_ref += 1
            return (r.choice([f"the moment {t} turns on", f"on the rising edge of {t}",
                              f"{t} goes from off to on"]),
                    f"RISE({t})", [Instr("XIC", (t,)), Instr("ONS", (f"REF_ONS_{self.n_ref}",))])
        if kind == "DN_TMR":  # timer done, the timer started by a helper rung
            src = self.bool_in()
            t = self.pick(TIMERS, "TIMER")  # an existing timer the model may reference
            ms = r.choice([2, 3, 5, 10, 30]) * 1000
            self.presets[t] = ms
            self.pre_rungs.append(Rung(Series((Instr("XIC", (src,)), Instr("TON", (t, "?", "?"))))))
            self.pre_specs.append(f"IF {src} THEN ON_DELAY_TIMER({t}, {ms // 1000}s);")
            return (f"{t} is done", f"{t}.DN", [Instr("XIC", (f"{t}.DN",))])
        raise ValueError(kind)


COND_KINDS = ["XIC", "XIO", "XIC", "XIO", "GT", "LT", "EQ", "NE", "GE", "LE"]


def _and(parts, nested):
    eng = [p[0] for p in parts]
    text = (", ".join(eng[:-1]) + " and " + eng[-1]) if len(eng) > 2 else " and ".join(eng)
    return ((f"both {text}" if nested else text), "(" + " AND ".join(p[1] for p in parts) + ")",
            [i for p in parts for i in p[2]])


def _or(parts, nested):
    eng = " or ".join(p[0] for p in parts)
    legs = tuple(Series(tuple(p[2])) for p in parts)
    return (f"either {eng}", "(" + " OR ".join(p[1] for p in parts) + ")", [Branch(legs)])


def _strip(spec: str) -> str:
    """Drop one pair of outer parentheses if they enclose the whole expression."""
    if not (spec.startswith("(") and spec.endswith(")")):
        return spec
    depth = 0
    for i, ch in enumerate(spec):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(spec) - 1:
            return spec  # "(A OR B) AND (C OR D)": outer parens are not one group
    return spec[1:-1]


def condition(b: Builder, structure: str, feature: str | None):
    """(english, logicspec, [elements]) for a condition tree that contains `feature` if it is a condition."""
    r = b.rng
    feat = feature if feature in COND_KINDS + ["ONS"] else None
    kinds = lambda n: [r.choice(COND_KINDS) for _ in range(n)]

    def atoms(ks):
        return [b.atom(k) for k in ks]

    if structure in ("single", "multi_output"):
        ks = [feat or r.choice(COND_KINDS)]
        if structure == "multi_output" and r.random() < 0.5:
            ks.append(r.choice(COND_KINDS))
        if feat == "ONS" and len(ks) > 1:
            ks = ["ONS"] + [k for k in ks if k != "ONS"]
        parts = atoms(ks)
        return parts[0] if len(parts) == 1 else _and(parts, False)
    if structure == "series":
        ks = kinds(r.randint(2, 3))
        if feat:
            ks[0 if feat == "ONS" else r.randrange(len(ks))] = feat
        return _and(atoms(ks), False)
    if structure == "parallel":
        ks = kinds(r.randint(2, 3))
        if feat:
            ks[r.randrange(len(ks))] = feat
        branch = _or(atoms(ks), False)
        if r.random() < 0.4:  # (A OR B) AND C
            tail = b.atom(r.choice(COND_KINDS))
            return (f"{branch[0]}, and {tail[0]}", f"({branch[1]} AND {tail[1]})", branch[2] + tail[2])
        return branch
    if structure == "nested":
        if r.random() < 0.5:  # (A AND B) OR C
            k1 = kinds(2)
            if feat:
                k1[0] = feat
            left = _and(atoms(k1), True)
            right = b.atom(r.choice(COND_KINDS))
            legs = (Series(tuple(left[2])), Series(tuple(right[2])))
            return (f"either {left[0]}, or {right[0]}", f"({left[1]} OR {right[1]})", [Branch(legs)])
        # A AND (B OR C)
        first = b.atom(feat if feat == "ONS" else r.choice(COND_KINDS))
        ks = kinds(2)
        if feat and feat != "ONS":
            ks[0] = feat
        grp = _or(atoms(ks), True)
        return (f"{first[0]} and {grp[0]}", f"({first[1]} AND {grp[1]})", first[2] + grp[2])
    raise ValueError(structure)


# ---------------------------------------------------------------- actions


def action(b: Builder, kind: str):
    """(english, logicspec action or None for OTE, [Instr], ote_target)"""
    r = b.rng
    if kind == "OTE":
        o = b.bool_out()
        return (r.choice([f"turn on {o}", f"energize {o}", f"switch on {o}"]), None, Instr("OTE", (o,)), o)
    if kind == "OTL":
        o = b.bool_out()
        return (r.choice([f"latch {o}", f"set {o} and keep it set"]), f"SET {o}", Instr("OTL", (o,)), None)
    if kind == "OTU":
        o = b.bool_out()
        return (r.choice([f"unlatch {o}", f"reset {o}"]), f"RESET {o}", Instr("OTU", (o,)), None)
    if kind in ("ADD", "SUB", "MUL", "DIV"):
        x, y, z = b.num(True), b.num(True), b.num(True)
        if kind == "DIV" and r.random() < 0.5:
            y = str(r.choice([2, 4, 10, 100]))
        eng = {"ADD": [f"add {x} and {y} and store the result in {z}", f"store {x} plus {y} in {z}"],
               "SUB": [f"subtract {y} from {x} and store the result in {z}", f"store {x} minus {y} in {z}"],
               "MUL": [f"multiply {x} by {y} into {z}", f"store {x} times {y} in {z}"],
               "DIV": [f"divide {x} by {y} and store it in {z}", f"store {x} divided by {y} in {z}"]}[kind]
        sym = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}[kind]
        return (r.choice(eng), f"{z} := {x} {sym} {y}", Instr(kind, (x, y, z)), None)
    if kind == "MOVE":
        z = b.num()
        if r.random() < 0.4:
            v = str(r.choice([0, 1, 50, 100, 250]))
            return (f"set {z} to {v}", f"{z} := {v}", Instr(b.mn("MOVE"), (v, z)), None)
        x = b.num()
        return (r.choice([f"copy the value of {x} into {z}", f"move {x} to {z}"]), f"{z} := {x}",
                Instr(b.mn("MOVE"), (x, z)), None)
    if kind == "COP":
        src, dst = r.choice(ARRAYS)
        n = r.choice([2, 5, 10])
        b.tags[src] = b.tags[dst] = "DINT"
        return (f"copy {n} elements from {src} to {dst}", f"COPY({src}, {dst}, {n})",
                Instr("COP", (src, dst, str(n))), None)
    if kind == "CLR":
        z = b.num()
        return (r.choice([f"clear {z}", f"reset {z} to zero"]), f"CLEAR {z}", Instr("CLR", (z,)), None)
    if kind in ("TON", "TOF"):
        t = b.pick(TIMERS, "")
        s = r.choice([2, 3, 5, 10, 30])
        b.presets[t] = s * 1000
        eng = (f"run the on-delay timer {t} with a {s} second preset" if kind == "TON"
               else f"run the off-delay timer {t} with a {s} second preset")
        kw = "ON_DELAY_TIMER" if kind == "TON" else "OFF_DELAY_TIMER"
        return (eng, f"{kw}({t}, {s}s)", Instr(kind, (t, "?", "?")), None)
    if kind in ("CTU", "CTD"):
        c = b.pick(COUNTERS, "")
        n = r.choice([3, 10, 12, 24, 100])
        b.presets[c] = n
        eng = f"count {'up' if kind == 'CTU' else 'down'} on {c} with a preset of {n}"
        kw = "COUNT_UP" if kind == "CTU" else "COUNT_DOWN"
        return (eng, f"{kw}({c}, {n})", Instr(kind, (c, "?", "?")), None)
    if kind == "RES":
        c = b.pick(COUNTERS, "COUNTER")  # an existing counter: offered to the model like a project tag
        b.presets.setdefault(c, 10)
        return (f"reset the counter {c}", f"RESET_ACC {c}", Instr("RES", (c,)), None)
    raise ValueError(kind)


ACTION_KINDS = ["OTE", "OTE", "OTL", "OTU", "ADD", "SUB", "MUL", "DIV", "MOVE", "COP", "CLR",
                "TON", "TOF", "CTU", "CTD"]


# ---------------------------------------------------------------- one case


def make_case(rng: random.Random, feature: str, structure: str, n: int, version: int) -> Case:
    b = Builder(rng, version)
    if feature == "TON" and rng.random() < 0.4:  # timer done used as a condition
        cond = b.atom("DN_TMR")
        if structure != "single":
            extra = condition(b, structure if structure != "multi_output" else "single", None)
            cond = _and([cond, extra], False)
    else:
        cond = condition(b, structure, feature)
    n_act = rng.randint(2, 3) if structure == "multi_output" else 1
    kinds = [feature if feature in ACTION_KINDS + ["RES"] else rng.choice(ACTION_KINDS)]
    while len(kinds) < n_act:
        k = rng.choice(ACTION_KINDS)
        if k not in kinds or k == "OTE":
            kinds.append(k)
    if feature == "RES" and "CTU" not in kinds:  # a reset needs a counter to reset
        pass
    acts = [action(b, k) for k in kinds]
    cond_spec = _strip(cond[1])

    # English
    act_eng = [a[0] for a in acts]
    act_text = act_eng[0] if len(act_eng) == 1 else ", ".join(act_eng[:-1]) + " and " + act_eng[-1]
    # several actions: condition first, else "A and B if C" is ambiguous about what C covers
    if rng.random() < 0.5 or len(act_eng) > 1:
        english = f"When {cond[0]}, {act_text}."
    else:
        english = f"{act_text[0].upper()}{act_text[1:]} if {cond[0]}."

    # expected LogicSpec: a lone coil is `X := cond;`, anything else one IF (coils as ENERGIZE)
    specs = list(b.pre_specs)
    if len(acts) == 1 and acts[0][3]:
        specs.append(f"{acts[0][3]} := {cond_spec};")
    else:
        specs.append(f"IF {cond_spec} THEN " + ", ".join(a[1] or f"ENERGIZE {a[3]}" for a in acts) + ";")

    # expected rungs (reference builder: one rung, output branch for several actions)
    outs = [a[2] for a in acts]
    tail = [outs[0]] if len(outs) == 1 else [Branch(tuple(Series((o,)) for o in outs))]
    rungs = b.pre_rungs + [Rung(Series(tuple(cond[2] + tail)))]
    offered = {k: v for k, v in b.tags.items() if v}
    return Case(f"{feature}-{structure}-{n:03d}", feature, structure, english, "\n".join(specs),
                [format_rung(r) for r in rungs], dict(b.presets), offered,
                [format_rung(r) for r in b.pre_rungs], list(b.pre_specs))


def generate(per_combo: int = 3, seed: int = 1, version: int = 35,
             instructions: list[str] | None = None, structures: list[str] | None = None) -> list[Case]:
    rng = random.Random(seed)
    cases = []
    for feat in instructions or INSTRUCTIONS:
        for st in structures or STRUCTURES:
            for n in range(per_combo):
                cases.append(make_case(rng, feat, st, n, version))
    return cases
