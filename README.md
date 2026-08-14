# syncronization_backend_moodle_idun

Backend di raccolta dati per il progetto C11326. Riceve gli eventi prodotti da
due sorgenti indipendenti — il client EEG (`EEGVisualizer.py`, IDUN Guardian 3)
e il plugin Moodle `local_eegimucapture` — li persiste su SQLite e li rende
disponibili per l'analisi su una timeline comune.

L'obiettivo del sistema è correlare nel tempo l'attività cerebrale registrata
dall'EEG con le azioni dello studente sulla piattaforma Moodle. Questo vincolo
determina la maggior parte delle scelte progettuali descritte in seguito.


## Architettura

Tre livelli, con dipendenze a senso unico dall'alto verso il basso e
dependency injection esplicita in `app/__init__.py`:

| Livello | Cartella | Responsabilità |
|---|---|---|
| API | `app/api/` | Validazione del formato della richiesta, codici HTTP, CORS |
| Servizi | `app/services/` | Logica di dominio; non dipende da Flask |
| Repository | `app/repository/` | Unico accesso a SQLite; nessuna logica di dominio |

Il livello dei servizi è indipendente dal framework web, in modo che la logica
di ingestione sia verificabile senza avviare un server HTTP.


## Avvio

```
venv\Scripts\Activate.ps1
python run.py
```

Il server ascolta su `http://127.0.0.1:8000`. I parametri (porta, percorso del
database, origini CORS ammesse) sono in `app/config.py`.


## Contratto di ingestione

```
POST /api/v1/events
Content-Type: application/json
```

Questo è l'unico endpoint esposto. Entrambe le sorgenti usano lo stesso URL, la
stessa struttura di messaggio e ricevono la stessa risposta; la distinzione
avviene sui campi `source` e `event_type`, non sull'indirizzo.

La scelta di un endpoint unico deriva dalla natura dei dati. Il flusso non è un
insieme di risorse da creare e modificare, ma un registro cronologico ad
accodamento (*append-only*) di eventi eterogenei provenienti da due sorgenti,
da ricomporre in un'unica sequenza temporale. Anche l'inizio e la fine di una
sessione sono eventi del registro: la sessione non è una risorsa separata, ma
un'informazione ricavata dalla sequenza. Da questa impostazione derivano il
nome dell'endpoint e l'assenza di verbi separati per aprire o chiudere una
sessione.

### Struttura del messaggio

Il corpo della richiesta è un **array JSON di eventi**, anche quando contiene
un solo elemento. Per tolleranza, un oggetto singolo non incapsulato viene
comunque accettato.

```json
[
  {
    "session_id": "20260812_114414",
    "timestamp": 1786527854.0963,
    "source": "eeg",
    "event_type": "sample",
    "payload": { "delta": 47.63, "theta": 12.63, "alpha": 5.986,
                 "sigma": 1.826, "beta": 5.341, "gamma": 0.8174 }
  }
]
```

| Campo | Obbligatorio | Note |
|---|---|---|
| `source` | sì | `"eeg"` oppure `"moodle"`; qualunque altro valore rende l'evento non valido |
| `event_type` | sì | vedi *Tipi di evento* |
| `timestamp` | sì | epoch in secondi o millisecondi (vedi sotto) |
| `session_id` | dipende | obbligatorio per `source: "eeg"`; assente per gli eventi Moodle, che lo ricevono dal backend |
| `payload` | no | oggetto JSON; un valore non-oggetto viene incapsulato in `{"value": ...}` |
| `description` | no | se assente o `null`, la calcola il backend (vedi *Descrizioni*) |

Un evento privo di `source` o di `event_type`, o con un `source` diverso dai
due previsti, viene contato come non valido e saltato, senza far fallire la
richiesta. Questa tolleranza è necessaria perché il client EEG non dispone di
un meccanismo di ritrasmissione automatica: un errore su una singola riga
farebbe perdere l'intera sessione, che contiene tipicamente da 300 a 800
campioni.

Un `source` non riconosciuto viene scartato invece di essere trattato come
Moodle per esclusione: erediterebbe l'identificatore della sessione EEG attiva
e una descrizione calcolata, entrando nella timeline come un evento legittimo.

### Risposta

Codice `201` con un riepilogo dell'esito:

```json
{ "received": 5, "stored": 5, "duplicates": 0, "invalid": 0,
  "no_timestamp": 0, "clock_skew_samples": 0,
  "sessions_opened": ["20260812_114414"], "sessions_superseded": [],
  "sessions_closed": [], "sessions_autoregistered": [] }
```

Il riepilogo serve alla verifica manuale e ai test; i client si limitano a
registrarlo nel proprio log. Due contatori vanno interpretati con attenzione:
`duplicates` indica righe già presenti, quindi un esito normale in caso di
ritrasmissione, mentre `no_timestamp` indica **dati perduti**.

