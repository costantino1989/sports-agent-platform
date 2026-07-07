# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI (`main.py`) that ingests soccer data from ESPN's public APIs and drives an end-to-end **1X2 prediction** workflow. It has grown from a simple fetch-and-render tool into three cooperating subsystems: ESPN ingestion + markdown dossiers, a SQLite-backed scheduler, and an Agno prediction agent (OpenAI-compatible endpoint).

Note: the repo folder is `sports-agent-platform` but the package is named `betting` (`pyproject.toml`). The README is in Italian; all code, comments, and docstrings are English (this is an enforced rule — see Conventions).

## Commands

```bash
uv sync                                   # install deps (or: pip install -e .)

uv run python main.py --save-current-week # save current-week schedule -> output/current_week_matches.json (also the no-flag default path)
uv run python main.py --schedule-sync     # sync weekly matches into SQLite + ensure minute30/minute60 jobs -> output/schedule_state.db
uv run python main.py --track-live        # one live-tracking cycle: probe started matches, re-predict only those that changed (run via cron ~5 min)
uv run python main.py --build-markdowns   # build dossiers for runs due in the DB -> output/match_markdowns/
uv run python main.py --predict-1x2       # build dossiers for due runs, then run 1X2 prediction -> output/predictions_1x2.md
uv run python main.py --help
```

`--build-markdowns`, `--predict-1x2`, and `--schedule-sync` are mutually exclusive.

### Lint / format / typecheck (Makefile, via `uvx`)

```bash
make ci            # lint + format-check + typecheck (no writes) — the CI gate
make all           # fix + format + typecheck
make lint          # ruff check src
make fix           # ruff check src --fix
make format        # ruff format src
make typecheck     # mypy src
make fix-plr       # auto-convert self-less methods to @staticmethod (ruff PLR6301)
```

