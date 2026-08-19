"""Test di integrazione su POST /api/v1/events.

Attraversa tutti i livelli veri — route, servizio, repository, SQLite — senza
mock: si verifica quello che finisce in tabella, non quello che il servizio
dichiara di aver fatto.
"""

import json

import pytest

from app import create_app
from app.config import TestConfig

# Sentinella per distinguere "campo assente" da "campo presente con valore
# null": passano entrambi per _coerce_ts, ma sono due errori diversi lato
# client e vanno verificati separatamente.
OMITTED = object()


def post(client, events):
    return client.post("/api/v1/events", json=events)


def timeline_rows(db_conn):
    # user_id resta in coda: gli indici usati altrove non si spostano.
    return db_conn.execute(
        "SELECT session_id, ts, source, event_type, description, payload, user_id "
        "FROM timeline ORDER BY id"
    ).fetchall()


def rows_by_source(db_conn):
    return {row[2]: row for row in timeline_rows(db_conn)}


def stored_user_id(db_conn):
    """user_id dell'unica riga in timeline."""
    return timeline_rows(db_conn)[0][6]


def user_ids_of(db_conn, source):
    """user_id di tutte le righe di una sorgente, in ordine di inserimento."""
    return [row[6] for row in timeline_rows(db_conn) if row[2] == source]


def session_user_id(db_conn, session_id):
    row = db_conn.execute(
        "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row[0] if row else None


def start_session(client, session_id="s1", ts=1786544500.0):
    return post(client, [{"session_id": session_id, "timestamp": ts,
                          "source": "eeg", "event_type": "session_start", "payload": {}}])


def moodle_event(ts, user_id=None, event_type="page_loaded"):
    """Evento del plugin con l'user_id dove lo mette davvero: dentro context."""
    payload = {} if user_id is None else {"context": {"user_id": user_id}}
    return {"timestamp": ts, "source": "moodle", "event_type": event_type, "payload": payload}


def eeg_sample(ts, session_id="s1"):
    return {"session_id": session_id, "timestamp": ts, "source": "eeg",
            "event_type": "sample", "payload": {"v": 1}}


# --------------------------------------------------------------------- #
#  timestamp obbligatorio                                               #
# --------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_ts",
    [OMITTED, None, "1786544587622", 0, -5, True],
    ids=["assente", "null", "stringa", "zero", "negativo", "bool"],
)
def test_event_without_valid_timestamp_is_rejected(client, db_conn, bad_ts):
    event = {"session_id": "s1", "source": "eeg", "event_type": "sample", "payload": {}}
    if bad_ts is not OMITTED:
        event["timestamp"] = bad_ts

    r = post(client, [event])

    body = r.get_json()
    assert body["stored"] == 0
    assert body["no_timestamp"] == 1
    assert timeline_rows(db_conn) == []


def test_timestamp_accepts_both_seconds_and_milliseconds(client, db_conn):
    events = [
        {"session_id": "s1", "timestamp": 1786544587.622, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"timestamp": 1786544588622, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "x"}},
    ]

    r = post(client, events)

    assert r.get_json()["stored"] == 2
    rows = timeline_rows(db_conn)
    # in colonna sempre secondi, qualunque unità sia arrivata
    assert rows[0][1] == pytest.approx(1786544587.622)
    assert rows[1][1] == pytest.approx(1786544588.622)


# --------------------------------------------------------------------- #
#  risoluzione del timestamp                                            #
# --------------------------------------------------------------------- #

