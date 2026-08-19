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
                    row_count   INTEGER,
                    user_id     INTEGER
                )
                """
            )
            # Migrazione idempotente sui database già popolati: SQLite non
            # supporta "ADD COLUMN IF NOT EXISTS", quindi si tenta e si
            # ignora l'errore se la colonna c'è già.
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
            except sqlite3.OperationalError:
                pass

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

    def attach_user(self, session_id: str, user_id: int) -> None:
        """Associa lo studente alla sessione, se non ne ha già uno.

        COALESCE invece di un UPDATE secco: il primo utente osservato vince e
        resta. Una sessione appartiene a uno studente solo, quindi un secondo
        user_id sulla stessa sessione è un'anomalia (due browser, due account
        sulla stessa macchina) e non deve riscrivere l'attribuzione già data
        alle righe della timeline.
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET user_id = COALESCE(user_id, ?) WHERE session_id = ?",
                (user_id, session_id),
            )

    def user_for(self, session_id: str) -> int | None:
        """Studente della sessione, None se sconosciuto o sessione assente."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row[0] if row else None

    def exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None
