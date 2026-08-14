"""Test di SessionService in isolamento: niente Flask, niente HTTP.

Il repository è quello vero su file temporaneo — la parte interessante è
proprio come stato in memoria e stato su disco restano allineati.
"""

import sqlite3

import pytest

from app.repository.session_repository import SessionRepository
from app.services.session_service import SessionService


@pytest.fixture
def session_db(tmp_path):
    return str(tmp_path / "sessions.db")


@pytest.fixture
def service(session_db):
    repo = SessionRepository(session_db)
    repo.init_schema()
    return SessionService(repo)


def stored_session(session_db, session_id):
    """Riga della tabella sessions, o None se assente."""
    conn = sqlite3.connect(session_db)
    try:
        return conn.execute(
            "SELECT started_at, stopped_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()


def test_no_active_session_initially(service):
    assert service.current_session_id() is None


def test_open_session_becomes_current(service):
    session, superseded = service.open_session("s1", 100.0)

    assert session.session_id == "s1"
    assert superseded is None
    assert service.current_session_id() == "s1"


def test_open_session_with_new_id_supersedes_previous(service):
    service.open_session("s1", 100.0)

    session, superseded = service.open_session("s2", 200.0)

    assert session.session_id == "s2"
    assert superseded == "s1"
    assert service.current_session_id() == "s2"


def test_open_session_with_same_id_does_not_supersede(service):
    """Un session_start ripetuto con lo stesso id — reinvio, doppio click —
    non deve chiudere la sessione che sta già identificando."""
    service.open_session("s1", 100.0)

    _, superseded = service.open_session("s1", 150.0)

    assert superseded is None
    assert service.current_session_id() == "s1"


def test_superseded_session_is_marked_stopped_on_disk(service, session_db):
    service.open_session("s1", 100.0)
    service.open_session("s2", 200.0)

    assert stored_session(session_db, "s1")[1] == 200.0


def test_close_session_clears_current(service):
    service.open_session("s1", 100.0)

    service.close_session("s1", 150.0)

    assert service.current_session_id() is None


def test_close_session_tolerates_non_active_id(service):
    """Un session_end tardivo, arrivato dopo che la sua sessione è stata
    soppiantata, non deve chiudere quella attiva al suo posto."""
    service.open_session("s1", 100.0)
    service.open_session("s2", 200.0)

    service.close_session("s1", 250.0)

    assert service.current_session_id() == "s2"


def test_ensure_registered_creates_unknown_session(service, session_db):
    created = service.ensure_registered("s_mai_annunciata", 100.0)

    assert created is True
    assert stored_session(session_db, "s_mai_annunciata") is not None


def test_ensure_registered_does_not_activate_the_session(service):
    """Recupera i dati di un client che ha perso la POST di session_start,
    ma non le dà lo stato di sessione corrente: gli eventi Moodle in arrivo
    non devono finire attribuiti a una sessione mai annunciata."""
    service.ensure_registered("s1", 100.0)

    assert service.current_session_id() is None


def test_ensure_registered_is_a_noop_for_already_known_session(service):
    first = service.ensure_registered("s1", 100.0)
    second = service.ensure_registered("s1", 999.0)

    assert first is True
    assert second is False


def test_ensure_registered_does_not_overwrite_started_at(service, session_db):
    """Il secondo tentativo porta un timestamp diverso: la riga già scritta
    non va toccata, altrimenti l'inizio sessione slitterebbe al primo
    campione di ogni batch successivo."""
    service.ensure_registered("s1", 100.0)
    service.ensure_registered("s1", 999.0)

    assert stored_session(session_db, "s1")[0] == 100.0


def test_ensure_registered_recognises_session_opened_via_open_session(service):
    """Una sessione annunciata regolarmente non va contata fra le
    autoregistrate: il riepilogo segnalerebbe un problema inesistente."""
    service.open_session("s1", 100.0)

    assert service.ensure_registered("s1", 100.0) is False