def test_integer_second_resolution_collides_and_drops_events(client):
    """Il vincolo UNIQUE non comprende il payload: a risoluzione di un
    secondo cinque campioni con alpha diverso sono la stessa riga, e ne
    sopravvive uno. È il motivo per cui il contratto pretende i ms."""
    events = [
        {"session_id": "s1", "timestamp": 1786544600, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": i}}
        for i in range(5)
    ]

    body = post(client, events).get_json()

    assert body["stored"] == 1
    assert body["duplicates"] == 4


def test_millisecond_resolution_avoids_collision(client):
    events = [
        {"session_id": "s1", "timestamp": 1786544600.0 + i * 0.001, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": i}}
        for i in range(5)
    ]

    body = post(client, events).get_json()

    assert body["stored"] == 5
    assert body["duplicates"] == 0


# --------------------------------------------------------------------- #
#  correlazione delle sessioni                                          #
# --------------------------------------------------------------------- #

def test_session_start_correlates_following_moodle_event(client, db_conn):
    post(client, [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"timestamp": 1786544601.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "x"}},
    ])

    assert rows_by_source(db_conn)["moodle"][0] == "s1"


def test_moodle_event_without_active_session_has_null_session_id(client, db_conn):
    r = post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "x"}},
    ])

    assert r.get_json()["stored"] == 1
    assert timeline_rows(db_conn)[0][0] is None


def test_second_session_start_supersedes_first(client, db_conn):
    post(client, [{"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
                    "event_type": "session_start", "payload": {}}])

    body = post(client, [{"session_id": "s2", "timestamp": 1786544700.0, "source": "eeg",
                           "event_type": "session_start", "payload": {}}]).get_json()

    assert body["sessions_opened"] == ["s2"]
    assert body["sessions_superseded"] == ["s1"]

    # la sessione soppiantata risulta chiusa all'istante di apertura della nuova
    row = db_conn.execute(
        "SELECT stopped_at FROM sessions WHERE session_id = 's1'"
    ).fetchone()
    assert row[0] == pytest.approx(1786544700.0)


def test_explicit_session_end_closes_session_and_sets_row_count(client, db_conn):
    """row_count si aggiorna dopo l'inserimento, così un session_end conta
    anche i campioni arrivati nella sua stessa richiesta."""
    events = [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"session_id": "s1", "timestamp": 1786544601.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 1}},
        {"session_id": "s1", "timestamp": 1786544602.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 2}},
        {"session_id": "s1", "timestamp": 1786544603.0, "source": "eeg",
         "event_type": "session_end", "payload": {}},
    ]

    body = post(client, events).get_json()

    assert body["sessions_closed"] == ["s1"]
    row = db_conn.execute(
        "SELECT stopped_at, row_count FROM sessions WHERE session_id = 's1'"
    ).fetchone()
    assert row[0] == pytest.approx(1786544603.0)
    assert row[1] == 4  # anche session_start e session_end sono righe di timeline


def test_eeg_sample_with_unknown_session_id_is_autoregistered(client, db_conn):
    """Se la POST di session_start non è mai arrivata, i campioni inviati
    allo Stop registrano la sessione invece di essere rifiutati."""
    body = post(client, [
        {"session_id": "s_mai_annunciata", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 1}},
    ]).get_json()

    assert body["stored"] == 1
    assert body["sessions_autoregistered"] == ["s_mai_annunciata"]
    assert db_conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = 's_mai_annunciata'"
    ).fetchone() is not None


# --------------------------------------------------------------------- #
#  idempotenza                                                          #
# --------------------------------------------------------------------- #

def test_resending_same_batch_does_not_duplicate(client, db_conn):
    events = [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"session_id": "s1", "timestamp": 1786544601.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 1}},
    ]

    post(client, events)
    body = post(client, events).get_json()

    assert body["stored"] == 0
    assert body["duplicates"] == 2
    assert len(timeline_rows(db_conn)) == 2


def test_events_with_null_session_id_are_never_deduplicated(client):
    """NULL non è mai uguale a NULL in SQL, quindi il vincolo UNIQUE non
    scatta sugli eventi fuori sessione. Il contrario di quanto succede a
    parità di session_id valorizzato (vedi il test sopra)."""
    event = {"timestamp": 1786544600.0, "source": "moodle",
              "event_type": "navigation_clicked", "payload": {"label": "x"}}

    body = post(client, [event, dict(event)]).get_json()

    assert body["stored"] == 2


