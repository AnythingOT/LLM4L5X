"""Scenario tests: requirement-level checks run against logic + plant, in OpenVnV's step language.

    SCENARIO TC-07 "P-101 fails to start" REQ R3
    SETUP:
      SET Auto_Mode = 1
    MAIN:
      SET PLANT:P101.fault = fail_to_start
      SET Level_Low = 1
      EXPECT P101_Cmd == 1 within_ms 500
      EXPECT P101_Fail == 1 within_ms 6000
      EXPECT P101_Cmd == 0 within_ms 500
    TEARDOWN:
      SET PLANT:P101.fault = none

Actions SET, EXPECT, WAIT, RESET, COMMENT, CALL; EXPECT operators == != < <= > >=, modifiers
within_ms N (polled every scan until true), within_ms N hold (must stay true for all N ms: the
negative test), tolerance X. TEARDOWN always runs, even after a failure.

The runner talks to a Backend (read, write, advance): the simulator with a plant model here; a
pylogix backend talks to an emulator or a controller with the same scenarios.
"""

from .backend import Backend, SimBackend
from .dsl import Scenario, ScenarioError, Step, parse_scenarios
from .runner import ScenarioResult, StepResult, report, run_scenario, run_scenarios, trace

__all__ = ["Backend", "Scenario", "ScenarioError", "ScenarioResult", "SimBackend", "Step", "StepResult",
           "parse_scenarios", "report", "run_scenario", "run_scenarios", "trace"]
