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


## Endpoint legacy

`/start-session`, `/stop-session`, `/event`, `/eeg-upload` restano attivi per
non rompere il plugin Moodle nella sua forma attuale. Da rimuovere quando il
plugin sarà migrato su `/api/sessions`.

## Ispezione del DB

```
python check_db.py     # ultimi eventi Moodle in timeline
python check_skew.py   # ultime misure di skew
```
