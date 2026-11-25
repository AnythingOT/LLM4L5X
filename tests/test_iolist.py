import io

import pytest
from openpyxl import Workbook

from generate.iolist import IOListError, plant_yaml, read_iolist
from devices import load_plant


def xlsx(rows, title="IO"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEAD = ["Tag Name", "Description", "I/O Address", "Signal Type", "Range Low", "Range High", "Units"]
GOOD = [
    ["Project IO list rev B"], [],
    HEAD,
    ["P101_Cmd", "Fill pump run command", "Local:2:O.Data.0", "DO"],
    ["P101_Running", "Fill pump running", "Local:1:I.Data.0", "Digital Input"],
    ["P101_OL", "Fill pump overload", "Local:1:I.Data.1", "DI"],
    ["XV101_Open", "Inlet valve open", "Local:2:O.Data.1", "DO"],
    ["XV101_ZSO", "Inlet valve opened", "Local:1:I.Data.2", "DI"],
    ["XV101_ZSC", "Inlet valve closed", "Local:1:I.Data.3", "DI"],
    ["XV102_Open", "Drain open", "Local:2:O.Data.2", "DO"],
    ["XV102_Close", "Drain close", "Local:2:O.Data.3", "DO"],
    ["XV102_ZSC", "Drain closed", "Local:1:I.Data.4", "DI"],
    ["AG101_Cmd", "Agitator", "Local:2:O.Data.4", "DO"],
    ["LT101_PV", "Tank level", "Local:3:I.Ch0Data", "AI", 0, 100, "%"],
    ["Level_Low", "Tank low level", "Local:1:I.Data.5", ""],          # type from the address
]


def test_reads_loose_headers_after_title_rows_and_checks_pass():
    iol = read_iolist(xlsx(GOOD))
    assert len(iol.points) == 12 and iol.errors == [] and iol.warnings == []
    lt = iol.by_tag()["LT101_PV"]
    assert (lt.type, lt.lo, lt.hi, lt.units) == ("AI", 0, 100, "%")
    assert iol.by_tag()["Level_Low"].type == "DI" and iol.by_tag()["P101_Running"].type == "DI"


def test_devices_are_recognised_and_become_a_working_plant():
    iol = read_iolist(xlsx(GOOD))
    kinds = {d.name: d.kind for d in iol.devices}
    assert kinds == {"P101": "pump", "XV101": "valve", "XV102": "valve", "AG101": "pump", "LT101": "",
                     "Level": ""}
    p = load_plant(plant_yaml(iol))                    # the proposal is a valid plant file
    assert p.devices["P101"].running == "P101_Running" and p.devices["P101"].overload == "P101_OL"
    assert p.devices["XV102"].close_cmd == "XV102_Close" and p.devices["XV102"].open_ls == ""
    assert p.devices["AG101"].running == ""            # no feedback in the list: none simulated
    assert "not recognised" in plant_yaml(iol) and "LT101" in plant_yaml(iol)
    out = {}
    for _ in range(12):
        out = p.step(100, {"P101_Cmd": 1, "XV101_Open": 1})
    assert out["P101_Running"] and not out["XV101_ZSC"]


def test_device_column_wins_over_the_tag_prefix():
    iol = read_iolist(xlsx([["Tag", "Address", "Type", "Device"],
                            ["Pump_Start", "Local:2:O.Data.0", "DO", "P-201"],
                            ["Pump_Run_FB", "Local:1:I.Data.0", "DI", "P-201"]]))
    assert [(d.name, d.kind, len(d.points)) for d in iol.devices] == [("P-201", "pump", 2)]


@pytest.mark.parametrize("row, msg", [
    (["2Pump", "x", "Local:1:I.Data.9", "DI"], "not a valid Logix name"),
    (["Pump__Run", "x", "Local:1:I.Data.9", "DI"], "double or trailing underscore"),
    (["Spare", "x", "", "maybe"], "no signal type"),
    (["P101_RUNNING", "dup", "Local:1:I.Data.9", "DI"], "appears twice"),           # case does not matter
    (["Other", "x", "Local:1:I.Data.0", "DI"], "is used by P101_Running and Other"),
    (["Hand_Lamp", "x", "Local:1:I.Data.9", "DO"], "is DO but Local:1:I.Data.9 is an input address"),
    (["FT1_PV", "x", "Local:3:I.Ch1Data", "AI", 50, 10], "range low 50 is not below range high 10"),
])
def test_errors_say_what_is_wrong(row, msg):
    iol = read_iolist(xlsx(GOOD + [row]))
    assert any(msg in e for e in iol.errors), iol.errors


@pytest.mark.parametrize("row, msg", [
    (["Spare_1", "Spare", "", "DI"], "has no address"),
    (["Spare_1", "", "Local:1:I.Data.9", "DI"], "has no description"),
    (["FT1_PV", "Flow", "Local:3:I.Ch1Data", "AI"], "analog with no range"),
])
def test_warnings_do_not_stop_the_list(row, msg):
    iol = read_iolist(xlsx(GOOD + [row]))
    assert iol.errors == [] and any(msg in w for w in iol.warnings)


def test_not_an_io_list():
    with pytest.raises(IOListError, match="Tag column"):
        read_iolist(xlsx([["Requirement", "Rung text"], ["x", "y"]]))
    with pytest.raises(IOListError, match="not an Excel workbook"):
        read_iolist(b"plain text")


def test_mapping_routines_follow_the_sim_mode_pattern():
    from core.rung import format_rung
    from generate.iolist import mapping
    m = mapping(read_iolist(xlsx(GOOD + [["FCV1_Out", "Valve out", "Local:4:O.Ch0Data", "AO", 0, 100, "%"],
                                         ["Spare_9", "Spare", "", "DI"]])))
    ins = [format_rung(r) for r in m.map_in]
    outs = [format_rung(r) for r in m.map_out]
    assert "XIC(Local:1:I.Data.0)OTE(P101_Running);" in ins and "MOV(Local:3:I.Ch0Data,LT101_PV);" in ins
    assert not any("Sim_Mode" in r for r in ins)          # MAP_IN is skipped by its JSR, not by its rungs
    assert "XIC(P101_Cmd)XIO(Sim_Mode)OTE(Local:2:O.Data.0);" in outs
    assert any("XIC(Sim_Mode) CLR(Local:4:O.Ch0Data)" in r for r in outs)
    assert m.map_in[0].comment == "Fill pump running (Local:1:I.Data.0)"
    assert m.skipped == ["Spare_9"]
    types = {t.name: t.datatype for t in m.tags}
    assert types["LT101_PV"] == "REAL" and types["P101_Running"] == "BOOL" and types["Sim_Mode"] == "BOOL"
    assert next(t for t in m.tags if t.name == "LT101_PV").description == "Tank level 0..100 %"


def test_outputs_are_forced_off_in_sim_mode():
    from core.simulator import Simulator
    from generate.iolist import mapping
    m = mapping(read_iolist(xlsx(GOOD)))
    sim = Simulator(m.map_out, {"P101_Cmd": 1})
    sim.scan()
    assert sim.get("Local:2:O.Data.0") == 1
    sim.put("Sim_Mode", 1)
    sim.scan()
    assert sim.get("Local:2:O.Data.0") == 0                # a test on real hardware cannot run the pump


def test_mapping_refuses_a_list_with_errors_and_writes_importable_l5x():
    from generate.iolist import mapping, mapping_l5x
    from l5x.reader import read_l5x
    with pytest.raises(IOListError, match="fix the I/O list first"):
        mapping(read_iolist(xlsx(GOOD + [["P101_Cmd", "dup", "Local:2:O.Data.9", "DO"]])))
    files = mapping_l5x(read_iolist(xlsx(GOOD)))
    assert set(files) == {"MAP_IN.L5X", "MAP_OUT.L5X"}
    p = read_l5x(files["MAP_OUT.L5X"].encode())
    rungs = [r for rt in p.routines for r in rt.rungs]
    assert len(rungs) == 5 and all(r.rung is not None for r in rungs)
    assert "Sim_Mode" in files["MAP_OUT.L5X"] and "LT101_PV" not in files["MAP_OUT.L5X"]  # own tags only
