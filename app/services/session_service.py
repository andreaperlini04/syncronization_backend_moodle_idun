import time
import uuid
from threading import Lock

from app.models.session import Session
from app.repository.session_repository import SessionRepository


class SessionAlreadyActiveError(Exception):
    def __init__(self, active_session_id: str):
        self.active_session_id = active_session_id
        super().__init__(f"Sessione già attiva: {active_session_id}")


class NoActiveSessionError(Exception):
    pass


class SessionService:
    """Gestisce la sessione attiva corrente. Stato in memoria, non persistito:
    se il backend si riavvia a metà sessione, la sessione va comunque
    considerata interrotta e riavviata manualmente."""

    def __init__(self, session_repository: SessionRepository):
        self._repo = session_repository
        self._current: Session | None = None
        self._lock = Lock()

    def start(self) -> Session:
        with self._lock:
            if self._current is not None:
                raise SessionAlreadyActiveError(self._current.session_id)
            self._current = Session(session_id=self._generate_id(), started_at=time.time())
            return self._current

    def stop(self) -> Session:
        with self._lock:
            if self._current is None:
                raise NoActiveSessionError()
            session = self._current
            session.stopped_at = time.time()
            self._current = None
            return session

    def current_session_id(self) -> str | None:
        with self._lock:
            return self._current.session_id if self._current else None

    def is_known_session(self, session_id: str) -> bool:
        """True se session_id è la sessione attiva corrente, o compare nello
        storico delle sessioni già chiuse (utile per l'ultimo flush di
        eeg_uploader dopo uno STOP)."""
        with self._lock:
            if self._current is not None and self._current.session_id == session_id:
                return True
        return self._repo.exists(session_id)

    @staticmethod
    def _generate_id() -> str:
        return f"sess_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"