# --------------------------------------------------------------------- #
#  discriminazione di 'source'                                          #
# --------------------------------------------------------------------- #

def test_unknown_source_is_rejected_not_routed_as_moodle(client, db_conn):
    """Un refuso in 'source' non deve finire nel ramo Moodle per esclusione:
    si porterebbe dietro il session_id della sessione EEG attiva e una
    description calcolata, sporcando la timeline senza segnalare nulla."""
    body = post(client, [
        {"timestamp": 1786544600.0, "source": "moodel",
         "event_type": "navigation_clicked", "payload": {"label": "x"}},
    ]).get_json()

    assert body["stored"] == 0
    assert body["invalid"] == 1
    assert timeline_rows(db_conn) == []


def test_eeg_and_moodle_get_different_treatment(client, db_conn):
    """Le due sorgenti nello stesso batch: l'evento EEG porta il proprio
    session_id e resta senza description, quello Moodle eredita la sessione
    attiva e riceve la description dal backend."""
    post(client, [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"timestamp": 1786544601.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "Avanti"}},
    ])

    rows = rows_by_source(db_conn)
    assert rows["eeg"][0] == "s1"
    assert rows["eeg"][4] == ""
    assert rows["moodle"][0] == "s1"
    assert rows["moodle"][4] == 'User clicked "Avanti"'


def test_eeg_event_without_session_id_is_invalid(client, db_conn):
    """A differenza degli eventi Moodle, un campione EEG senza session_id non
    è recuperabile: non esiste una sessione da cui ereditarlo."""
    body = post(client, [
        {"timestamp": 1786544600.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 1}},
    ]).get_json()

    assert body["invalid"] == 1
    assert timeline_rows(db_conn) == []


# --------------------------------------------------------------------- #
#  validazione della busta                                              #
# --------------------------------------------------------------------- #

def test_single_object_body_is_accepted_as_one_event_array(client):
    r = client.post("/api/v1/events", json={
        "session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
        "event_type": "session_start", "payload": {},
    })

    assert r.status_code == 201
    assert r.get_json()["stored"] == 1


def test_event_missing_source_or_event_type_is_invalid(client):
    body = post(client, [
        {"timestamp": 1786544600.0, "event_type": "sample", "payload": {}},
        {"timestamp": 1786544601.0, "source": "eeg", "payload": {}},
    ]).get_json()

    assert body["invalid"] == 2
    assert body["stored"] == 0


def test_one_invalid_event_does_not_discard_the_rest_of_the_batch(client, db_conn):
    """Il client non ritrasmette: far fallire l'intera richiesta per una riga
    costerebbe la sessione completa, 300-800 campioni."""
    body = post(client, [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
        {"source": "eeg", "event_type": "band_power", "payload": {}},  # senza timestamp
        {"session_id": "s1", "timestamp": 1786544602.0, "source": "eeg",
         "event_type": "band_power", "payload": {"alpha": 2}},
    ]).get_json()

    assert body["stored"] == 2
    assert body["no_timestamp"] == 1
    assert len(timeline_rows(db_conn)) == 2


@pytest.mark.parametrize(
    "payload, expected",
    [("click", {"value": "click"}), (42, {"value": 42}), (None, {})],
    ids=["stringa", "numero", "null"],
)
def test_non_dict_payload_is_wrapped_not_dropped(client, db_conn, payload, expected):
    """La colonna payload deve restare sempre un oggetto JSON, altrimenti
    chi legge la timeline deve gestire due forme diverse."""
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": payload},
    ])

    assert json.loads(timeline_rows(db_conn)[0][5]) == expected


# --------------------------------------------------------------------- #
#  clock_skew_measured: telemetria, non comportamento                   #
# --------------------------------------------------------------------- #

