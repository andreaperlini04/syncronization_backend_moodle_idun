import sqlite3

import pytest

from app import create_app
from app.config import TestConfig


@pytest.fixture
def app(tmp_path):
    """App Flask con database su file temporaneo, uno per test.

    Il file serve: ':memory:' darebbe a ogni connessione un database vuoto
    diverso, e i repository ne aprono una per operazione. tmp_path è una
    fixture pytest, la cartella viene ripulita da sola.
    """

    class _AppConfig(TestConfig):
        DB_PATH = str(tmp_path / "test.db")

    return create_app(_AppConfig)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_path(app):
    return app.config["DB_PATH"]


@pytest.fixture
def db_conn(db_path):
    """Connessione a parte per leggere quello che l'app ha scritto, come
    fanno check_db.py e check_skew.py."""
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()
