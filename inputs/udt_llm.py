"""Plain English -> UDT. The model writes the small UDT text form (udt.model);
code checks it and builds the file. On llama.cpp the answer is grammar-constrained."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from inputs.llm import LLMError
from udt.model import MEMBER_TYPES, UdtDef, UdtError, check, format_spec, parse_spec

SYSTEM = """You turn a plain-English description of a PLC data structure into a Studio 5000 UDT.
Reply with the UDT text form only, no explanations, no code fences:

UDT Name "what it is";
Member TYPE "what it holds";
Member TYPE[n] "an array of n";

TYPE is BOOL, SINT, INT, DINT, LINT, REAL, LREAL, STRING, TIMER, COUNTER, CONTROL,
or the name of another UDT (defined in the same reply, or one of the project's UDTs listed below).
Rules:
  - on/off states, flags, commands, alarms as single bits = BOOL; "32 alarm bits" = BOOL[32] (BOOL arrays: multiples of 32)
  - speed, temperature, pressure, level, flow, setpoints, measured values = REAL
  - counts, codes, states, step numbers, IDs = DINT; text = STRING; a timer = TIMER; a counter = COUNTER
  - names: letters, digits and _, start with a letter, at most 40 characters, no __, no _ at the end
  - use names given in the request exactly; otherwise short names like Run_Cmd, Speed_SP
  - every member gets a short description
  - one UDT unless the request asks for several; a UDT used inside another comes first
  - member order does not matter: it is reordered for memory later"""

EXAMPLES = [
    ("A motor: running and faulted bits, speed in rpm, run hours, the last fault code and 32 alarm bits.",
     'UDT Motor "Motor status";\nRunning BOOL "Motor is running";\nFaulted BOOL "Motor has a fault";\n'
     'Speed REAL "Speed, rpm";\nRun_Hours REAL "Accumulated run hours";\nFault_Code DINT "Last fault code";\n'
     'Alarms BOOL[32] "Alarm bits";'),
    ("Valve UDT with open and close commands, open and closed limit switches and a travel timer.",
     'UDT Valve "On/off valve";\nOpen_Cmd BOOL "Command to open";\nClose_Cmd BOOL "Command to close";\n'
     'Opened_LS BOOL "Open limit switch";\nClosed_LS BOOL "Closed limit switch";\nTravel_TMR TIMER "Travel time monitor";'),
    ("A tank with level and temperature, and two pumps that each have a run command and a speed setpoint.",
     'UDT Pump "Pump";\nRun_Cmd BOOL "Run command";\nSpeed_SP REAL "Speed setpoint, %";\n'
     'UDT Tank "Tank with two pumps";\nLevel REAL "Level, %";\nTemperature REAL "Temperature, degC";\n'
     'Pumps Pump[2] "The tank\'s pumps";'),
]


def grammar(project_types: list[str]) -> str:
    """GBNF for the UDT text form (llama.cpp)."""
    natives = sorted(MEMBER_TYPES)
    alts = " | ".join(f'"{t}"' for t in natives + [t for t in project_types if re.fullmatch(r"[A-Za-z_]\w*", t)])
    return "\n".join([
        'root ::= udt (nl udt)* nl?',
        'udt ::= "UDT " name desc? ";" (nl member)+',
        'member ::= name " " type desc? ";"',
        f'type ::= ({alts} | name) ("[" [1-9] [0-9]? [0-9]? [0-9]? "]")?',
        'name ::= [A-Za-z] [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? '
        '[A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? '
        '[A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? '
        '[A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]? [A-Za-z0-9_]?',
        'desc ::= " \\"" [^"\\n]* "\\""',
        'nl ::= "\\n"',
    ])


def extract(reply: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S | re.I)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    keep = [ln.strip() for ln in text.splitlines()
            if re.match(r'\s*(UDT\s+\w+|[A-Za-z_]\w*\s+[A-Za-z_]\w*(\[\d+\])?)\s*("[^"]*")?\s*;', ln)]
    return "\n".join(keep)


@dataclass
class UdtResult:
    udts: list[UdtDef] | None
    spec: str | None
    attempts: list[dict] = field(default_factory=list)  # {"reply", "error"}
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def generate(client, request: str, known: dict[str, str] | None = None, retries: int = 2) -> UdtResult:
    """known: the project's data types {name: "UDT" | "AOI" | "STRING"}."""
    t0 = time.perf_counter()
    known = known or {}
    sys_msg = SYSTEM + ("\nProject UDTs you may use: " + ", ".join(sorted(known)) if known else "")
    msgs = [{"role": "system", "content": sys_msg}]
    for q, a in EXAMPLES:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": request})
    res = UdtResult(None, None)
    use_grammar = bool(getattr(client, "supports_grammar", False))
    for _ in range(retries + 1):
        try:
            reply = client.chat(msgs, grammar=grammar(sorted(known)) if use_grammar else None)
        except LLMError as e:
            if use_grammar and "grammar" in str(e).lower():
                use_grammar = False
                res.warnings.append("the server did not accept the UDT grammar; answered without it")
                continue
            raise
        spec = extract(reply)
        error = None
        try:
            udts = parse_spec(spec)
            problems = check(udts, known)
            if problems:
                error = "; ".join(problems[:4])
        except UdtError as e:
            error = str(e)
        res.attempts.append({"reply": reply, "error": error})
        if error is None:
            res.udts, res.spec = udts, format_spec(udts)
            break
        msgs = msgs + [{"role": "assistant", "content": reply},
                       {"role": "user", "content": f"That UDT has an error: {error}\nReply with the corrected UDT only."}]
    else:
        res.error = f"no valid UDT after {len(res.attempts)} attempts: {res.attempts[-1]['error'] if res.attempts else '?'}"
    res.seconds = round(time.perf_counter() - t0, 2)
    return res