def test_clock_skew_measured_goes_to_its_own_table(client, db_conn):
    body = post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "clock_skew_measured",
         "payload": {"skew_ms": -12.4, "uncertainty_ms": 3.1,
                      "rtt_min_ms": 8.2, "samples": 5}},
    ]).get_json()

    assert body["clock_skew_samples"] == 1
    assert timeline_rows(db_conn) == []  # non deve sporcare la timeline

    row = db_conn.execute(
        "SELECT skew_ms, uncertainty_ms, rtt_min_ms, samples FROM clock_skew"
    ).fetchone()
    assert row == (-12.4, 3.1, 8.2, 5)


def test_clock_skew_inherits_active_session(client, db_conn):
    post(client, [{"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
                    "event_type": "session_start", "payload": {}}])

    post(client, [{"timestamp": 1786544601.0, "source": "moodle",
                    "event_type": "clock_skew_measured", "payload": {"skew_ms": 1.0}}])

    row = db_conn.execute("SELECT session_id FROM clock_skew").fetchone()
    assert row[0] == "s1"


def test_clock_skew_missing_keys_default_to_zero_not_error(client, db_conn):
    r = post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "clock_skew_measured", "payload": {}},
    ])

    assert r.status_code == 201
    row = db_conn.execute(
        "SELECT skew_ms, uncertainty_ms, rtt_min_ms, samples FROM clock_skew"
    ).fetchone()
    assert row == (0, 0, 0, 0)


# --------------------------------------------------------------------- #
#  description                                                          #
# --------------------------------------------------------------------- #

def test_explicit_description_is_used_verbatim(client, db_conn):
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "x"},
         "description": "Testo fornito dal chiamante"},
    ])

    assert timeline_rows(db_conn)[0][4] == "Testo fornito dal chiamante"


def test_null_description_is_computed_by_backend(client, db_conn):
    """Il caso reale: il plugin manda description null per ogni evento."""
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "Avanti"},
         "description": None},
    ])

    assert timeline_rows(db_conn)[0][4] == 'User clicked "Avanti"'


def test_empty_string_description_is_not_recomputed(client, db_conn):
    """Stringa vuota è un valore esplicito, non un'assenza: il backend non
    la rimpiazza. Distinzione facile da rompere passando a un controllo di
    verità al posto di 'is None'."""
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "Avanti"},
         "description": ""},
    ])

    assert timeline_rows(db_conn)[0][4] == ""


# --------------------------------------------------------------------- #
#  user_id                                                              #
# --------------------------------------------------------------------- #

def test_user_id_is_read_from_payload_context(client, db_conn):
    """Il caso reale: il plugin non manda user_id come campo proprio, lo
    include nell'oggetto context insieme al resto dell'ambiente."""
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "page_loaded",
         "payload": {"context": {"user_id": 7, "course_name": "Neuroscienze"}}},
    ])

    assert stored_user_id(db_conn) == 7


def test_top_level_user_id_takes_precedence_over_context(client, db_conn):
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle", "user_id": 99,
         "event_type": "page_loaded", "payload": {"context": {"user_id": 7}}},
    ])

    assert stored_user_id(db_conn) == 99


def test_user_id_is_null_when_absent_everywhere(client, db_conn):
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "navigation_clicked", "payload": {"label": "Avanti"}},
    ])

    assert stored_user_id(db_conn) is None


def test_user_id_survives_a_non_dict_context(client, db_conn):
    """Un context non-oggetto non deve far fallire l'estrazione: senza il
    controllo di tipo, .get() su una stringa solleverebbe AttributeError e
    porterebbe giù l'intero lotto."""
    post(client, [
        {"timestamp": 1786544600.0, "source": "moodle",
         "event_type": "page_loaded", "payload": {"context": "non un oggetto"}},
    ])

    assert stored_user_id(db_conn) is None


