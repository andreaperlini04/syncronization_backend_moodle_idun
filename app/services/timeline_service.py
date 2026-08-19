import json

from app.models.timeline_entry import TimelineEntry
from app.repository.clock_skew_repository import ClockSkewRepository
from app.repository.timeline_repository import TimelineRepository
from app.services.moodle_descriptions import describe
from app.services.session_service import SessionService


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

        'timestamp' è obbligatorio e non ha ripiego: senza, l'evento è
        scartato e contato in 'no_timestamp'. Il perché è in _coerce_ts.

        L'inserimento è idempotente sulla chiave (session_id, source,
        event_type, ts) del vincolo UNIQUE: un reinvio manuale della stessa
        sessione non duplica nulla.

        L'attribuzione allo studente è per sessione: l'user_id arriva solo
        dagli eventi Moodle, e da lì si estende a tutte le righe della stessa
        sessione, campioni EEG compresi.

        Returns:
            dict: riepilogo (ricevuti, inseriti, duplicati, sessioni toccate).
        """
        entries: list[TimelineEntry] = []
        invalid = 0
        no_timestamp = 0
        skew_samples = 0
        opened: list[str] = []
        superseded: list[str] = []
        closed: list[str] = []
        registered: list[str] = []
        attributable: set[str] = set()

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
            if ts is None:
                # Contatore separato da 'invalid': un batch che perde righe
                # per timestamp mancante è quasi sempre una regressione nella
                # serializzazione del client (null, stringa, 0), non un
                # evento malformato isolato. Distinguerlo lo rende
                # diagnosticabile dalla sola risposta.
                no_timestamp += 1
                continue

            payload = raw.get("payload")
            if not isinstance(payload, dict):
                # Payload non-oggetto: conservato comunque, incapsulato, così
                # il dato non va perso e la colonna resta sempre un JSON object.
                payload = {} if payload is None else {"value": payload}
            session_id = raw.get("session_id") or None
            description = raw.get("description")
            user_id = raw.get("user_id")
            if user_id is None and isinstance(payload.get("context"), dict):
                user_id = payload["context"].get("user_id")

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
                # Lo Stop si deduce di norma dall'arrivo del batch finale;
                # se il client invia esplicitamente session_end, l'evento
                # chiude comunque la sessione indicata.
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
            elif source == "moodle":
                # Il plugin Moodle non conosce il session_id: glielo assegna il
                # backend, prendendo quello della sessione EEG attiva. Se non ce
                # n'è nessuna la riga resta con session_id NULL invece di essere
                # scartata: l'evento è comunque riallineabile per timestamp.
                session_id = session_id or self._session_service.current_session_id()
                if description is None:
                    description = describe(event_type, payload)
            else:
                # source valorizzato ma diverso da "eeg"/"moodle": nessuno
                # dei due schemi di attribuzione si applica. Scartato invece
                # di essere instradato come Moodle per esclusione.
                invalid += 1
                continue

            if session_id:
                # Attribuzione per sessione. Il client EEG non conosce
                # l'utente Moodle, ma i due lati condividono il session_id:
                # l'utente si impara dal plugin e si stampa su tutto il resto
                # della sessione. Vale anche per un evento Moodle senza
                # user_id proprio, che è comunque dello stesso studente.
                if user_id is not None:
                    self._session_service.attach_user(session_id, user_id)
                else:
                    user_id = self._session_service.user_for(session_id)
                attributable.add(session_id)

            entries.append(
                TimelineEntry(
                    session_id=session_id,
                    ts=ts,
                    source=source,
                    event_type=event_type,
                    payload=json.dumps(payload),
                    description=description or "",
                    user_id=user_id, 
                )
            )

        inserted = self._timeline_repo.insert_many(entries)

        # Recupero delle righe scritte prima che l'utente fosse noto. Copre
        # tre casi che l'attribuzione in corsa non può prendere: session_start,
        # che precede sempre il primo evento Moodle; i campioni EEG arrivati in
        # una richiesta anteriore a qualsiasi attività nel browser; e gli
        # eventi dello stesso lotto costruiti prima dell'evento che porta
        # l'user_id, dato che le entry si assemblano tutte prima dell'INSERT.
        attributed = 0
        for session_id in attributable:
            user_id = self._session_service.user_for(session_id)
            if user_id is not None:
                attributed += self._timeline_repo.assign_user(session_id, user_id)

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
            "no_timestamp": no_timestamp,
            "clock_skew_samples": skew_samples,
            "rows_attributed": attributed,
            "sessions_opened": opened,
            "sessions_superseded": superseded,
            "sessions_closed": closed,
            "sessions_autoregistered": registered,
        }

    @staticmethod
    def _coerce_ts(value) -> float | None:
        """Timestamp del contratto: epoch in secondi, float.

        Tollera i millisecondi (il plugin Moodle lavora in ms interi, 13
        cifre): un epoch in secondi supera 1e11 solo nell'anno 5138, mentre
        1e11 ms è il 1973, quindi la soglia discrimina senza ambiguità.

        Nessun ripiego sull'ora di arrivo al backend, ed è deliberato: il
        ritardo di rete e di accodamento è ignoto e variabile, quindi un
        timestamp inventato posizionerebbe l'evento nel punto sbagliato
        della timeline. Dato che l'intero scopo del sistema è correlare EEG
        e attività Moodle nel tempo, un evento mal posizionato è peggio di
        un evento mancante: il primo falsifica l'analisi in silenzio, il
        secondo si conta in 'no_timestamp'.

        Returns:
            float | None: None se il valore è assente, non numerico o <= 0.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        if value <= 0:
            return None
        return value / 1000 if value > 1e11 else value