class Config:
    """Configurazione di default (sviluppo)."""

    DB_PATH = "sessions/timeline.db"
    HOST = "127.0.0.1"
    PORT = 8000          # porta attesa dal client EEG (BACKEND_URL del contratto)
    DEBUG = False

    # Il batch di campioni inviato allo Stop contiene 300-800 eventi: qualche
    # centinaio di kB. Limite alto apposta, per non troncare sessioni lunghe.
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024


    ALLOWED_ORIGINS = [
        "https://upraisemoodle.dti.supsi.ch",  # Moodle SUPSI (remoto)
        "http://localhost:8080",                # Moodle locale in Docker
    ]


# TestConfig (DB_PATH in memoria/temporaneo, ecc.) verrà aggiunta insieme ai test.