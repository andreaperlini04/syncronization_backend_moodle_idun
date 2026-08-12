import sqlite3
from pathlib import Path
from threading import Lock

from app.models.timeline_entry import TimelineEntry


class TimelineRepository:
    """Unico punto che tocca la tabella 'timeline'. Nessuna logica di dominio qui."""

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
                CREATE TABLE IF NOT EXISTS timeline (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT,
                    ts          REAL    NOT NULL,
                    source      TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    payload     TEXT    NOT NULL,
                    description TEXT    NOT NULL DEFAULT '',
                    UNIQUE(session_id, source, event_type, ts)
                )
                """
            )
            # Migrazione idempotente: se la tabella esiste già da prima
            # dell'introduzione di questa colonna, aggiungerla qui. SQLite
            # non supporta "ADD COLUMN IF NOT EXISTS", quindi si tenta e si
            # ignora l'errore se la colonna c'è già.
            try:
                conn.execute("ALTER TABLE timeline ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # NB: in SQLite, righe con session_id = NULL sono considerate
            # sempre distinte dal vincolo UNIQUE (NULL != NULL), quindi gli
            # eventi fuori sessione non vengono mai scartati per errore.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_session ON timeline(session_id, ts)"
            )

    def insert_many(self, entries: list[TimelineEntry]) -> int:
        """Inserimento bulk (usato per i chunk EEG). Idempotente: un chunk
        rispedito dopo un timeout di rete non duplica righe già presenti."""
        if not entries:
            return 0
        rows = [
            (e.session_id, e.ts, e.source, e.event_type, e.payload, e.description) for e in entries
        ]
        with self._lock, self._connect() as conn:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO timeline "
                "(session_id, ts, source, event_type, payload, description) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            return cur.rowcount

    def count_for_session(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM timeline WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row[0]