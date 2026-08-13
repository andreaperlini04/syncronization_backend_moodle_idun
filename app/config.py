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


class TestConfig(Config):
    """Configurazione per i test. DB_PATH non è fissato qui: ogni repository
    apre una connessione sqlite3 per operazione, quindi con ':memory:' ogni
    connessione vedrebbe un database vuoto diverso e init_schema() non
    servirebbe a nulla. La fixture 'app' in tests/conftest.py assegna un
    file temporaneo per test (pytest tmp_path), isolato e ripulito da solo."""

    DEBUG = True
    TESTING = True