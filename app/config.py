class Config:
    """Configurazione di default (sviluppo)."""

    DB_PATH = "sessions/timeline.db"
    HOST = "localhost"
    PORT = 5000
    DEBUG = False


    ALLOWED_ORIGINS = [
        "https://upraisemoodle.dti.supsi.ch",  # Moodle SUPSI (remoto)
        "http://localhost:8080",                # Moodle locale in Docker
    ]


# TestConfig (DB_PATH in memoria/temporaneo, ecc.) verrà aggiunta insieme ai test.