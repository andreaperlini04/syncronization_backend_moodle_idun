"""Genera description leggibili per gli eventi Moodle nella timeline.

Tradotta da event_writer.php::descriptions() (plugin local_eegimucapture),
limitata ai tipi di evento che oggi arrivano dal client via /event: gli
eventi server-side (quiz_started, course_opened, ecc.) non transitano
ancora da questo backend, quindi non hanno voce qui.

Se PHP aggiunge o modifica un template per uno di questi event_type, va
aggiornato anche qui — sono due implementazioni indipendenti della stessa
tabella di traduzione, non condividono codice per via del confine
JS-nel-browser / Python-sul-backend descritto nella progettazione.

event_type senza voce nel registry degradano allo slug grezzo (stesso
comportamento del fallback PHP), non bloccano mai la scrittura.
"""

from typing import Callable

_Template = Callable[[dict], str]


def _navigation_clicked(p: dict) -> str:
    label = p.get("label") or p.get("target_tag") or "?"
    return f'User clicked "{label}"'


def _input_change(p: dict) -> str:
    tag = p.get("target_tag") or "field"
    target_id = p.get("target_id")
    return f'User changed field "{target_id}" ({tag})' if target_id else f"User changed a {tag} field"


def _question_displayed(p: dict) -> str:
    n = p.get("question_number", "?")
    return f"User displayed Question {n}"


def _answer_selected(p: dict) -> str:
    n = p.get("question_number", "?")
    ans = p.get("answer_text", "?")
    return f'User selected "{ans}" for question {n}'


def _answer_changed(p: dict) -> str:
    n = p.get("question_number", "?")
    old = p.get("old_answer_text", "?")
    new = p.get("new_answer_text", "?")
    return f'User changed answer for question {n} from "{old}" to "{new}"'


def _text_answer_entered(p: dict) -> str:
    n = p.get("question_number", "?")
    return f"User entered text answer for question {n}"


def _answer_cleared(p: dict) -> str:
    n = p.get("question_number", "?")
    answer_text = p.get("answer_text")
    if answer_text:
        return f'User deselected "{answer_text}" for question {n}'
    return f"User cleared answer for question {n}"


def _drag_drop_completed(p: dict) -> str:
    n = p.get("question_number", "?")
    item = p.get("item_text", "?")
    target = p.get("target_text", "?")
    return f'User placed "{item}" on "{target}" for question {n}'


def _video_started(p: dict) -> str:
    name = p.get("video_name") or f"#{p.get('video_id', '?')}"
    return f'User started video lesson "{name}"'


def _video_paused(p: dict) -> str:
    name = p.get("video_name") or f"#{p.get('video_id', '?')}"
    return f'User paused video lesson "{name}"'


def _quiz_abandoned(p: dict) -> str:
    name = p.get("quiz_name") or f"#{p.get('quiz_id', '?')}"
    return f'User abandoned quiz "{name}"'


def _quiz_overdue(p: dict) -> str:
    name = p.get("quiz_name") or f"#{p.get('quiz_id', '?')}"
    return f'Quiz "{name}" time expired'


def _page_loaded(p: dict) -> str:
    """Nessun equivalente PHP: sostituisce lato client course_opened/
    activity_opened, il contesto è nel campo 'context' del payload."""
    ctx = p.get("context", {})
    activity = ctx.get("activity_name")
    course = ctx.get("course_name")
    if activity:
        return f'User loaded page: "{activity}" ({course or "?"})'
    if course:
        return f'User loaded page in course "{course}"'
    return "User loaded a page"


def _clock_skew_measured(p: dict) -> str:
    """Nessun equivalente PHP: evento diagnostico, non un'azione dello studente."""
    return f"Clock skew measured: {p.get('skew_ms', '?')}ms (±{p.get('uncertainty_ms', '?')}ms)"


_REGISTRY: dict[str, _Template] = {
    "navigation_clicked": _navigation_clicked,
    "input_change": _input_change,
    "question_displayed": _question_displayed,
    "answer_selected": _answer_selected,
    "answer_changed": _answer_changed,
    "text_answer_entered": _text_answer_entered,
    "answer_cleared": _answer_cleared,
    "drag_drop_completed": _drag_drop_completed,
    "video_started": _video_started,
    "video_paused": _video_paused,
    "quiz_abandoned": _quiz_abandoned,
    "quiz_overdue": _quiz_overdue,
    "page_loaded": _page_loaded,
    "clock_skew_measured": _clock_skew_measured,
}


def describe(event_type: str, payload: dict) -> str:
    """Description leggibile per un evento. Fallback allo slug grezzo se
    l'event_type non ha un template (stesso comportamento di PHP)."""
    template = _REGISTRY.get(event_type)
    if template is None:
        return event_type
    return template(payload)