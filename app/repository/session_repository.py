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

    def save_open(self, session: Session) -> bool:
        """Registra una sessione appena aperta (stopped_at ancora NULL).

        INSERT OR IGNORE: un session_start rispedito a mano, o una sessione
        già chiusa i cui campioni arrivano in ritardo, non devono azzerare
        stopped_at/row_count già scritti.

        Returns:
            bool: True se la riga è stata creata ora.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session.session_id, session.started_at),
            )
            return cur.rowcount > 0

    def mark_stopped(self, session_id: str, stopped_at: float, row_count: int | None = None) -> None:
        """Chiude una sessione già presente. row_count None lascia invariato
        il valore esistente (COALESCE), così una chiusura per supersede non
        cancella un conteggio scritto da uno stop precedente."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET stopped_at = ?, row_count = COALESCE(?, row_count) "
                "WHERE session_id = ?",
                (stopped_at, row_count, session_id),
            )

    def set_row_count(self, session_id: str, row_count: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET row_count = ? WHERE session_id = ?",
                (row_count, session_id),
            )

    def exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None