def test_eeg_events_have_no_user_id_of_their_own(client, db_conn):
    """Il client EEG non conosce l'utente Moodle: senza un evento del plugin
    che lo dichiari, non c'è nulla da attribuire e la riga resta nulla."""
    post(client, [
        {"session_id": "s1", "timestamp": 1786544600.0, "source": "eeg",
         "event_type": "session_start", "payload": {}},
    ])

    assert stored_user_id(db_conn) is None


def test_user_id_is_not_part_of_the_uniqueness_key(client, db_conn):
    """Due eventi che differiscono solo per user_id collidono comunque: la
    chiave è (session_id, source, event_type, ts). Conta saperlo prima di
    usare user_id per distinguere studenti sulla stessa sessione.

    Serve una sessione attiva: con session_id nullo il vincolo non scatta
    mai e il confronto non direbbe nulla su user_id."""
    post(client, [{"session_id": "s1", "timestamp": 1786544500.0, "source": "eeg",
                    "event_type": "session_start", "payload": {}}])

    body = post(client, [
        {"timestamp": 1786544600.0, "source": "moodle", "user_id": 1,
         "event_type": "page_loaded", "payload": {}},
        {"timestamp": 1786544600.0, "source": "moodle", "user_id": 2,
         "event_type": "page_loaded", "payload": {}},
    ]).get_json()

    assert body["stored"] == 1
    assert body["duplicates"] == 1


# --------------------------------------------------------------------- #
#  attribuzione degli eventi EEG allo studente                          #
# --------------------------------------------------------------------- #
#
#  Il client EEG non conosce l'utente Moodle e non lo manderà mai. L'unica
#  cosa che le due sorgenti condividono è il session_id: il backend impara
#  l'utente dal plugin e lo estende a tutte le righe della sessione.

def test_eeg_events_inherit_the_user_learned_from_moodle(client, db_conn):
    """Il caso normale: il plugin dichiara lo studente, i campioni EEG che
    arrivano dopo (allo Stop) ne ereditano l'attribuzione."""
    start_session(client)
    post(client, [moodle_event(1786544600.0, user_id=7)])

    post(client, [eeg_sample(1786544700.0), eeg_sample(1786544701.0)])

    assert user_ids_of(db_conn, "eeg") == [7, 7, 7]  # session_start compreso


def test_session_start_is_backfilled_when_the_user_becomes_known(client, db_conn):
    """session_start precede sempre il primo evento Moodle: quella riga non
    si può attribuire in corsa, la recupera la UPDATE di ripescaggio."""
    start_session(client)
    assert user_ids_of(db_conn, "eeg") == [None]

    post(client, [moodle_event(1786544600.0, user_id=7)])

    assert user_ids_of(db_conn, "eeg") == [7]


def test_eeg_batch_sent_before_any_moodle_activity_is_backfilled(client, db_conn):
    """Sessione registrata prima che lo studente tocchi il browser: le righe
    esistono già quando l'utente si scopre, e vanno recuperate a ritroso."""
    start_session(client)
    post(client, [eeg_sample(1786544700.0), eeg_sample(1786544701.0)])

    body = post(client, [moodle_event(1786544800.0, user_id=7)]).get_json()

    assert body["rows_attributed"] == 3
    assert user_ids_of(db_conn, "eeg") == [7, 7, 7]


def test_events_are_attributed_within_a_single_batch(client, db_conn):
    """Le entry si assemblano tutte prima dell'INSERT: un campione che nel
    lotto precede l'evento Moodle non può leggere l'utente al momento della
    costruzione. Senza il ripescaggio, resterebbe nullo."""
    start_session(client)

    post(client, [eeg_sample(1786544700.0), moodle_event(1786544800.0, user_id=7)])

    assert user_ids_of(db_conn, "eeg") == [7, 7]
    assert user_ids_of(db_conn, "moodle") == [7]


