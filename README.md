# Betting CLI

Tool CLI Python per raccogliere partite calcio da ESPN e generare output per analisi 1X2.

## Requisiti

- Python `>= 3.12`
- Dipendenze dal `pyproject.toml` (LangChain/LangGraph/Ollama incluse)

## Installazione

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

In alternativa, se usi `uv`:

```powershell
uv sync
```

## Uso rapido

### 1. Salvataggio partite della settimana corrente (default)

```powershell
python main.py
```

Output di default: `output\current_week_matches.json`.

### 2. Salvataggio settimanale con path custom

```powershell
python main.py --save-current-week --weekly-output output\my_week_matches.json
```

### 3. Generazione markdown dossier partite live di oggi

```powershell
python main.py --build-markdowns
```

Output di default: `output\match_markdowns`.

### 4. Generazione markdown con directory custom

```powershell
python main.py --build-markdowns --markdown-dir output\my_markdowns
```

### 5. Flusso end-to-end predizione 1X2 (LangGraph + Ollama)

```powershell
python main.py --predict-1x2
```

Output predizioni di default: `output\predictions_1x2.md`.

### 6. Sync scheduler (persistenza SQLite + job minute30/minute60)

```powershell
python main.py --schedule-sync
```

Default DB path: `output\schedule_state.db`.


## Regole di selezione per `--build-markdowns`

Vengono incluse solo le partite che rispettano tutte le condizioni:

1. data partita = **oggi** (UTC)
2. stato partita = **in progress** (`state == "in"`)
3. kickoff avvenuto da almeno **10 minuti**

Se non ci sono partite eleggibili, il comando termina senza file markdown.

## Argomenti CLI

| Argomento | Tipo | Default | Descrizione |
|---|---|---|---|
| `--build-markdowns` | flag | `False` | Genera un markdown per ogni match live eleggibile (oggi, in corso, >=10 min). |
| `--save-current-week` | flag | `False` | Salva le partite della settimana corrente. |
| `--predict-1x2` | flag | `False` | Flusso unico: genera i dossier markdown e poi produce un file markdown unico con predizioni 1X2. |
| `--schedule-sync` | flag | `False` | Sincronizza i match settimanali su SQLite e crea job per minuto 30 e minuto 60. |
| `--markdown-dir` | path | `output\match_markdowns` | Directory di output markdown. |
| `--weekly-output` | path | `output\current_week_matches.json` | File JSON output per il flusso weekly. |
| `--prediction-output` | path | `output\predictions_1x2.md` | File markdown unico con tabella predizioni 1X2. |
| `--schedule-db` | path | `output\schedule_state.db` | Path SQLite usato dalla schedulazione. |

`--build-markdowns`, `--save-current-week`, `--predict-1x2` e `--schedule-sync` sono mutualmente esclusivi.

## Formato output

### Weekly JSON

File: `output\current_week_matches.json`

Timezone handling

Kickoff times and timestamps stored by the scheduler and written to the DB are normalized to UTC (field `kickoff_utc` in the database and ISO datetime strings in the JSON output). When you compare times with web pages or local calendars, those services typically display a *local* time zone. To reproduce the same local view, convert the stored UTC timestamp to the desired timezone. Example (Python 3.9+):

```python
from datetime import datetime, timezone
import zoneinfo

iso = '2026-04-22T08:30:00+00:00'  # kickoff_utc from DB
utc_dt = datetime.fromisoformat(iso)
local_tz = zoneinfo.ZoneInfo('Europe/Rome')
local_dt = utc_dt.astimezone(local_tz)
print(local_dt.strftime('%Y-%m-%d %H:%M %Z'))  # 2026-04-22 10:30 CEST
```

If you prefer a different behaviour (for example persisting the original raw date string `kickoff_raw` or also adding a `kickoff_local` field), that change is straightforward and can be added on request.

Struttura ad alto livello:

```json
{
  "generated_at_utc": "...",
  "week_start_utc": "...",
  "week_end_utc": "...",
  "data": {
    "YYYY-MM-DD": {
      "league.slug": {
        "description": "...",
        "matches_by_time": {
          "HH:MM": [
            {
              "event": { "...": "..." },
              "competition": { "...": "..." },
              "teams": [ { "...": "..." } ]
            }
          ]
        }
      }
    }
  },
  "match_count": 0,
  "fetch_errors": []
}
```

### Markdown dossier

Directory: `output\match_markdowns`

Naming file: `<league_slug>_<event_id>.md` (esempio: `eng_3_745657.md`).

Il dossier mantiene 14 sezioni; dalla sezione 4 in poi è reso in modo più conversazionale/tabellare (non dump JSON grezzo) con sanificazione dei campi tecnici non utili (`href`, `$ref`, `uid`, `id`, campi vuoti).

### Predizioni 1X2 markdown

File: `output\predictions_1x2.md`

La tabella contiene una riga per match con:

- match
- risultato predetto (1/X/2)
- probabilità di successo
- motivazione dettagliata con riferimenti evidenze
- campo outcome vuoto (da valorizzare in futuro)

## Log

Logger colorato in console:

- `INFO`: verde
- `DEBUG`: blu
- `WARN`: giallo
- `ERROR`: rosso

Ogni riga include timestamp, classe/modulo e numero riga.

## Configurazione Ollama (predizione 1X2)

Variabili `.env` utilizzate:

- `OLLAMA_MODEL` (default: `gemma4:latest`)
- `OLLAMA_BASE_URL` (default: `http://localhost:11434`)
- `TERMINAL_TIMEOUT_SECONDS` (default: `45`)
- `SCHEDULE_DB_PATH` (default: `output\schedule_state.db`)
- `SCHEDULE_STALE_MINUTES` (default: `30`)
- `SCHEDULE_MAX_ATTEMPTS` (default: `2`)

## Help

```powershell
python main.py --help
```
