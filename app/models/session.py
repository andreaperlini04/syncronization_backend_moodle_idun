from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    session_id: str
    started_at: float
    stopped_at: Optional[float] = None
    row_count: Optional[int] = None
    user_id: Optional[int] = None  # studente Moodle, appreso dagli eventi del plugin
