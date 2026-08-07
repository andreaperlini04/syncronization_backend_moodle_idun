import json
import time

from app.models.timeline_entry import TimelineEntry
from app.repository.timeline_repository import TimelineRepository
from app.services.session_service import SessionService


class UnknownSessionError(Exception):
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"session_id sconosciuto: {session_id}")


class TimelineService:
    """Logica di dominio per scrivere sulla timeline. Non sa nulla di Flask."""

    def __init__(self, timeline_repository: TimelineRepository, session_service: SessionService):
        self._timeline_repo = timeline_repository
        self._session_service = session_service

    def record_moodle_event(self, event_type: str, payload: dict) -> str | None:
        """Registra un evento dal plugin Moodle. session_id assegnato in
        automatico dalla sessione attiva corrente (None se nessuna attiva)."""
        session_id = self._session_service.current_session_id()
        entry = TimelineEntry(
            session_id=session_id,
            ts=time.time(),
            source="moodle",
            event_type=event_type,
            payload=json.dumps(payload),
        )
        self._timeline_repo.insert_event(entry)
        return session_id

    def record_eeg_rows(self, session_id: str, rows: list[dict]) -> int:
        """Registra un chunk (o batch) di band power dall'app IDUN.
        session_id deve essere noto (attivo o già chiuso), altrimenti errore."""
        if not self._session_service.is_known_session(session_id):
            raise UnknownSessionError(session_id)

        arrival_ts = time.time()
        entries = [
            TimelineEntry(
                session_id=session_id,
                # Se la riga non porta un ts proprio, si usa l'arrivo del
                # chunk con un piccolo offset per indice: senza offset, righe
                # multiple nello stesso chunk senza ts esplicito avrebbero
                # tutte lo stesso valore e il vincolo UNIQUE ne scarterebbe
                # la maggior parte come falsi duplicati.
                ts=row.get("ts", arrival_ts + i * 1e-6),
                source="eeg",
                event_type=row.get("event_type", "band_power"),
                payload=json.dumps(row.get("payload", {})),
            )
            for i, row in enumerate(rows)
        ]
        return self._timeline_repo.insert_many(entries)

    def count_for_session(self, session_id: str) -> int:
        return self._timeline_repo.count_for_session(session_id)
