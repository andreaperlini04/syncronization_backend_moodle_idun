import json
import time

from app.models.timeline_entry import TimelineEntry
from app.repository.clock_skew_repository import ClockSkewRepository
from app.repository.timeline_repository import TimelineRepository
from app.services.moodle_descriptions import describe
from app.services.session_service import SessionService


class UnknownSessionError(Exception):
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"session_id sconosciuto: {session_id}")


class TimelineService:
    """Logica di dominio per scrivere sulla timeline. Non sa nulla di Flask."""

    def __init__(
        self,
        timeline_repository: TimelineRepository,
        session_service: SessionService,
        clock_skew_repository: ClockSkewRepository,
    ):
        self._timeline_repo = timeline_repository
        self._session_service = session_service
        self._clock_skew_repo = clock_skew_repository

    # ------------------------------------------------------------------ #
    #  Ingestione unificata (contratto client -> backend)                 #
    # ------------------------------------------------------------------ #

    def ingest(self, events: list) -> dict:
        """Registra un array di eventi nell'envelope comune alle due sorgenti:

            {"session_id", "timestamp", "source", "event_type", "payload"}

        Un evento malformato viene contato e saltato, non fa fallire l'intera
        richiesta: il client non ha retry automatico, quindi un 400 su una riga
        sola costerebbe l'intera sessione (300-800 campioni).

        L'inserimento è idempotente sulla chiave (session_id, source,
        event_type, ts) del vincolo UNIQUE: un reinvio manuale della stessa
        sessione non duplica nulla.

        Returns:
            dict: riepilogo (ricevuti, inseriti, duplicati, sessioni toccate).
        """
        entries: list[TimelineEntry] = []
        invalid = 0
        skew_samples = 0
        opened: list[str] = []
        superseded: list[str] = []
        closed: list[str] = []
        registered: list[str] = []

        for raw in events:
            if not isinstance(raw, dict):
                invalid += 1
                continue

            source = raw.get("source")
            event_type = raw.get("event_type")
            if not source or not event_type:
                invalid += 1
                continue

            ts = self._coerce_ts(raw.get("timestamp"))
            payload = raw.get("payload")
            if not isinstance(payload, dict):
                # Payload non-oggetto: conservato comunque, incapsulato, così
                # il dato non va perso e la colonna resta sempre un JSON object.
                payload = {} if payload is None else {"value": payload}
            session_id = raw.get("session_id") or None
            description = raw.get("description")

            if event_type == "session_start":
                if not session_id:
                    # Senza id la sessione non è correlabile con Moodle:
                    # è il solo caso in cui l'evento è inutilizzabile.
                    invalid += 1
                    continue
                _, sup = self._session_service.open_session(session_id, ts)
                opened.append(session_id)
                if sup:
                    superseded.append(sup)

            elif event_type == "session_end":
                # Non previsto dal contratto attuale (lo Stop si deduce
                # dall'arrivo del batch), ma gestito: se il client lo aggiunge
                # non serve toccare il backend.
                if session_id:
                    self._session_service.close_session(session_id, ts)
                    closed.append(session_id)

            elif event_type == "clock_skew_measured":
                # Telemetria sulla misura, non comportamento: tabella separata.
                self._clock_skew_repo.insert(
                    session_id=session_id or self._session_service.current_session_id(),
                    ts=ts,
                    skew_ms=payload.get("skew_ms", 0),
                    uncertainty_ms=payload.get("uncertainty_ms", 0),
                    rtt_min_ms=payload.get("rtt_min_ms", 0),
                    samples=payload.get("samples", 0),
                    payload=json.dumps(payload),
                )
                skew_samples += 1
                continue

            if source == "eeg":
                if not session_id:
                    invalid += 1
                    continue
                # Se la POST di session_start è fallita il client registra
                # comunque in locale: la sessione arriva qui solo allo Stop,
                # e va accettata invece che rifiutata con 404.
                if self._session_service.ensure_registered(session_id, ts):
                    registered.append(session_id)
            else:
                # Il plugin Moodle non conosce il session_id: glielo assegna il
                # backend, prendendo quello della sessione EEG attiva. Se non ce
                # n'è nessuna la riga resta con session_id NULL invece di essere
                # scartata: l'evento è comunque riallineabile per timestamp.
                session_id = session_id or self._session_service.current_session_id()
                if description is None:
                    description = describe(event_type, payload)

            entries.append(
                TimelineEntry(
                    session_id=session_id,
                    ts=ts,
                    source=source,
                    event_type=event_type,
                    payload=json.dumps(payload),
                    description=description or "",
                )
            )

        inserted = self._timeline_repo.insert_many(entries)

        # row_count aggiornato dopo l'inserimento: un session_end può arrivare
        # nella stessa richiesta dei campioni che deve contare.
        for session_id in closed:
            self._session_service.update_row_count(
                session_id, self._timeline_repo.count_for_session(session_id)
            )

        return {
            "received": len(events),
            "stored": inserted,
            "duplicates": len(entries) - inserted,
            "invalid": invalid,
            "clock_skew_samples": skew_samples,
            "sessions_opened": opened,
            "sessions_superseded": superseded,
            "sessions_closed": closed,
            "sessions_autoregistered": registered,
        }

    @staticmethod
    def _coerce_ts(value) -> float:
        """Timestamp del contratto: epoch in secondi, float.

        Tollera i millisecondi (il plugin Moodle lavora in ms): un epoch in
        secondi supera 1e11 solo nell'anno 5138, quindi la soglia discrimina
        senza ambiguità. Valore assente o non numerico -> istante di arrivo.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return time.time()
        value = float(value)
        if value <= 0:
            return time.time()
        return value / 1000 if value > 1e11 else value

    def record_moodle_event(
        self,
        event_type: str,
        payload: dict,
        description: str | None = None,
        ts_ms: float | None = None,
    ) -> str | None:
        """Registra un evento dal plugin Moodle. session_id assegnato in
        automatico dalla sessione attiva corrente (None se nessuna attiva).

        description/ts_ms: usati dagli eventi relayati dal server Moodle
        (già passati per event_writer::write() lato PHP, con description
        già calcolata e timestamp originale corretto per lo skew). Se
        assenti (eventi client "in diretta"), si comporta come prima:
        description calcolata qui, ts = arrivo al backend.

        clock_skew_measured non finisce in timeline: è telemetria
        diagnostica sulla misura stessa, non comportamento dello studente."""
        session_id = self._session_service.current_session_id()
        ts = ts_ms / 1000 if ts_ms is not None else time.time()

        if event_type == "clock_skew_measured":
            self._clock_skew_repo.insert(
                session_id=session_id,
                ts=ts,
                skew_ms=payload.get("skew_ms", 0),
                uncertainty_ms=payload.get("uncertainty_ms", 0),
                rtt_min_ms=payload.get("rtt_min_ms", 0),
                samples=payload.get("samples", 0),
                payload=json.dumps(payload),
            )
            return session_id

        entry = TimelineEntry(
            session_id=session_id,
            ts=ts,
            source="moodle",
            event_type=event_type,
            payload=json.dumps(payload),
            description=description if description is not None else describe(event_type, payload),
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