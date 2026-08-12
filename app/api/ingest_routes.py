from flask import Blueprint, jsonify, request

from app.api.errors import error_response
from app.services.timeline_service import TimelineService


def create_ingest_routes(timeline_service: TimelineService) -> Blueprint:
    """Endpoint unico del contratto client -> backend.

    Riceve gli eventi di entrambe le sorgenti (client EEG e plugin Moodle)
    nell'envelope comune; la discriminazione avviene sui campi source /
    event_type, non sull'URL.

    Lo stream è un log append-only di eventi eterogenei: session_start,
    session_end e clock_skew_measured sono eventi come gli altri, e la
    sessione è una proiezione sullo stream, non una risorsa parallela.
    Da qui il nome /api/v1/events: si inviano eventi, la timeline è ciò
    che il backend ne ricava.
    """

    bp = Blueprint("ingest_routes", __name__)

    @bp.route("/api/v1/events", methods=["POST"])
    def ingest_events():
        events = request.get_json(silent=True)
        if events is None:
            return error_response("INVALID_BODY", "Body JSON mancante o non valido", 400)

        # Il contratto prevede sempre un array, anche per un solo evento.
        # Un oggetto singolo viene comunque accettato: costa una riga e
        # rende il backend compatibile con la variante indicata come
        # modifica a basso costo lato client.
        if isinstance(events, dict):
            events = [events]
        if not isinstance(events, list):
            return error_response("INVALID_BODY", "Atteso un array di eventi", 400)

        result = timeline_service.ingest(events)

        return jsonify(result), 201

    return bp