Tests live in `tests/` (pytest). `pydantic`, `agno`, `openai`, `ddgs` + `beautifulsoup4` (for Agno's web search + scraping tools), and `tzdata` are the runtime deps; ESPN access uses stdlib `urllib`, concurrency uses `asyncio` + threads.

## Environment config (`src/utils/config.py`)

Reads an optional project-root `.env` (a simple `KEY=VALUE` parser, not python-dotenv) into `os.environ`, cached via `lru_cache`. Settings:

- `MATCH_CONCURRENCY_DEFAULT` (5) — max dossiers built in parallel.
- `FETCH_CONCURRENCY_DEFAULT` (12) — max concurrent ESPN HTTP calls across all builds.
- `ZEN_MODEL_ID` (`glm-5.2`), `ZEN_BASE_URL` (`https://opencode.ai/zen/go/v1`), `ZEN_API_KEY` (empty) — Agno prediction agent (OpenAI-compatible endpoint). The pipeline needs **both** structured output (`output_schema`, for the prediction) and tool-calling (for deep web research). Verified on this gateway, **only `glm-5.2` supports both**. Others fail one axis: `kimi-k2.6` = structured only (no tools → deep branch degrades to dossier-only); `deepseek-v4-pro`/`qwen3.7-max` = tools only (no structured output → always falls back); `minimax-m3` = invalid structured output on the real schema (and can hang); `kimi-k2.7-code`/`deepseek-v4-flash`/`qwen3.7-plus` = neither. `MODEL_TIMEOUT_SECONDS` (180) — HTTP timeout per model request; a full ~28KB live dossier needs ~110s for the structured prediction. The deep branch's research is bounded (`RESEARCH_TOOL_CALL_LIMIT`) and best-effort: if it finds nothing (or scrapes 403), the prediction still runs on the dossier alone.
- `PREDICTION_CONCURRENCY` (4) — max matches predicted in parallel.
- `PREDICTION_LOCK_CONFIDENCE` (80), `PREDICTION_FORCE_REFRESH_EVERY` (3), `PREDICTION_RECENT_EVENTS` (15) — live-tracking (`--track-live`): after the first prediction a match is re-predicted **only** on a goal against the pick, a new red card, or every `FORCE_REFRESH_EVERY` cycles (not every cycle — avoids re-running the LLM on unchanged data); **lock the bet** at/above lock-confidence (then stop and settle at FT); play-by-play events kept in the model prompt. Betting: `betting.py` (EV+ filter with min-odds 1.2, fractional Kelly, bankroll P/L per budget), locked bets persist in `match_bets`, settled won/lost at full-time. Lock triggers on `PREDICTION_LOCK_CONFIDENCE` **or** when the predicted outcome's odds fall to `PREDICTION_LOCK_ODDS` (~1.2). Betting knobs: `PREDICTION_MIN_ODDS` (1.2), `PREDICTION_LOCK_ODDS` (1.25), `PREDICTION_KELLY_FRACTION` (0.25); `PREDICTION_ACTIVE_WINDOW_HOURS` (3) bounds which started matches the live loop probes. `PREDICTION_MAX_BET_MINUTE` (80) — no bet is locked past this match minute (markets are pulled and the outcome is near-decided).
- `TERMINAL_TIMEOUT_SECONDS` (45) — timeout for the agent's safe-terminal tool.
- `SCHEDULE_DB_PATH` (`output/schedule_state.db`), `SCHEDULE_STALE_MINUTES` (30), `SCHEDULE_MAX_ATTEMPTS` (2) — scheduler.

## Architecture

`main.py` wires everything with `build_*` factory functions (manual dependency injection). A single `EspnSoccerClient` is shared across all flows. The system is three subsystems that hand off through the SQLite DB and the markdown filesystem.

### Subsystem 1 — ESPN ingestion + dossiers (`src/espn/`, `src/dossier/`, `src/models/`)
- `EspnSoccerClient` (`src/espn/client.py`) is the only code that touches the network; `fetch_json(url)` wraps `urllib` and raises `EspnApiError` on any failure. Two API hosts are used: `site.api.espn.com` (site v2) and `sports.core.api.espn.com` (core v2).
- `DossierDataClient` (`src/dossier/client.py`) exposes one method per ESPN endpoint (summary, core event/competition/plays/situation/probabilities/odds, standings, rankings, news, leaders, roster, injuries, schedule, athlete).
- **Dossier build** (`MatchDossierAction` → `MatchDossierBuilder.build_many`, `src/dossier/builder.py`): the concurrency core, run under `asyncio.run`. An `asyncio.Semaphore` bounds parallel *matches*; a `threading.BoundedSemaphore` bounds parallel *fetches* (blocking `urllib` calls pushed to threads via `asyncio.to_thread`). Endpoints fire in two phases (base fetch, then aggregation depending on `season_year`/`summary`). League-scoped endpoints (standings/rankings/news/leaders) are deduped across matches via `LeaguePayloadTaskCache` (`fetch_cache.py`) — fetched once per league.
- Fetch errors never raise past `DossierFetchFacade.safe_fetch` (`builder_fetch.py`) — they become `EndpointPayload` errors, so one bad endpoint never kills a run.
- **Render** (`MatchMarkdownRenderer.render`, `src/dossier/render.py`) emits **14 fixed sections**, delegating to `render_flow.py` and `render_context.py`; `render_tools.py` sanitizes technical noise (`href`, `$ref`, `uid`, `id`, empty fields). Missing data renders a "No data found… verify via web search" line. Filename: `<league_slug_dots_as_underscores>_<event_id>.md`.

### Subsystem 2 — Scheduler + SQLite persistence (`src/schedule/`)
- `WeeklyMatchesAction` (`src/schedule/weekly.py`) + `WeeklyScoreboardCollector` fetch every league × every day of the current UTC week concurrently, filter to upcoming, dedup, and group as `data[date][league.slug].matches_by_time[HH:MM]` (pydantic `weekly_models.py`).
- `ScheduleDatabase` (`db.py`) owns the SQLite connection; `MatchRepository` / `RunRepository` (`repositories/`) persist matches and scheduled runs. `ScheduleIngestionService.sync()` (`services/ingestion.py`) writes matches and ensures **minute30 / minute60** runs per match.
- **Important design shift:** `ScheduleDispatcherService` (`services/dispatcher.py`) **no longer executes runs** — it exposes only `sync_only()` (the old `run_tick` was removed). Execution is now pull-based: `--build-markdowns` and `--predict-1x2` read due runs from the DB via `RunRepository.get_pending_runs_due()` and build dossiers for them. `sync_only()` has defensive checks that force ingestion to come from the ESPN API path only.
- Kickoff/scheduled times are stored in Europe/Rome when `tzdata` is available (now a dependency), falling back to UTC.

### Subsystem 3 — 1X2 prediction (`src/prediction/`)
- `PredictionMarkdownPipeline` (`service/pipeline.py`) runs `MatchPredictionAgent` over each dossier markdown file and writes one consolidated `predictions_1x2.md` (table: match / predicted 1X2 / success probability / rationale + evidence refs / outcome). On per-file failure it emits a fallback row ("X", 50%) rather than aborting the batch.
- `MatchPredictionAgent` (`agents/predictor.py`, plus `rule_scan.py`) runs on **Agno** against an OpenAI-compatible endpoint. It branches on the deterministic rule scan. The **fast branch** (no high-priority signal) calls a tool-less structured agent directly on the dossier. The **deep branch** (high-priority signal: missing data / inconsistency / odds anomaly) is **two-phase**: (1) a `_research_agent` with Agno `WebSearchTools` (returns links) + `WebsiteTools` (scrapes a link) and no `output_schema` gathers external evidence, then (2) the structured `_prediction_agent` turns dossier + findings into the result. The split exists because on this gateway `output_schema` suppresses tool calls. Both paths emit `PredictionDraft` merged into `PredictionResult`. Supporting pieces: `tools/toolkit.py` (project browser/terminal callables), `skills/`, `prompts/loader.py`, `models.py`. The batch pipeline predicts matches concurrently (bounded by `PREDICTION_CONCURRENCY`).
- **Live tracking** (`--track-live`, `service/live.py`): for periodic re-evaluation (cron ~5 min). Per started match: a cheap probe (`live_probe.parse_match_state` — score/minute/finished/red-cards from the summary) feeds `live_decision.decide_action`, which **skips** the expensive LLM call after the first prediction and only re-predicts on a goal against the pick, a new red card, or after `PREDICTION_FORCE_REFRESH_EVERY` skip cycles (confidence does not force a re-prediction — the state only changes via events or accumulated play-by-play). Last prediction + state persist in `match_predictions` (`repositories/prediction_repo.py`). The model prompt is compacted (`prompt_compact.py`, keeps `PREDICTION_RECENT_EVENTS` play-by-play rows) so a large live dossier doesn't time out — the full dossier stays on disk. Matches in competitions ESPN does not cover with play-by-play (e.g. League of Ireland) are **skipped** before the LLM call (`has_play_by_play` on the built dossier — their data is too thin for a useful prediction).

### Models (`src/models/`)
Pydantic throughout: `live_models.py` (dossier/selection records), `weekly_models.py` (weekly JSON payload), `dossier.py` (`EndpointPayload.has_data()`, `MatchDossierData`, `TeamDossierData`), `schedule.py` (`MatchSnapshotRecord`, `ScheduleTickResult`), `leagues.py` (`LEAGUES`: frozen tuple of ~169 `LeagueDefinition` slug/name pairs — the fixed universe both flows scan).

### Cross-cutting utils (`src/utils/`)
- `color_logger.py` — `get_logger()`, used everywhere as module-level `LOGGER`.
- `timing.py` — `@log_execution_time` decorator (sync + async; `label`, `reference_arg`, `log_level`).

## Reference

`docs/soccer.md` documents ESPN's soccer API surface (all league slugs, endpoint shapes). Consult it when adding endpoints or leagues.

## Cognitive complexity

Do not write functions with high cognitive complexity. Keep every function at or
below the SonarQube Cognitive Complexity limit of **15** — never produce code
that triggers warnings like *"Refactor this function to reduce its Cognitive
Complexity from N to the 15 allowed."*

Rules:
- Before finishing a function, mentally check its nesting and branching; if it
  is approaching the limit, extract helpers, use early returns / guard clauses,
  and flatten nested conditionals.
- Prefer several small, single-purpose functions over one large branchy one.
- This applies to new code and to any function you modify: leave it at or below
  the limit, not worse than you found it.

## Code language

All code comments and docstrings must be written in English.

Rules:
- Write every new comment and docstring in English.
- When modifying code, translate any comment or docstring you touch into English
  if it is not already; leave the surrounding language as-is only when out of scope.

## Variable naming

Do not use acronyms or single letters as variable names. Names must be explicit
and follow standard Python naming conventions (PEP 8).

Rules:
- Use descriptive, full-word names (e.g. `response`, `user_index`, `document_count`),
  not `r`, `ui`, `dc`, or opaque acronyms.
- Use `snake_case` for variables and functions, `PascalCase` for classes, and
  `UPPER_SNAKE_CASE` for constants.
- This applies to new code and to any variable you rename or introduce while
  modifying existing code; leave names at least as clear as you found them.
- Narrowly-scoped loop indices or math-domain conventions are acceptable only
  when they are the established idiom and improve readability.

## Other conventions

- **Docstrings:** Google-style with `Args:` / `Returns:` / `Raises:` on every module/class/function — match the existing style.
