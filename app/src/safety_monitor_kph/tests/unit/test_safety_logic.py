from safety.monitor import SafetyMonitor
from safety.config import get_config

def make_monitor(cfg_overrides=None):
    cfg = get_config()
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return SafetyMonitor(cfg), cfg

def test_seatbelt_activate_and_clear():
    mon, _ = make_monitor({"DEBOUNCE_COUNT": 2, "THRESHOLD_KPH": 5})
    fast = 8  # kph
    slow = 4

    # Below threshold -> no activation
    ch_sb, ch_dr, _ = mon.evaluate(slow, {"Row1.DriverSide": False}, {"frontLeft": True})
    assert ch_sb is None and ch_dr is None

    # Two fast ticks with unfastened -> activate
    for _ in range(2):
        ch_sb, _, _ = mon.evaluate(fast, {"Row1.DriverSide": False}, {"frontLeft": True})
    assert ch_sb == "activated"

    # Two fast ticks now fastened -> clear
    for _ in range(2):
        ch_sb, _, _ = mon.evaluate(fast, {"Row1.DriverSide": True}, {"frontLeft": True})
    assert ch_sb == "cleared"

def test_door_activate_and_clear():
    mon, _ = make_monitor({"DEBOUNCE_COUNT": 2, "THRESHOLD_KPH": 5})
    fast = 9

    # Door open while moving -> activate
    for _ in range(2):
        _, ch_dr, _ = mon.evaluate(fast, {"Row1.DriverSide": True}, {"frontLeft": False})
    assert ch_dr == "activated"

    # Door closed while moving -> clear
    for _ in range(2):
        _, ch_dr, _ = mon.evaluate(fast, {"Row1.DriverSide": True}, {"frontLeft": True})
    assert ch_dr == "cleared"
