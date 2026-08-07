from flask import Flask

from app.api.eeg_routes import create_eeg_routes
from app.api.event_routes import create_event_routes
from app.api.session_routes import create_session_routes
from app.config import Config
from app.repository.session_repository import SessionRepository
from app.repository.timeline_repository import TimelineRepository
from app.services.session_service import SessionService
from app.services.timeline_service import TimelineService
from app.api.cors import register_cors    


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    register_cors(app)

    # Repository (accesso dati)
    timeline_repository = TimelineRepository(app.config["DB_PATH"])
    timeline_repository.init_schema()
    session_repository = SessionRepository(app.config["DB_PATH"])
    session_repository.init_schema()

    # Service (logica di dominio) — dependency injection manuale, esplicita
    session_service = SessionService(session_repository)
    timeline_service = TimelineService(timeline_repository, session_service)

    # API (blueprint)
    app.register_blueprint(
        create_session_routes(session_service, session_repository, timeline_service)
    )
    app.register_blueprint(create_event_routes(timeline_service))
    app.register_blueprint(create_eeg_routes(timeline_service))

    return app
