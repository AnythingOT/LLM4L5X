

def test_power_trace_is_kept_only_when_asked():
    from core.rung import parse_rung
    from core.simulator import Simulator
    sim = Simulator([parse_rung("XIC(A)XIO(B)OTE(C);")], {"A": True, "B": True})
    sim.scan(0)
    assert sim.flow == []  # comparisons and test cases run many scans: no trace unless asked
    sim.trace = True
    sim.scan(0)
    assert sim.flow == [{"0": 3, "1": 1, "2": 0}]  # A passes, B blocks, C gets nothing
