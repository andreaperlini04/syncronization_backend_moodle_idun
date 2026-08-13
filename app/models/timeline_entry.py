from dataclasses import dataclass
from typing import Optional


@dataclass
class TimelineEntry:
    session_id: Optional[str]  # None = fuori sessione (debug/completezza)
    ts: float                  # istante dell'evento, fornito dal client (epoch secondi)
    source: str                # "moodle" | "eeg"
    event_type: str
    payload: str                # JSON già serializzato
    description: str = ""       # leggibile per revisione umana (vedi moodle_descriptions.py)