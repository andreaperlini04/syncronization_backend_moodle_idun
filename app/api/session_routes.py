from flask import Blueprint, jsonify

from app.api.errors import error_response
from app.repository.session_repository import SessionRepository
from app.services.session_service import NoActiveSessionError, SessionAlreadyActiveError, SessionService
from app.services.timeline_service import TimelineService


def create_session_routes(
    session_service: SessionService,
    session_repository: SessionRepository,
    timeline_service: TimelineService,
) -> Blueprint:
    bp = Blueprint("session_routes", __name__)

    @bp.route("/start-session", methods=["POST"])
    def start_session():
        try:
            session = session_service.start()
        except SessionAlreadyActiveError as e:
            return error_response(
                "SESSION_ALREADY_ACTIVE",
                f"Sessione già attiva: {e.active_session_id}",
                409,
            )
        return jsonify({"session_id": session.session_id, "started_at": session.started_at})

    @bp.route("/stop-session", methods=["POST"])
    def stop_session():
        try:
            session = session_service.stop()
        except NoActiveSessionError:
            return error_response("NO_ACTIVE_SESSION", "Nessuna sessione attiva da fermare", 400)

        session.row_count = timeline_service.count_for_session(session.session_id)
        session_repository.save_closed(session)

        return jsonify(
            {
                "session_id": session.session_id,
                "stopped_at": session.stopped_at,
                "row_count": session.row_count,
            }
        )

    return bp
