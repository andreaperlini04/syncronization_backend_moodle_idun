from flask import Blueprint, jsonify, request

from app.api.errors import error_response
from app.services.timeline_service import TimelineService, UnknownSessionError


def create_eeg_routes(timeline_service: TimelineService) -> Blueprint:
    bp = Blueprint("eeg_routes", __name__)

    @bp.route("/eeg-upload", methods=["POST"])
    def receive_eeg_upload():
        data = request.get_json(silent=True)
        if not data:
            return error_response("INVALID_BODY", "Body JSON mancante o non valido", 400)

        session_id = data.get("session_id")
        rows = data.get("rows")
        if not session_id or not rows:
            return error_response("MISSING_FIELDS", "session_id e rows sono obbligatori", 400)

        try:
            inserted = timeline_service.record_eeg_rows(session_id, rows)
        except UnknownSessionError:
            return error_response("UNKNOWN_SESSION", f"session_id sconosciuto: {session_id}", 404)

        return jsonify({"received": len(rows), "inserted": inserted})

    return bp
