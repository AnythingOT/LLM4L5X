import pytest

from plant import Motor, PlantError, Valve, load_plant
from plant.plant import Plant

PUMP = "devices:\n  - {name: P101, type: pump, cmd: Cmd, running: Run, overload: OL, start_ms: 1000, stop_ms: 400}\n"


def run(p, ms, plc, step=100):
    out = {}
    for _ in range(int(ms // step)):
        out = p.step(step, plc)
    return out


def test_pump_feedback_follows_the_command_after_its_delays():
    p = load_plant(PUMP)
    assert run(p, 900, {"Cmd": 1})["Run"] is False
    assert run(p, 100, {"Cmd": 1})["Run"] is True           # exactly 1000 ms
    assert run(p, 300, {"Cmd": 0})["Run"] is True
    assert run(p, 100, {"Cmd": 0})["Run"] is False          # 400 ms stop delay


def test_a_command_shorter_than_the_start_delay_never_runs_the_pump():
    p = load_plant(PUMP)
    run(p, 600, {"Cmd": 1})
    assert run(p, 600, {"Cmd": 0})["Run"] is False and run(p, 600, {"Cmd": 1})["Run"] is False


def test_same_result_whatever_the_step_size():
    a, b = load_plant(PUMP), load_plant(PUMP)
    assert run(a, 1000, {"Cmd": 1}, step=10) == run(b, 1000, {"Cmd": 1}, step=500)


def test_motor_without_feedback_writes_nothing():
    p = load_plant("devices:\n  - {name: M1, type: motor, cmd: M1_Cmd}\n")
    assert p.feedbacks() == [] and run(p, 2000, {"M1_Cmd": 1}) == {}


@pytest.mark.parametrize("fault, run_, ol", [("fail_to_start", False, False), ("trip", False, True),
                                            ("fb_stuck_on", True, False)])
def test_motor_faults(fault, run_, ol):
    p = load_plant(PUMP)
    p.write("PLANT:P101.fault", fault)
    out = run(p, 3000, {"Cmd": 1 if fault != "fb_stuck_on" else 0})
    assert (out["Run"], out["OL"]) == (run_, ol)


def test_trip_while_running_drops_feedback_and_clearing_it_restarts():
    p = load_plant(PUMP)
    assert run(p, 1000, {"Cmd": 1})["Run"] is True
    p.write("PLANT:P101.fault", "trip")
    assert run(p, 400, {"Cmd": 1}) == {"Run": False, "OL": True}
    p.write("PLANT:P101.fault", "none")
    assert run(p, 1000, {"Cmd": 1}) == {"Run": True, "OL": False}


VALVE = ("devices:\n  - {name: XV1, type: valve, open_cmd: Op, open_ls: ZSO, closed_ls: ZSC, travel_ms: 2000}\n")


def test_single_solenoid_valve_travels_and_springs_back():
    p = load_plant(VALVE)
    assert run(p, 100, {"Op": 1}) == {"ZSO": False, "ZSC": False}   # leaves closed at once
    assert run(p, 1900, {"Op": 1}) == {"ZSO": True, "ZSC": False}   # open after 2 s
    assert run(p, 2000, {"Op": 0}) == {"ZSO": False, "ZSC": True}   # spring return


def test_double_solenoid_holds_without_a_command_and_notes_both_on():
    p = load_plant("devices:\n  - {name: XV2, type: valve, open_cmd: O, close_cmd: C, open_ls: ZSO, "
                   "travel_ms: 1000}\n")
    run(p, 500, {"O": 1})
    assert p.read("PLANT:XV2.position") == 0.5
    run(p, 2000, {})
    assert p.read("PLANT:XV2.position") == 0.5                      # holds mid travel
    run(p, 200, {"O": 1, "C": 1})
    assert p.read("PLANT:XV2.position") == 0.5 and p.notes() == ["XV2: open and close commands on together"]
    assert run(p, 1000, {"C": 1}) == {"ZSO": False} and p.read("PLANT:XV2.position") == 0.0


@pytest.mark.parametrize("fault, zso, zsc", [("stuck", False, True), ("open_ls_off", False, False),
                                            ("closed_ls_on", True, True)])
def test_valve_faults(fault, zso, zsc):
    p = load_plant(VALVE)
    p.write("PLANT:XV1.fault", fault)
    assert run(p, 3000, {"Op": 1}) == {"ZSO": zso, "ZSC": zsc}


def test_slow_valve_takes_three_times_as_long():
    p = load_plant(VALVE)
    p.write("PLANT:XV1.fault", "slow")
    assert run(p, 5900, {"Op": 1})["ZSO"] is False and run(p, 100, {"Op": 1})["ZSO"] is True


def test_valve_with_one_limit_switch_or_none():
    p = load_plant("devices:\n  - {name: V0, type: valve, open_cmd: A}\n"
                   "  - {name: V1, type: valve, open_cmd: B, closed_ls: B_ZSC}\n")
    assert p.feedbacks() == ["B_ZSC"] and run(p, 4000, {"A": 1, "B": 1}) == {"B_ZSC": False}


@pytest.mark.parametrize("text, msg", [
    ("devices: []\nx: 1", None),
    ("nope", "needs a 'devices:' list"),
    ("devices:\n  - {name: P1, type: compressor, cmd: C}", "type must be one of"),
    ("devices:\n  - {name: 1P, type: pump, cmd: C}", "plain identifier"),
    ("devices:\n  - {name: P1, type: pump}", "needs its command tag"),
    ("devices:\n  - {name: P1, type: pump, cmd: C, speed: 5}", "unknown speed"),
    ("devices:\n  - {name: P1, type: pump, cmd: C, running: R}\n  - {name: P2, type: pump, cmd: D, running: R}",
     "one tag, one device"),
    ("devices:\n  - {name: P1, type: pump, cmd: C}\n  - {name: P1, type: pump, cmd: D}", "defined twice"),
    ("devices: [", "not valid YAML"),
])
def test_plant_file_errors_say_what_to_fix(text, msg):
    if msg is None:
        assert load_plant(text).devices == {}
    else:
        with pytest.raises(PlantError, match=msg):
            load_plant(text)


def test_plant_tags_reject_unknown_devices_faults_and_attributes():
    p = load_plant(PUMP)
    with pytest.raises(PlantError, match="no device P102"):
        p.read("PLANT:P102.fault")
    with pytest.raises(PlantError, match="a motor can have"):
        p.write("PLANT:P101.fault", "stuck")
    with pytest.raises(PlantError, match="only PLANT:P101.fault can be set"):
        p.write("PLANT:P101.running", 1)
    assert p.owns("PLANT:P101.fault") and not p.owns("P101_Cmd")
    assert p.commands() == ["Cmd"] and p.feedbacks() == ["OL", "Run"]


def test_devices_can_be_built_in_code():
    p = Plant([Motor("M", cmd="C", running="R", start_ms=0), Valve("V", open_cmd="O", travel_ms=0, open_ls="L")])
    assert p.step(1, {"C": 1, "O": 1}) == {"R": True, "L": True}
    with pytest.raises(PlantError, match="backwards"):
        p.step(-1, {})