def test_the_first_user_seen_wins_for_the_whole_session(client, db_conn):
    """Una sessione è di uno studente solo. Un secondo user_id sulla stessa
    sessione (due account sulla stessa macchina) non riscrive l'attribuzione
    già data: resterebbero righe EEG assegnate a due studenti diversi senza
    modo di dire quale sia quella giusta."""
    start_session(client)
    post(client, [moodle_event(1786544600.0, user_id=7)])
    post(client, [moodle_event(1786544700.0, user_id=99)])

    post(client, [eeg_sample(1786544800.0)])

    assert session_user_id(db_conn, "s1") == 7
    assert user_ids_of(db_conn, "eeg") == [7, 7]
    # L'evento del secondo utente conserva il proprio user_id: è un dato
    # osservato, non un'inferenza, e non va riscritto.
    assert user_ids_of(db_conn, "moodle") == [7, 99]


def test_a_moodle_event_without_user_id_inherits_the_session_user(client, db_conn):
    """Non tutti gli eventi del plugin portano context: quelli che ne sono
    privi sono comunque dello studente della sessione."""
    start_session(client)
    post(client, [moodle_event(1786544600.0, user_id=7)])

    post(client, [moodle_event(1786544700.0, event_type="navigation_clicked")])

    assert user_ids_of(db_conn, "moodle") == [7, 7]


def test_attribution_does_not_leak_across_sessions(client, db_conn):
    """Lo studente sta sulla sessione, non sul backend: una sessione nuova
    riparte senza utente finché non arriva un suo evento Moodle."""
    start_session(client, "s1")
    post(client, [moodle_event(1786544600.0, user_id=7)])
    start_session(client, "s2", ts=1786544700.0)  # supersede di s1

    post(client, [eeg_sample(1786544800.0, session_id="s2")])

    assert session_user_id(db_conn, "s2") is None
    assert user_ids_of(db_conn, "eeg") == [7, None, None]


def test_the_session_user_is_persisted(client, db_conn):
    """La colonna su 'sessions' è la fonte autorevole: serve a interrogare le
    sessioni per studente e a sopravvivere al riavvio."""
    start_session(client)

    post(client, [moodle_event(1786544600.0, user_id=7)])

    assert session_user_id(db_conn, "s1") == 7


def test_attribution_survives_a_backend_restart(db_path, db_conn):
    """I campioni di una sessione arrivano allo Stop e possono cadere dopo un
    riavvio: lo stato in memoria è perso, l'attribuzione no perché la rilegge
    dal database."""
    class _AppConfig(TestConfig):
        DB_PATH = db_path

    first = create_app(_AppConfig).test_client()
    start_session(first)
    post(first, [moodle_event(1786544600.0, user_id=7)])

    restarted = create_app(_AppConfig).test_client()
    post(restarted, [eeg_sample(1786544700.0)])

    assert user_ids_of(db_conn, "eeg") == [7, 7]


def test_nothing_is_attributed_when_no_user_is_ever_known(client, db_conn):
    """Nessun evento Moodle, nessuna invenzione: le righe restano nulle e il
    contatore lo dice."""
    start_session(client)

    body = post(client, [eeg_sample(1786544700.0)]).get_json()

    assert body["rows_attributed"] == 0
    assert user_ids_of(db_conn, "eeg") == [None, None]


def test_events_outside_any_session_are_not_attributed(client, db_conn):
    """Senza sessione attiva l'evento Moodle finisce con session_id nullo: non
    c'è nessuna sessione a cui appendere lo studente, e le righe di altre
    sessioni non devono ereditarlo."""
    start_session(client)
    post(client, [moodle_event(1786544600.0, user_id=7)])
    post(client, [{"session_id": "s1", "timestamp": 1786544700.0, "source": "eeg",
                   "event_type": "session_end", "payload": {}}])

    post(client, [moodle_event(1786544800.0, user_id=99)])

    rows = [row for row in timeline_rows(db_conn) if row[0] is None]
    assert [row[6] for row in rows] == [99]
    assert session_user_id(db_conn, "s1") == 7
