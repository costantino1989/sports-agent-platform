# Betting CLI

Tool CLI Python per raccogliere partite calcio da ESPN e generare output per analisi 1X2.

## Requisiti

- Python `>= 3.12`
- Dipendenze dal `pyproject.toml` (attualmente: `pydantic`)

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
| `--markdown-dir` | path | `output\match_markdowns` | Directory di output markdown. |
| `--weekly-output` | path | `output\current_week_matches.json` | File JSON output per il flusso weekly. |

`--build-markdowns` e `--save-current-week` sono mutualmente esclusivi.

## Formato output

### Weekly JSON

File: `output\current_week_matches.json`

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

Il dossier mantiene 16 sezioni; dalla sezione 4 in poi è reso in modo più conversazionale/tabellare (non dump JSON grezzo) con sanificazione dei campi tecnici non utili (`href`, `$ref`, `uid`, `id`, campi vuoti).

## Log

Logger colorato in console:

- `INFO`: verde
- `DEBUG`: blu
- `WARN`: giallo
- `ERROR`: rosso

Ogni riga include timestamp, classe/modulo e numero riga.

## Help

```powershell
python main.py --help
```
