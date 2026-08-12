"""Genera description leggibili per gli eventi Moodle nella timeline.

Il backend è l'unica autorità sulle description: il plugin manda sempre
`description: null`, sia per gli eventi client-side (JS) sia per quelli
server-side relayati. Prima esistevano due implementazioni indipendenti
della stessa tabella — questa e event_writer.php::descriptions() — e i
loro testi erano già divergenti su due template (vedi sotto). Ora PHP
calcola la description solo per i suoi file di log locali (.jsonl/.log),
che non transitano da qui.

Tradotta da event_writer.php::descriptions() (plugin local_eegimucapture).
Se PHP aggiunge un event_type, va aggiunta una voce anche qui: non c'è
codice condiviso fra i due linguaggi.

event_type senza voce nel registry degradano allo slug grezzo (stesso
comportamento del fallback PHP), non bloccano mai la scrittura.

Due template si discostano volutamente dal testo PHP:

  page_loaded          PHP dice 'User opened "X"', che produrrebbe una
                       description quasi identica a quella di
                       activity_opened e course_opened — tre event_type
                       distinti indistinguibili a occhio nella timeline.
                       Qui resta "User loaded page", che li separa.
  clock_skew_measured   testo storico di questo file.

Entrambi sono eventi client-side, quindi le righe già in database sono
state scritte da questo file: mantenere il testo di qui evita di spezzare
in due la stessa description a metà del dataset.
"""

from typing import Callable

_Template = Callable[[dict], str]


def _f(p: dict, key: str, default: str = "?"):
    """Campo del payload, con default se assente o null.

    Replica l'operatore ?? di PHP: solo null/assente attivano il default,
    non i valori falsy. Serve per question_number, dove uno 0 legittimo
    (indice base zero) non deve degradare a "?".
    """
    value = p.get(key)
    return default if value is None else value


def _named(name_key: str, id_key: str, template: str) -> _Template:
    """Template per il caso più comune: un nome, con ripiego su "#id".

    A differenza del ?? di PHP usa il test di verità, quindi un nome vuoto
    ripiega sull'id invece di produrre virgolette vuote — un '#42' è più
    utile di un '""' quando Moodle non ha valorizzato il nome.
    """

    def render(p: dict) -> str:
        return template.format(name=p.get(name_key) or f"#{_f(p, id_key)}")

    return render


# ── interazioni domanda ───────────────────────────────────────────────

def _question_displayed(p: dict) -> str:
    return f"User displayed Question {_f(p, 'question_number')}"


def _answer_selected(p: dict) -> str:
    return f'User selected "{_f(p, "answer_text")}" for question {_f(p, "question_number")}'


def _answer_changed(p: dict) -> str:
    return (
        f"User changed answer for question {_f(p, 'question_number')} "
        f'from "{_f(p, "old_answer_text")}" to "{_f(p, "new_answer_text")}"'
    )


def _text_answer_entered(p: dict) -> str:
    return f"User entered text answer for question {_f(p, 'question_number')}"


def _answer_cleared(p: dict) -> str:
    n = _f(p, "question_number")
    answer_text = p.get("answer_text")
    if answer_text:
        return f'User deselected "{answer_text}" for question {n}'
    return f"User cleared answer for question {n}"


def _drag_drop_completed(p: dict) -> str:
    return (
        f'User placed "{_f(p, "item_text")}" on "{_f(p, "target_text")}" '
        f"for question {_f(p, 'question_number')}"
    )


# ── navigazione UI ────────────────────────────────────────────────────

def _navigation_clicked(p: dict) -> str:
    """Richiede 'label' o 'target_tag' nel payload.

    Il plugin li rimuoveva dal payload persistito perché ridondanti con la
    description già calcolata in PHP; ora che la calcola il backend, senza
    di essi la description degrada a 'User clicked "?"'.
    """
    return f'User clicked "{p.get("label") or p.get("target_tag") or "?"}"'


def _input_change(p: dict) -> str:
    tag = p.get("target_tag") or "field"
    target_id = p.get("target_id")
    return f'User changed field "{target_id}" ({tag})' if target_id else f"User changed a {tag} field"


def _activity_opened(p: dict) -> str:
    module_type = p.get("module_type") or "activity"
    name = p.get("activity_name") or f"#{_f(p, 'cmid')}"
    return f'User opened {module_type} "{name}"'


# ── contesto pagina / sincronizzazione ────────────────────────────────

def _page_loaded(p: dict) -> str:
    """Testo divergente da PHP per non collidere con activity_opened e
    course_opened: vedi nota nel docstring del modulo."""
    ctx = p.get("context") or {}
    activity = ctx.get("activity_name")
    course = ctx.get("course_name")
    if activity:
        return f'User loaded page: "{activity}" ({course or "?"})'
    if course:
        return f'User loaded page in course "{course}"'
    return "User loaded a page"


def _clock_skew_measured(p: dict) -> str:
    """Evento diagnostico, non un'azione dello studente. Non finisce in
    timeline: TimelineService lo dirotta sulla tabella clock_skew."""
    return f"Clock skew measured: {_f(p, 'skew_ms')}ms (±{_f(p, 'uncertainty_ms')}ms)"


def _user_loggedin(p: dict) -> str:
    name = p.get("username") or f"#{_f(p, 'user_id')}"
    return f'User "{name}" logged in'


_REGISTRY: dict[str, _Template] = {
    # sessione / autenticazione
    "user_loggedin": _user_loggedin,
    # navigazione corso
    "course_opened": _named("course_name", "course_id", 'User opened course "{name}"'),
    "activity_opened": _activity_opened,
    "page_loaded": _page_loaded,
    "video_started": _named("video_name", "video_id", 'User started video lesson "{name}"'),
    "video_paused": _named("video_name", "video_id", 'User paused video lesson "{name}"'),
    # quiz lifecycle
    "quiz_started": _named("quiz_name", "quiz_id", 'User started quiz "{name}"'),
    "quiz_submitted": _named("quiz_name", "quiz_id", 'User submitted quiz "{name}"'),
    "quiz_abandoned": _named("quiz_name", "quiz_id", 'User abandoned quiz "{name}"'),
    "quiz_overdue": _named("quiz_name", "quiz_id", 'Quiz "{name}" time expired'),
    "quiz_reviewed": _named("quiz_name", "quiz_id", 'User reviewed quiz "{name}"'),
    # interazioni domanda
    "question_displayed": _question_displayed,
    "answer_selected": _answer_selected,
    "answer_changed": _answer_changed,
    "text_answer_entered": _text_answer_entered,
    "answer_cleared": _answer_cleared,
    "drag_drop_completed": _drag_drop_completed,
    # navigazione UI
    "navigation_clicked": _navigation_clicked,
    "input_change": _input_change,
    # altri moduli
    "forum_opened": _named("forum_name", "forum_id", 'User opened discussion forum "{name}"'),
    "forum_post_created": _named("forum_name", "forum_id", 'User created a post in forum "{name}"'),
    "lesson_started": _named("lesson_name", "lesson_id", 'User started lesson "{name}"'),
    "lesson_ended": _named("lesson_name", "lesson_id", 'User ended lesson "{name}"'),
    "assignment_submitted": _named("assign_name", "assign_id", 'User submitted assignment "{name}"'),
    # telemetria
    "clock_skew_measured": _clock_skew_measured,
}


def describe(event_type: str, payload: dict) -> str:
    """Description leggibile per un evento. Fallback allo slug grezzo se
    l'event_type non ha un template (stesso comportamento di PHP)."""
    template = _REGISTRY.get(event_type)
    if template is None:
        return event_type
    return template(payload)
