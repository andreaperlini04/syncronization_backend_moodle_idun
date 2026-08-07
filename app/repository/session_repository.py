import sqlite3
from pathlib import Path
from threading import Lock

from app.models.session import Session


class SessionRepository:
    """Storico delle sessioni chiuse (per la tesi: numero sessioni, durata, ecc.).
    NON gestisce la sessione attiva corrente: quella vive in memoria in SessionService.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id  TEXT PRIMARY KEY,
                    started_at  REAL NOT NULL,
                    stopped_at  REAL,
                    row_count   INTEGER
                )
                """
            )

    def save_closed(self, session: Session) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions "
                "(session_id, started_at, stopped_at, row_count) VALUES (?, ?, ?, ?)",
                (session.session_id, session.started_at, session.stopped_at, session.row_count),
            )

    def exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None
