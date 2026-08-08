import sqlite3
from pathlib import Path
from threading import Lock


class ClockSkewRepository:
    """Campioni di misura dello skew fra clock server Moodle e clock locale.

    Tabella separata da 'timeline' apposta: sono telemetria diagnostica
    sull'infrastruttura di misura, non comportamento dello studente — non
    ha senso vederli mescolati quando si sfoglia la timeline per l'analisi."""

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
                CREATE TABLE IF NOT EXISTS clock_skew (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id      TEXT,
                    ts              REAL    NOT NULL,
                    skew_ms         REAL    NOT NULL,
                    uncertainty_ms  REAL    NOT NULL,
                    rtt_min_ms      REAL    NOT NULL,
                    samples         INTEGER NOT NULL,
                    payload         TEXT    NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clock_skew_ts ON clock_skew(ts)")

    def insert(
        self,
        session_id: str | None,
        ts: float,
        skew_ms: float,
        uncertainty_ms: float,
        rtt_min_ms: float,
        samples: int,
        payload: str,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO clock_skew "
                "(session_id, ts, skew_ms, uncertainty_ms, rtt_min_ms, samples, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, ts, skew_ms, uncertainty_ms, rtt_min_ms, samples, payload),
            )