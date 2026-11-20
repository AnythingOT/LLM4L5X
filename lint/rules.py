"""The rule checklist: codes, titles, descriptions, scope.

The code prefix fixes the severity (CRT critical, ERR error, WAR warning,
INF info). A rule can be switched on or off but its severity never changes,
so a code always means the same thing in every report.

scope:
  "rung"     needs only the rungs and tag types: also run on generated logic
  "project"  needs the whole project (tasks, modules, descriptions ...): only
             judged on a full controller export
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY = {"CRT": "critical", "ERR": "error", "WAR": "warning", "INF": "info"}
LIFECYCLE = {"ERR017", "WAR021", "INF009"}


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    description: str
    scope: str  # rung | project
    group: str  # what the Rules page groups by

    @property
    def severity(self) -> str:
        return SEVERITY[self.code[:3]]


_R = Rule
RULES: list[Rule] = [
    _R("CRT001", "Forces present", "The export contains forced I/O or tag values. Remove all forces before the project is released.", "project", "Controller"),
    _R("CRT002", "AFI in rung", "An AFI (Always False) instruction disables the whole rung. Remove it or replace it with real logic.", "rung", "Logic"),

    _R("ERR001", "Duplicate OTE", "The same tag or bit is driven by OTE in more than one place. Only the last one in scan order takes effect.", "rung", "Logic"),
    _R("ERR002", "Multiple OTL", "A tag is latched (OTL) in more than one place, which makes its state hard to trace.", "rung", "Logic"),
    _R("ERR003", "Multiple OTU", "A tag is unlatched (OTU) in more than one place, which makes its state hard to trace.", "rung", "Logic"),
    _R("ERR004", "Write to MSG status bit", "Logic writes a status bit (.EN, .DN, .ER ...) of a MESSAGE tag, which the controller manages.", "rung", "Logic"),
    _R("ERR005", "Write to timer/counter bit", "Logic writes a .DN, .EN, .TT (or counter) bit of a TIMER or COUNTER, which the instruction itself manages.", "rung", "Logic"),
    _R("ERR006", "MSG not gated", "A MSG runs without a one-shot or timer bit in its rung, so it is re-triggered every scan.", "rung", "Logic"),
    _R("ERR007", "Controller fault handler", "No Controller Fault Handler program is configured, or it names a program that does not exist.", "project", "Controller"),
    _R("ERR008", "Program fault routine", "A program has no Fault Routine assigned, or names a routine that does not exist.", "project", "Programs and tasks"),
    _R("ERR009", "AOI uses controller tag", "AOI logic uses a controller-scoped tag directly instead of a parameter, which breaks the AOI's encapsulation.", "project", "Add-On Instructions"),
    _R("ERR010", "Duplicate instruction in rung", "The same instruction with the same operands appears twice in one series path, or two parallel branch legs are identical.", "rung", "Logic"),
    _R("ERR011", "Unchecked array index", "An array is indexed by a tag (Arr[Idx]) with no range check on the index before it on the same path. An out-of-range index is a major fault.", "rung", "Logic"),
    _R("ERR012", "Unguarded division", "A DIV, MOD or '/' in CPT divides by a tag that is not compared with zero before it on the same path.", "rung", "Logic"),
    _R("ERR013", "Backward jump", "A JMP jumps to a LBL at or above itself, which loops inside the scan (watchdog risk).", "rung", "Logic"),
    _R("ERR014", "Timer/counter reused", "One TIMER or COUNTER is used by more than one timer/counter instruction. (One CTU plus one CTD on the same counter is fine.)", "rung", "Logic"),
    _R("ERR015", "One-shot storage reused", "An ONS/OSR/OSF storage bit is shared by several one-shots, or also written by other logic, so edges are missed.", "rung", "Logic"),
    _R("ERR016", "No reset for RTO/counter", "An RTO or counter accumulates but is never reset: no RES and no write to .ACC.", "rung", "Logic"),
    _R("ERR017", "Discontinued module", "A module's catalog number is Discontinued in the lifecycle list. Spares may be unobtainable.", "project", "Modules"),
    _R("ERR018", "Safety tag written by standard logic", "A standard (non-safety) program writes a safety-class tag. GuardLogix lets standard logic read safety tags, not write them, so the project will not verify. Reports what the logic does; never rates safety.", "rung", "Logic"),

    _R("WAR001", "Safety map naming", "A standard tag mapped to safety tag SFTY_X must be named STD_X.", "project", "Tags"),
    _R("WAR002", "Produced/consumed naming", "A consumed tag must have the name of the produced tag it maps to, with PRO replaced by CON.", "project", "Tags"),
    _R("WAR003", "Task name missing period", "A periodic task's name must state its period (e.g. Task_10MS for a 10 ms task).", "project", "Programs and tasks"),
    _R("WAR004", "Uncalled routine", "A routine is not the main or fault routine and no JSR calls it.", "project", "Programs and tasks"),
    _R("WAR005", "Unscheduled program", "A program is not scheduled in any task.", "project", "Programs and tasks"),
    _R("WAR006", "Empty rung", "A rung contains no instructions.", "rung", "Logic"),
    _R("WAR007", "Empty branch", "A branch leg contains no instructions, which is an always-true bypass of the other legs.", "rung", "Logic"),
    _R("WAR008", "Timer preset not set", "A timer used in logic has preset 0 in its tag data and logic never writes .PRE. Timer arrays are checked per element.", "project", "Tags"),
    _R("WAR009", "Watchdog margin too small", "A periodic task's watchdog is less than 1.5 times its period, so one slow scan faults the controller.", "project", "Programs and tasks"),
    _R("WAR010", "UDT padding waste", "Reordering this UDT's members would save at least 4 bytes of alignment padding.", "project", "Data types"),
    _R("WAR011", "UDT member order", "UDT members are not grouped by data type, or not in natural alphabetical order (Valve2 before Valve10).", "project", "Data types"),
    _R("WAR013", "MSGs not staggered", "Two or more MSGs share the same trigger condition and fire together.", "rung", "Logic"),
    _R("WAR014", "JSR nesting too deep", "A JSR call chain from the main routine is nested deeper than 4 levels.", "project", "Programs and tasks"),
    _R("WAR015", "MOV REAL to integer", "A MOV converts a REAL into an integer type. MOV rounds silently (.5 to even) and can overflow. Use TRN or explicit, commented rounding.", "rung", "Logic"),
    _R("WAR016", "INT/SINT instead of DINT", "A tag uses INT or SINT. Logix is 32-bit native, so DINT is faster and avoids conversions.", "project", "Tags"),
    _R("WAR017", "Physical I/O point not mapped", "No logic references a field-data point of a physical I/O module directly (e.g. Local:4:I.Data.3). Points covered by an alias are reported by WAR022 instead.", "project", "Modules"),
    _R("WAR018", "Physical I/O point without comment", "An I/O point used directly in logic has no comment on the module I/O tag.", "project", "Modules"),
    _R("WAR019", "Used tag marked spare", "A tag, element or bit is used in logic but its description or comment says 'spare' or 'unused'.", "project", "Tags"),
    _R("WAR020", "Unused UDT/AOI definition", "A UDT or AOI definition is not used by any tag, member, parameter or rung.", "project", "Data types"),
    _R("WAR021", "End-of-life module", "A module's catalog number has reached End of Life in the lifecycle list. Plan the migration.", "project", "Modules"),
    _R("WAR022", "Alias used for physical I/O", "A tag is an alias of a physical I/O point. The standard is direct mapping logic.", "project", "Modules"),

    _R("INF001", "Unused tag", "A tag is declared but never read or written.", "project", "Tags"),
    _R("INF002", "Loose BOOL tags", "Standalone BOOL tags are used. Pack them into a DINT, a BOOL array or a UDT.", "project", "Tags"),
    _R("INF003", "Tag without description", "A used tag has no description, or a bit that logic addresses individually has no comment.", "project", "Tags"),
    _R("INF004", "Rung without comment", "A rung has no comment.", "project", "Logic"),
    _R("INF005", "AOI without description", "An AOI or one of its parameters has no description.", "project", "Add-On Instructions"),
    _R("INF006", "UDT member without description", "A UDT member has no description.", "project", "Data types"),
    _R("INF007", "Hard-coded literal", "A numeric literal other than 0, 1 or -1 is a source of a math or move instruction. Use a named tag.", "rung", "Logic"),
    _R("INF008", "Electronic keying not Compatible", "A module's electronic keying is not Compatible Module (Exact Match or Disabled). Compatible Module accepts like-for-like spares and still blocks a wrong module.", "project", "Modules"),
    _R("INF009", "Active mature module", "A module's catalog number is Active Mature. Newer alternatives exist; consider them for new designs.", "project", "Modules"),
]

BY_CODE: dict[str, Rule] = {r.code: r for r in RULES}
