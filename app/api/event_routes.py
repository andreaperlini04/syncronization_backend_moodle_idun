from flask import Blueprint, jsonify, request

from app.api.errors import error_response
from app.services.timeline_service import TimelineService


def create_event_routes(timeline_service: TimelineService) -> Blueprint:
    bp = Blueprint("event_routes", __name__)

    @bp.route("/event", methods=["POST"])
    def receive_event():
        data = request.get_json(silent=True)
        if not data:
            return error_response("INVALID_BODY", "Body JSON mancante o non valido", 400)

        event_type = data.get("event_type")
        if not event_type:
            return error_response("MISSING_EVENT_TYPE", "event_type è obbligatorio", 400)

        payload = data.get("payload", {})
        description = data.get("description")  
        ts_ms = data.get("ts_ms")               # None -> usa l'arrivo al backend
        session_id = timeline_service.record_moodle_event(
            event_type, payload, description=description, ts_ms=ts_ms
        )

        return jsonify({"recorded": True, "session_id": session_id})

    return bp