La scrittura è sincrona: l'inserimento di 500 campioni richiede circa 20 ms,
ampiamente entro il timeout di 10 s del client. Non è quindi necessaria una
coda asincrona.


## Il campo `timestamp`

### Formato

Sono accettati sia i secondi sia i millisecondi dall'epoch Unix. La
discriminazione avviene con una soglia a `1e11`: valori superiori sono
interpretati come millisecondi e divisi per 1000, valori inferiori come
secondi. La soglia è priva di ambiguità perché `1e11` secondi corrisponde
all'anno 5138, mentre `1e11` millisecondi corrisponde al 1973: nessun
timestamp plausibile cade nell'intervallo sbagliato.

Il client EEG invia secondi in virgola mobile, il plugin Moodle millisecondi
interi. Entrambi i formati sono gestiti senza conversione a monte. Il valore
memorizzato è sempre in secondi.

### Obbligatorietà

Un evento il cui `timestamp` sia assente, `null`, non numerico, nullo o
negativo viene scartato e conteggiato in `no_timestamp`. Non è previsto alcun
ripiego sull'istante di arrivo al backend.

La motivazione è metodologica. Il ritardo introdotto dalla rete e
dall'accodamento è ignoto e variabile, quindi un timestamp assegnato al momento
della ricezione collocherebbe l'evento in una posizione errata della timeline.
Poiché la finalità del sistema è misurare la relazione temporale fra segnale
EEG e attività dello studente, un evento collocato in modo errato compromette
l'analisi in modo silenzioso, mentre un evento scartato resta visibile nel
contatore.

### Requisito di risoluzione

Il vincolo di unicità della tabella `timeline` è
`UNIQUE(session_id, source, event_type, ts)` e **non comprende il payload**.
Due eventi dello stesso tipo con lo stesso timestamp sono quindi
indistinguibili e uno dei due viene scartato come duplicato.

Ne segue che la risoluzione della sorgente del timestamp è vincolante: con
risoluzione di un secondo, tutti gli eventi dello stesso tipo emessi entro
quel secondo collassano in una sola riga. Su cinque eventi `input_change`
emessi entro un secondo:

| Sorgente | Risoluzione | Righe conservate |
|---|---|---|
| PHP `time()` | 1 s | 1 su 5 |
| JavaScript `Date.now()` | 1 ms | 5 su 5 |
| PHP `microtime(true)` | ~1 µs | 5 su 5 |

La risoluzione minima richiesta è quindi il millisecondo. Per riferimento, il
dispositivo IDUN campiona a 250 Hz circa, ossia un campione ogni ~4 ms.


## Tipi di evento

### Sorgente `eeg`

| `event_type` | Effetto |
|---|---|
| `session_start` | apre la sessione con l'identificatore scelto dal client e la rende attiva; la riga è comunque registrata in `timeline` |
| `sample` | riga in `timeline`; il payload contiene le sei potenze assolute di banda |
| `session_end` | chiude la sessione e ne aggiorna `row_count` |
| `ntp_check` | riga in `timeline`; verifica diagnostica di sincronizzazione dell'orologio |

### Sorgente `moodle`

Ogni evento produce una riga in `timeline`, con `session_id` assegnato dal
backend. Unica eccezione:

| `event_type` | Effetto |
|---|---|
| `clock_skew_measured` | scritto nella tabella `clock_skew`, non in `timeline`: è una misura diagnostica sullo scostamento fra gli orologi, non un comportamento dello studente |

L'elenco dei tipi riconosciuti è in `app/services/moodle_descriptions.py`. Un
tipo non presente in quell'elenco viene comunque registrato: cambia solo la
descrizione associata.


## Correlazione delle sessioni

È il meccanismo che rende possibile l'analisi congiunta delle due sorgenti.

1. Il client EEG genera l'identificatore di sessione e lo comunica con
   l'evento `session_start`. È l'unica autorità sull'identificatore.
2. Il backend conserva in memoria la sessione attiva corrente.
3. Il plugin Moodle non conosce l'identificatore e non lo invia: il backend
   assegna a ciascun evento Moodle quello della sessione attiva al momento
   della ricezione.

Da questo derivano tre comportamenti:

- **Nessuna sessione attiva.** L'evento Moodle è registrato con `session_id`
  nullo, non scartato: resta riallineabile in base al timestamp. Perché i dati
  risultino correlati, `session_start` deve precedere gli eventi Moodle.
- **Una sola sessione attiva per volta.** Un nuovo `session_start` chiude la
  sessione precedente, che viene riportata in `sessions_superseded`. Questo
  evita che una sessione resti aperta indefinitamente quando il client termina
  in modo anomalo, e rende non ambigua l'attribuzione degli eventi successivi.
