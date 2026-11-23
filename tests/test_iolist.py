import io

import pytest
from openpyxl import Workbook

from inputs.iolist import IOListError, plant_yaml, read_iolist
from plant import load_plant


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
