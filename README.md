# syncronization_backend_moodle_idun

Backend di raccolta per il progetto C11326: riceve gli eventi del client EEG
(`EEGVisualizer.py`, IDUN Guardian 4) e del plugin Moodle `local_eegimucapture`,
li persiste su SQLite e li tiene disponibili per l'analisi.

L'allineamento fra le due sorgenti avviene **per timestamp**: il backend non
produce righe fuse EEG+Moodle, conserva solo evento, timestamp e `session_id`.

## Avvio

```
venv\Scripts\Activate.ps1
python run.py
```

Ascolta su `http://127.0.0.1:8000` (vedi `app/config.py`).

## Endpoint del contratto

```
POST /api/sessions
Content-Type: application/json
```

Body: **array JSON di eventi**, anche per un solo elemento (un oggetto singolo
viene comunque accettato). Envelope comune alle due sorgenti:

```json
{
  "session_id": "20260809_150137",
  "timestamp": 1786287703.72254,
  "source": "eeg",
  "event_type": "sample",
  "payload": { "delta": 47.63, "theta": 12.63, "alpha": 5.986,
               "sigma": 1.826, "beta": 5.341, "gamma": 0.8174 }
}
```

Risposta `201` con un riepilogo (`stored`, `duplicates`, `invalid`,
`sessions_opened`, ...): serve al debug manuale, il client lo logga soltanto.

Scrittura sincrona: 500 campioni si inseriscono in ~20 ms, quindi nessuna coda
asincrona: si resta ampiamente dentro i 10 s di timeout del client.

### Tipi di evento gestiti

| `event_type` | Effetto |
|---|---|
| `session_start` | registra la sessione con l'id deciso dal client e la rende attiva; la riga finisce anche in `timeline` |
| `sample` (`source: eeg`) | riga in `timeline`, `payload` = le sei potenze assolute di banda |
| qualsiasi evento `source: moodle` | riga in `timeline`, `session_id` assegnato dal backend |
| `clock_skew_measured` | tabella separata `clock_skew` (telemetria, non comportamento) |
| `session_end` | chiude la sessione e ne aggiorna `row_count`; non ancora inviato dal client, gestito in anticipo |

### Semantica dei dati EEG (da tenere presente in analisi)

- Le sei bande sono **potenze assolute in µV²**, non normalizzate.
- `sigma` (12–15 Hz) e `beta` (13–30 Hz) **si sovrappongono**: la loro somma non
  è la potenza totale.
- Ordini di grandezza molto diversi fra bande (delta 20–150, gamma 0.4–3):
  niente soglie di validazione uguali per tutte.
- Il `timestamp` è l'**estremo destro di una finestra di 6 s**, non un istante.
- I campioni **non sono equispaziati**: il client scarta ~30% delle finestre e
  non le invia. Buchi di 10–20 s sono normali. Non interpolare.

## Decisioni prese (punti aperti del contratto)

1. **Sessioni concorrenti**: una sola attiva. Un nuovo `session_start`
   *supersede* la precedente (le assegna `stopped_at`), invece di dare 409:
   il client permette Start → Stop → Start e, se lo Stop non arriva (crash,
   finestra chiusa), la sessione resterebbe aperta per sempre.
2. **Eventi Moodle prima di `session_start`**: salvati con `session_id` NULL,
   non scartati. Restano riallineabili per timestamp.
3. **`session_id` sconosciuto sui campioni EEG**: la sessione viene registrata
   d'ufficio invece di rifiutare con 404. Se la POST di `session_start`
   fallisce il client prosegue comunque la registrazione locale e invia i
   campioni allo Stop: rifiutarli significherebbe perdere la sessione.
4. **Evento malformato**: contato in `invalid` e saltato, non fa fallire la
   richiesta. Il client non ha retry: un 400 su una riga costerebbe l'intero
   batch da 300–800 campioni.
5. **Persistenza**: tabella eventi unica `timeline` con `payload` JSON, come
   suggerito dall'envelope comune.
6. **Idempotenza**: vincolo `UNIQUE(session_id, source, event_type, ts)` con
   `INSERT OR IGNORE`. Un reinvio manuale della stessa sessione non duplica.
7. **Timestamp**: epoch in secondi. Valori > 1e11 vengono interpretati come
   millisecondi (il plugin Moodle lavora in ms).

## Endpoint legacy

`/start-session`, `/stop-session`, `/event`, `/eeg-upload` restano attivi per
non rompere il plugin Moodle nella sua forma attuale. Da rimuovere quando il
plugin sarà migrato su `/api/sessions`.

## Ispezione del DB

```
python check_db.py     # ultimi eventi Moodle in timeline
python check_skew.py   # ultime misure di skew
```
