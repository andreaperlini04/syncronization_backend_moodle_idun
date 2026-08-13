"""Test dei template di description.

Funzioni pure: nessuna app, nessun database. I testi attesi sono quelli
prodotti dal plugin, perché le righe già in timeline li usano e una
riformulazione spezzerebbe in due la stessa description a metà dataset.
"""

import pytest

from app.services.moodle_descriptions import _REGISTRY, describe

# Un caso "pieno" per template, con il testo che deve uscirne.
# page_loaded e clock_skew_measured hanno più rami e sono verificati a parte.
FULL_PAYLOADS = {
    "user_loggedin": ({"username": "mrossi", "user_id": 42}, 'User "mrossi" logged in'),
    "course_opened": ({"course_name": "Neuroscienze", "course_id": 7},
                       'User opened course "Neuroscienze"'),
    "activity_opened": ({"module_type": "quiz", "activity_name": "Test 1", "cmid": 99},
                         'User opened quiz "Test 1"'),
    "video_started": ({"video_name": "Lezione 3", "video_id": 5},
                       'User started video lesson "Lezione 3"'),
    "video_paused": ({"video_name": "Lezione 3", "video_id": 5},
                      'User paused video lesson "Lezione 3"'),
    "quiz_started": ({"quiz_name": "Test 1", "quiz_id": 3}, 'User started quiz "Test 1"'),
    "quiz_submitted": ({"quiz_name": "Test 1", "quiz_id": 3}, 'User submitted quiz "Test 1"'),
    "quiz_abandoned": ({"quiz_name": "Test 1", "quiz_id": 3}, 'User abandoned quiz "Test 1"'),
    "quiz_overdue": ({"quiz_name": "Test 1", "quiz_id": 3}, 'Quiz "Test 1" time expired'),
    "quiz_reviewed": ({"quiz_name": "Test 1", "quiz_id": 3}, 'User reviewed quiz "Test 1"'),
    "question_displayed": ({"question_number": 3}, "User displayed Question 3"),
    "answer_selected": ({"question_number": 3, "answer_text": "Roma"},
                         'User selected "Roma" for question 3'),
    "answer_changed": ({"question_number": 3, "old_answer_text": "Milano",
                         "new_answer_text": "Roma"},
                        'User changed answer for question 3 from "Milano" to "Roma"'),
    "text_answer_entered": ({"question_number": 4}, "User entered text answer for question 4"),
    "answer_cleared": ({"question_number": 5, "answer_text": "Roma"},
                        'User deselected "Roma" for question 5'),
    "drag_drop_completed": ({"question_number": 6, "item_text": "Lobo", "target_text": "Frontale"},
                             'User placed "Lobo" on "Frontale" for question 6'),
    "navigation_clicked": ({"label": "Avanti"}, 'User clicked "Avanti"'),
    "input_change": ({"target_tag": "input", "target_id": "q3_answer"},
                      'User changed field "q3_answer" (input)'),
    "forum_opened": ({"forum_name": "Domande", "forum_id": 2},
                      'User opened discussion forum "Domande"'),
    "forum_post_created": ({"forum_name": "Domande", "forum_id": 2},
                            'User created a post in forum "Domande"'),
    "lesson_started": ({"lesson_name": "Anatomia", "lesson_id": 8},
                        'User started lesson "Anatomia"'),
    "lesson_ended": ({"lesson_name": "Anatomia", "lesson_id": 8},
                      'User ended lesson "Anatomia"'),
    "assignment_submitted": ({"assign_name": "Relazione", "assign_id": 4},
                              'User submitted assignment "Relazione"'),
}

TESTED_SEPARATELY = {"page_loaded", "clock_skew_measured"}


def test_every_registered_template_is_covered():
    """Aggiungere un template senza il caso corrispondente fa fallire qui,
    invece di lasciarlo scoperto in silenzio."""
    assert set(_REGISTRY) == set(FULL_PAYLOADS) | TESTED_SEPARATELY


@pytest.mark.parametrize("event_type", sorted(FULL_PAYLOADS))
def test_template_with_full_payload(event_type):
    payload, expected = FULL_PAYLOADS[event_type]
    assert describe(event_type, payload) == expected


@pytest.mark.parametrize("event_type", sorted(_REGISTRY))
def test_incomplete_payload_degrades_instead_of_raising(event_type):
    """Un payload senza le chiavi attese non deve far saltare l'ingest:
    l'eccezione qui propagherebbe fino a far perdere l'intero batch."""
    describe(event_type, {})


def test_question_number_zero_is_not_treated_as_missing():
    """Zero è un indice legittimo, non un'assenza: solo None attiva il '?'."""
    assert describe("question_displayed", {"question_number": 0}) == "User displayed Question 0"


def test_named_template_falls_back_to_id_when_name_is_missing():
    assert describe("quiz_started", {"quiz_id": 3}) == 'User started quiz "#3"'


def test_answer_cleared_without_answer_text_uses_generic_phrasing():
    assert describe("answer_cleared", {"question_number": 5}) == "User cleared answer for question 5"


def test_navigation_clicked_falls_back_to_target_tag_without_label():
    assert describe("navigation_clicked", {"target_tag": "button"}) == 'User clicked "button"'


def test_input_change_without_target_id_uses_generic_phrasing():
    assert describe("input_change", {"target_tag": "textarea"}) == "User changed a textarea field"


def test_unregistered_event_type_degrades_to_raw_slug():
    assert describe("qualcosa_di_nuovo", {}) == "qualcosa_di_nuovo"


# page_loaded: tre rami, e un testo che si discosta da quello del plugin per
# non confondersi con activity_opened e course_opened.

def test_page_loaded_with_activity_includes_course():
    payload = {"context": {"activity_name": "Test 1", "course_name": "Neuroscienze"}}
    assert describe("page_loaded", payload) == 'User loaded page: "Test 1" (Neuroscienze)'


def test_page_loaded_with_course_only():
    payload = {"context": {"course_name": "Neuroscienze"}}
    assert describe("page_loaded", payload) == 'User loaded page in course "Neuroscienze"'


def test_page_loaded_without_context():
    assert describe("page_loaded", {}) == "User loaded a page"


def test_page_loaded_stays_distinguishable_from_course_opened():
    """Due event_type diversi non devono produrre la stessa frase: in
    timeline sarebbero indistinguibili a occhio."""
    same_course = {"course_name": "Neuroscienze", "course_id": 7}

    assert describe("page_loaded", {"context": same_course}) != describe("course_opened", same_course)


def test_clock_skew_measured_reads_diagnostic_fields():
    payload = {"skew_ms": -12.4, "uncertainty_ms": 3.1}
    assert describe("clock_skew_measured", payload) == "Clock skew measured: -12.4ms (±3.1ms)"
