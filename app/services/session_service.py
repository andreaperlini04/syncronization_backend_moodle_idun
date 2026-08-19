from threading import Lock

from app.models.session import Session
from app.repository.session_repository import SessionRepository


class SessionService:
    """Gestisce la sessione attiva corrente. Stato in memoria, non persistito:
    se il backend si riavvia a metà sessione, la sessione va comunque
    considerata interrotta e riavviata manualmente.

    L'id della sessione lo decide sempre il client EEG e arriva con l'evento
    session_start: unica autorità sull'id, così l'attribuzione degli eventi
    Moodle non è mai ambigua."""

    def __init__(self, session_repository: SessionRepository):
        self._repo = session_repository
        self._current: Session | None = None
        self._lock = Lock()
        # Cache dei session_id già visti: evita una SELECT per ogni campione
        # di un batch da 800 righe.
        self._known: set[str] = set()
        # session_id -> studente Moodle. Un session_id presente con valore
        # None significa "già cercato, non lo sa nessuno": senza questo caso
        # negativo un batch EEG di una sessione senza utente farebbe una
        # SELECT per campione.
        self._users: dict[str, int | None] = {}

    def open_session(self, session_id: str, started_at: float) -> tuple[Session, str | None]:
        """Apre la sessione con l'id deciso dal client EEG (evento session_start).

        Non solleva se una sessione è già attiva: il client permette
        Start -> Stop -> Start e, se lo Stop non arriva (crash, finestra
        chiusa), la sessione precedente resterebbe aperta per sempre.
        Una sola sessione attiva alla volta, l'ultimo session_start vince: gli
        eventi Moodle successivi hanno così un'attribuzione non ambigua.

        Returns:
            tuple: (sessione aperta, session_id superseduto o None).
        """
        with self._lock:
            superseded = None
            if self._current is not None and self._current.session_id != session_id:
                superseded = self._current.session_id
                self._current.stopped_at = started_at
                self._repo.mark_stopped(superseded, started_at)

            session = Session(session_id=session_id, started_at=started_at)
            self._current = session
            self._known.add(session_id)

        self._repo.save_open(session)
        return session, superseded

    def close_session(self, session_id: str, stopped_at: float) -> None:
        """Chiude la sessione indicata. Tollera un session_id non attivo: un
        session_end può arrivare dopo un supersede o un riavvio del backend."""
        with self._lock:
            if self._current is not None and self._current.session_id == session_id:
                self._current.stopped_at = stopped_at
                self._current = None
        self._repo.mark_stopped(session_id, stopped_at)

    def update_row_count(self, session_id: str, row_count: int) -> None:
        self._repo.set_row_count(session_id, row_count)

    def ensure_registered(self, session_id: str, started_at: float) -> bool:
        """Registra una sessione mai annunciata da un session_start.

        Serve perché il client, se la POST di session_start fallisce, prosegue
        comunque la registrazione locale e allo Stop invia i campioni: scartarli
        significherebbe perdere la sessione. Non rende la sessione attiva.

        Returns:
            bool: True se la sessione era sconosciuta ed è stata creata ora.
        """
        with self._lock:
            if session_id in self._known:
                return False
            self._known.add(session_id)

        if self._repo.exists(session_id):
            return False
        return self._repo.save_open(Session(session_id=session_id, started_at=started_at))

    def attach_user(self, session_id: str, user_id: int) -> bool:
        """Registra lo studente di una sessione, appreso da un evento Moodle.

        Il client EEG non conosce l'utente Moodle: l'unico modo di attribuire
        i campioni a uno studente è passare per la sessione, che il plugin e
        il client condividono. Il primo utente osservato vince, qui e sul
        database (vedi SessionRepository.attach_user).

        Returns:
            bool: True se la sessione non aveva ancora un utente.
        """
        with self._lock:
            if self._users.get(session_id) is not None:
                return False
            self._users[session_id] = user_id

        self._repo.attach_user(session_id, user_id)
        return True

    def user_for(self, session_id: str) -> int | None:
        """Studente della sessione, None se ancora sconosciuto.

        Cache in memoria davanti al database: la memoria basta finché il
        backend resta acceso, il database copre il caso in cui i campioni di
        una sessione arrivino dopo un riavvio (vedi ensure_registered).
        """
        with self._lock:
            if session_id in self._users:
                return self._users[session_id]

        user_id = self._repo.user_for(session_id)

        with self._lock:
            # Non sovrascrive un utente appreso nel frattempo da un evento
            # Moodle: quello è più fresco della SELECT appena fatta.
            if self._users.get(session_id) is None:
                self._users[session_id] = user_id
            return self._users[session_id]

    def current_session_id(self) -> str | None:
        with self._lock:
            return self._current.session_id if self._current else None