from dataclasses import dataclass, field
from typing import Dict, List, Optional
@dataclass
class DebouncedState:
    active: bool = False
    up: int = 0
    down: int = 0
@dataclass
class SafetyStatus:
    moving: bool
    threshold_kph: float
    unfastened: List[str] = field(default_factory=list)
    open_doors: List[str] = field(default_factory=list)
class SafetyMonitor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.seatbelt_state = DebouncedState()
        self.door_state = DebouncedState()
    def evaluate(self, speed_kph: float, belts: Dict[str, bool], doors_closed: Dict[str, bool]):
        moving = speed_kph > self.cfg["THRESHOLD_KPH"]
        unfastened = [k for k, fastened in belts.items() if not fastened]
        open_doors = [k for k, closed in doors_closed.items() if not closed]
        sb_changed = self._update(self.seatbelt_state, moving and bool(unfastened))
        dr_changed = self._update(self.door_state, moving and bool(open_doors))
        status = SafetyStatus(moving, self.cfg["THRESHOLD_KPH"], unfastened, open_doors)
        return sb_changed, dr_changed, status
    def _update(self, st: DebouncedState, condition: bool) -> Optional[str]:
        if condition:
            st.up += 1; st.down = 0
            if not st.active and st.up >= self.cfg["DEBOUNCE_COUNT"]:
                st.active = True; return "activated"
        else:
            st.down += 1; st.up = 0
            if st.active and st.down >= self.cfg["DEBOUNCE_COUNT"]:
                st.active = False; return "cleared"
        return None