- **Sessioni non annunciate.** Se la richiesta contenente `session_start` non
  arriva a destinazione, il client prosegue la registrazione locale e invia i
  campioni al termine. Il backend registra allora la sessione al primo campione
  ricevuto, segnalandola in `sessions_autoregistered`, invece di rifiutare i
  dati.

Lo stato della sessione attiva è mantenuto in memoria e non è persistito: al
riavvio del backend la sessione in corso va considerata interrotta.


## Idempotenza

L'inserimento avviene con `INSERT OR IGNORE` sul vincolo di unicità descritto
sopra. La ritrasmissione di un batch già ricevuto non produce duplicati, ed è
quindi un'operazione sicura.

Nel vincolo, le righe con `session_id` nullo sono sempre considerate distinte
fra loro, coerentemente con il trattamento di `NULL` in SQL. Gli eventi
registrati fuori sessione non vengono perciò mai scartati come duplicati.


## Descrizioni

Ogni riga di `timeline` porta una descrizione testuale leggibile dell'evento,
usata per l'ispezione manuale della sequenza.

Le descrizioni sono generate dal backend per tutti gli eventi: il plugin invia
`description: null` sia per gli eventi rilevati nel browser sia per quelli
originati dal server Moodle. Il modulo `app/services/moodle_descriptions.py` è
l'unica origine dei testi.

## Schema del database

File SQLite in `sessions/timeline.db`, in modalità WAL.

**`timeline`** — la sequenza di eventi.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER | chiave primaria |
| `session_id` | TEXT | nullo se l'evento è fuori sessione |
| `ts` | REAL | epoch in secondi |
| `source` | TEXT | `eeg` o `moodle` |
| `event_type` | TEXT | |
| `payload` | TEXT | oggetto JSON |
| `description` | TEXT | vuota per gli eventi EEG |

Vincolo `UNIQUE(session_id, source, event_type, ts)`; indice su
`(session_id, ts)`.

**`sessions`** — anagrafica delle sessioni: `session_id`, `started_at`,
`stopped_at`, `row_count`.

**`clock_skew`** — misure diagnostiche dello scostamento fra orologi:
`session_id`, `ts`, `skew_ms`, `uncertainty_ms`, `rtt_min_ms`, `samples`.


## Test

Dipendenze, da installare una volta nell'ambiente virtuale:

```
venv\Scripts\Activate.ps1
pip install pytest pytest-cov
```

Esecuzione dell'intera suite:

```
python -m pytest tests/
```

Con la copertura del codice, e l'elenco delle righe che nessun test esegue:

```
python -m pytest tests/ --cov=app --cov-report=term-missing
```

Ogni test riceve un database su file temporaneo, creato e rimosso da pytest:
l'esecuzione non tocca `sessions/timeline.db` e non altera i dati raccolti.

Varianti utili:

| Comando | Effetto |
|---|---|
| `python -m pytest tests/ -v` | un test per riga, con esito singolo |
| `python -m pytest tests/ -x` | si ferma al primo fallimento |
| `python -m pytest tests/test_ingest_contract.py` | un solo file |
| `python -m pytest tests/ -k timestamp` | solo i test il cui nome contiene "timestamp" |

Una copertura alta non garantisce che i test siano significativi: indica quali
righe vengono eseguite, non se il loro effetto viene verificato. Le righe
scoperte residue riguardano gli header CORS, il corpo della richiesta non
interpretabile come JSON e alcuni rami difensivi che il contratto attuale non
produce.

### Composizione della suite

| File | Tipo | Oggetto |
|---|---|---|
| `tests/test_ingest_contract.py` | integrazione | `POST /api/v1/events` attraverso tutti i livelli: route, servizio, repository, SQLite. Nessun mock |
| `tests/test_session_service.py` | unità | `SessionService` isolato: apertura, sostituzione e chiusura della sessione, autoregistrazione |
| `tests/test_moodle_descriptions.py` | unità | i modelli di descrizione, funzioni pure senza app né database |

Le fixture condivise sono in `tests/conftest.py`. La suite non comprende test
end-to-end: verificarli richiederebbe il backend in esecuzione come processo
separato, con il client EEG e il plugin reali.

### Verificare che un test sia significativo

Un test verde può non controllare nulla. Per accertarsene, si introduce
deliberatamente un guasto e si verifica che la suite lo rilevi. Esempio su
`_coerce_ts` in `app/services/timeline_service.py`: sostituire i due
`return None` con `return time.time()`, ripristinando il ripiego sull'istante
di arrivo. L'esecuzione deve segnalare il fallimento dei sei casi di
`test_event_without_valid_timestamp_is_rejected`. Ripristinato il codice, la
suite torna verde.


## Ispezione del database

```
python check_db.py     # ultimi eventi in timeline
python check_skew.py   # ultime misure di scostamento
```
