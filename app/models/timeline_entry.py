from dataclasses import dataclass
from typing import Optional


@dataclass
class TimelineEntry:
    session_id: Optional[str]  # None = fuori sessione (debug/completezza)
    ts: float                  # timestamp di arrivo al backend
    source: str                # "moodle" | "eeg"
    event_type: str
    payload: str                # JSON già serializzato
    description: str = ""       # leggibile per revisione umana (vedi moodle_descriptions.py)