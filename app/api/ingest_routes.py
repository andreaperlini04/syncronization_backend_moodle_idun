from flask import Blueprint, jsonify, request

from app.api.errors import error_response
from app.services.timeline_service import TimelineService


def create_ingest_routes(timeline_service: TimelineService) -> Blueprint:
    """Endpoint unico del contratto client -> backend.

    Riceve gli eventi di entrambe le sorgenti (client EEG e plugin Moodle)
    nell'envelope comune; la discriminazione avviene sui campi source /
    event_type, non sull'URL.
    """

    bp = Blueprint("ingest_routes", __name__)

    @bp.route("/api/sessions", methods=["POST"])
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

        # 201 come il mock su cui il client è stato provato. Il client tratta
        # come successo qualsiasi 2xx e logga il body senza interpretarlo: il
        # riepilogo serve al debug manuale (curl) e ai test.
        return jsonify(result), 201

    return bp
