# Betting CLI

Tool CLI Python per raccogliere partite calcio da ESPN e generare output per analisi 1X2.

## Requisiti

- Python `>= 3.12`
- Dipendenze dal `pyproject.toml` (Agno + client OpenAI incluse)

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

### 5. Flusso end-to-end predizione 1X2 (Agno + endpoint OpenAI-compatibile)

```powershell
python main.py --predict-1x2
```

Output predizioni di default: `output\predictions_1x2.md`.

### 6. Sync scheduler (persistenza SQLite + job minute30/minute60)

```powershell
python main.py --schedule-sync
```

Default DB path: `output\schedule_state.db`.

### 7. Tracciamento live (`--track-live`)

```powershell
python main.py --track-live
```

Esegue **un ciclo** di tracciamento: per ogni partita già iniziata fa un probe
economico (risultato/minuto/rossi) e **ricalcola la predizione solo se serve** —
dopo la prima predizione **ripredice solo** su gol contro il pronostico, nuovo
cartellino rosso, o ogni `PREDICTION_FORCE_REFRESH_EVERY` cicli (non a ogni ciclo:
evita di rieseguire l'LLM su dati invariati). Pensato per essere lanciato
periodicamente via cron, es. ogni 5 minuti:

```bash
# ogni 6 ore: aggiorna le partite della settimana (upcoming) + i job 30'/60'
0 */6 * * * cd /path/al/progetto && uv run python main.py --schedule-sync >> output/sync.log 2>&1
# ogni 5 minuti: tracciamento live (probe + predici/salta/blocca/liquida)
*/5 * * * * cd /path/al/progetto && uv run python main.py --track-live >> output/track_live.log 2>&1
```

Al lock la scommessa si "chiude": se la confidenza raggiunge `PREDICTION_LOCK_CONFIDENCE`
**oppure** la quota dell'esito previsto scende a `PREDICTION_LOCK_ODDS` (~1.2), si smette
di predire e si decide se/quanto scommettere (`PREDICTION_MIN_ODDS`, Kelly frazionario). Il
tracciamento **predice** solo sulle partite iniziate nelle ultime `PREDICTION_ACTIVE_WINDOW_HOURS`
ore; la **liquidazione** invece non è vincolata alla finestra: ogni scommessa bloccata e non ancora
liquidata viene comunque risolta col punteggio finale, anche se lo stato ESPN resta indietro
(status lag) o la partita è uscita dalla finestra prima di essere vista come conclusa.


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

By default the scheduler attempts to persist kickoff and scheduled times using the Europe/Rome timezone (ISO strings including the zone offset) so they match the local display you see on many web pages. This localized storage requires the system tzdata to be available (on some Windows Python installs tzdata is not bundled).

If tzdata is unavailable the code falls back to storing UTC ISO datetimes (preserving internal correctness). To enable localized storage, install tzdata into the runtime environment:

```powershell
pip install tzdata
```

Example: convert a UTC ISO timestamp to Europe/Rome for display (Python 3.9+):

```python
from datetime import datetime, timezone
import zoneinfo

iso = '2026-04-22T08:30:00+00:00'  # UTC timestamp from DB
utc_dt = datetime.fromisoformat(iso)
local_tz = zoneinfo.ZoneInfo('Europe/Rome')
local_dt = utc_dt.astimezone(local_tz)
print(local_dt.strftime('%Y-%m-%d %H:%M %Z'))  # 2026-04-22 10:30 CEST
```

If you prefer a different behaviour (for example persisting the original raw date string `kickoff_raw` or also adding an explicit `kickoff_local` field), that change is straightforward and can be added on request.

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

## Configurazione modello (predizione 1X2)

La predizione usa Agno su un endpoint OpenAI-compatibile. Variabili `.env` utilizzate:

- `ZEN_API_KEY` (obbligatoria: API key dell'endpoint)
- `ZEN_MODEL_ID` (default: `glm-5.2`; sul gateway zen è l'unico modello che supporta sia la structured-output sia il tool-calling, entrambi richiesti dalla pipeline)
- `ZEN_BASE_URL` (default: `https://opencode.ai/zen/go/v1` — senza `/chat/completions`)
- `MODEL_TIMEOUT_SECONDS` (default: `180`; un dossier live completo ~28KB richiede ~110s per la predizione strutturata)
- `PREDICTION_CONCURRENCY` (default: `4`)
- `PREDICTION_FORCE_REFRESH_EVERY` (default: `3`), `PREDICTION_RECENT_EVENTS` (default: `15`) — tracciamento live
- `ODDS_API_KEY` (opzionale): chiave di [The Odds API](https://the-odds-api.com/). Se
  impostata, il dossier e la predizione usano **quote reali di mercato** (di default il
  **Betfair Exchange**) al posto dello snapshot ESPN; senza chiave si usa il fallback ESPN.
- `ODDS_API_REGION` (default: `eu`), `ODDS_API_BOOKMAKER` (default: `betfair_ex_eu`),
  `ODDS_API_CACHE_MINUTES` (default: `3`, cache per lega per risparmiare crediti).
  Le quote reali sono disponibili solo per le leghe coperte dal provider (Serie A, top
  campionati, coppe UEFA, Mondiale, ecc.); per le leghe non coperte si ricade su ESPN.
- `TERMINAL_TIMEOUT_SECONDS` (default: `45`)
- `SCHEDULE_DB_PATH` (default: `output\schedule_state.db`)
- `SCHEDULE_STALE_MINUTES` (default: `30`)
- `SCHEDULE_MAX_ATTEMPTS` (default: `2`)

## Help

```powershell
python main.py --help
```
