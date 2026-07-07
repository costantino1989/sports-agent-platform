"""Tests for the live prediction cycle orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
)
from src.prediction.live_decision import LastPrediction, MatchState
from src.prediction.models import PredictionResult
from src.prediction.service.live import LivePredictionService

NOW = datetime(2026, 7, 3, 14, 10, tzinfo=timezone.utc)


def _match(event_id: str) -> MatchRecordModel:
    return MatchRecordModel(
        league=LeagueModel(slug="chn.1", name="CSL"),
        event=EventModel(id=event_id),
        competition=CompetitionModel(id="c"),
        teams=[],
        api_refs=ApiReferencesModel(summary="s", core_competition="c"),
    )


def _result(pred="2", prob=85) -> PredictionResult:
    return PredictionResult(
        match="A vs B", predicted_result=pred, success_probability=prob,
        rationale="r", evidence_refs=[], source_file="f.md", outcome="",
    )


class _FakeMatchRepo:
    def __init__(self, matches): self._m = matches
    def get_started_matches(self, now_utc, active_window_hours=None): return self._m
    def get_match_record(self, event_id): return _match(event_id)


class _FakePredRepo:
    def __init__(self, last=None): self._last = dict(last or {}); self.upserts = []
    def get_last(self, event_id): return self._last.get(event_id)
    def upsert(self, **kw): self.upserts.append(kw); self._last[kw["event_id"]] = LastPrediction(
        predicted_result=kw["predicted_result"], success_probability=kw["success_probability"],
        home_score=kw["home_score"], away_score=kw["away_score"], red_cards=kw["red_cards"],
        cycles_since_full=kw["cycles_since_full"])


class _FakeBetRepo:
    def __init__(self, locked=None): self.rows = dict(locked or {}); self.settlements = {}
    def is_locked(self, event_id): return event_id in self.rows
    def lock(self, event_id, predicted_result, model_prob, odds, minute, locked_at,
             rationale=None, evidence=None, bookmaker=None, synthetic=False):
        self.rows[event_id] = SimpleNamespace(
            predicted_result=predicted_result, model_prob=model_prob, odds=odds,
            settled=False, outcome=None, rationale=rationale, evidence=evidence or [],
            bookmaker=bookmaker, synthetic=synthetic)
    def get(self, event_id): return self.rows.get(event_id)
    def list_all(self):
        return [SimpleNamespace(event_id=eid, settled=row.settled)
                for eid, row in self.rows.items()]
    def settle(self, event_id, final_home, final_away, outcome):
        self.rows[event_id].settled = True
        self.rows[event_id].outcome = outcome
        self.settlements[event_id] = outcome


class _FakeStatusRepo:
    def __init__(self): self.rows = {}
    def upsert(self, event_id, action, reason, updated_at):
        self.rows[event_id] = SimpleNamespace(action=action, reason=reason)


def _service(matches, states, pred_repo, calls, bet_repo=None, result_prob=85,
             dossier_path=None, status_repo=None, bet_provider_hints=None,
             predict_error=None, synthetic_odds=None):
    def prober(match): return states.get(match.event.id)
    def dossier_runner(match):
        calls["dossier"].append(match.event.id)
        return dossier_path if dossier_path is not None else Path(f"{match.event.id}.md")
    def predictor(path):
        calls["predict"].append(str(path))
        if predict_error is not None:
            raise predict_error
        return _result(prob=result_prob)
    return LivePredictionService(
        match_repo=_FakeMatchRepo(matches), prediction_repo=pred_repo,
        bet_repo=bet_repo or _FakeBetRepo(),
        prober=prober, dossier_runner=dossier_runner, predictor=predictor,
        force_refresh_every=6, lock_confidence=80,
        lock_odds=1.25, min_odds=1.2, kelly_fraction=0.5, active_window_hours=3,
        max_bet_minute=80, status_repo=status_repo,
        bet_provider_hints=bet_provider_hints, synthetic_odds=synthetic_odds,
    )


def _odds_dossier(tmp_path, provider, home="8.0", draw="5.25", away="1.29"):
    dossier = tmp_path / "e1.md"
    dossier.write_text(
        "## 6. Current live statistics\n"
        "| Minute | Team | Event | Impact |\n"
        "| --- | --- | --- | --- |\n"
        "| 12' | Away | Goal | Score changed |\n\n"
        "## 8. Odds\n"
        "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| {provider} | Current | {home} | {draw} | {away} |\n",
        encoding="utf-8",
    )
    return dossier


class TestRunCycle:
    def test_new_match_predicts_and_persists(self) -> None:
        calls = {"dossier": [], "predict": []}
        repo = _FakePredRepo()
        svc = _service([_match("e1")], {"e1": MatchState(1, 0, 0, 20, False)}, repo, calls)
        outcomes = svc.run_cycle(now=NOW)
        assert calls["dossier"] == ["e1"] and calls["predict"] == ["e1.md"]
        assert repo.upserts[0]["cycles_since_full"] == 0
        assert outcomes[0].action == "predict"

    def test_confident_stable_skips_without_predicting(self) -> None:
        calls = {"dossier": [], "predict": []}
        last = {"e1": LastPrediction("1", 88, 1, 0, 0, 0)}
        repo = _FakePredRepo(last)
        svc = _service([_match("e1")], {"e1": MatchState(1, 0, 0, 30, False)}, repo, calls)
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == []          # LLM skipped
        assert outcomes[0].action == "skip"
        assert repo.upserts[0]["cycles_since_full"] == 1   # bumped

    def test_goal_against_pick_triggers_prediction(self) -> None:
        calls = {"dossier": [], "predict": []}
        last = {"e1": LastPrediction("1", 88, 1, 0, 0, 2)}
        repo = _FakePredRepo(last)
        svc = _service([_match("e1")], {"e1": MatchState(1, 1, 0, 55, False)}, repo, calls)
        svc.run_cycle(now=NOW)
        assert calls["predict"] == ["e1.md"]
        assert repo.upserts[0]["cycles_since_full"] == 0   # reset

    def test_finished_match_marks_done_without_predicting(self) -> None:
        calls = {"dossier": [], "predict": []}
        last = {"e1": LastPrediction("1", 88, 2, 1, 0, 0)}
        repo = _FakePredRepo(last)
        svc = _service([_match("e1")], {"e1": MatchState(2, 1, 0, 90, True)}, repo, calls)
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == []
        assert outcomes[0].action == "done"
        assert repo.upserts[0]["status"] == "done"

    def test_model_unavailable_skips_and_persists_nothing(self) -> None:
        # Model out of credits (or any failure): no prediction is fabricated and
        # nothing is written to the prediction repo — the data stays clean.
        from src.prediction.models import PredictionUnavailableError

        calls = {"dossier": [], "predict": []}
        repo = _FakePredRepo()
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(1, 0, 0, 20, False)}, repo, calls,
            bet_repo=bets, predict_error=PredictionUnavailableError("no credits"),
        )
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == ["e1.md"]           # the model was attempted
        assert repo.upserts == []                       # but nothing persisted
        assert bets.is_locked("e1") is False            # no bet
        assert outcomes[0].action == "skip"
        assert outcomes[0].reason == "model_unavailable"

    def test_missing_probe_is_skipped_safely(self) -> None:
        calls = {"dossier": [], "predict": []}
        repo = _FakePredRepo()
        svc = _service([_match("e1")], {"e1": None}, repo, calls)
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == [] and outcomes[0].action == "skip"
        assert outcomes[0].reason == "no_state"

    def test_confident_prediction_locks_bet(self, tmp_path: Path) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(1, 0, 0, 20, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "DraftKings"),
        )
        svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is True
        assert bets.get("e1").predicted_result == "2"

    def test_locked_bet_records_odds_and_bookmaker(self, tmp_path: Path) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 2, 0, 45, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "DraftKings - Live Odds"),
        )
        svc.run_cycle(now=NOW)
        locked = bets.get("e1")
        assert locked.odds == 1.29
        assert locked.bookmaker == "DraftKings - Live Odds"

    def test_late_match_locks_at_relaxed_threshold(self, tmp_path: Path) -> None:
        # 65% at minute 80: base 80 relaxes to 60 late -> locks.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 1, 0, 80, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=65,
            dossier_path=_odds_dossier(tmp_path, "Betfair"),
        )
        svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is True

    def test_early_match_does_not_lock_at_65(self, tmp_path: Path) -> None:
        # 65% at minute 50: full 80 threshold, odds 1.29 > lock_odds -> no lock.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 1, 0, 50, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=65,
            dossier_path=_odds_dossier(tmp_path, "Betfair"),
        )
        svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is False

    def test_no_lock_when_no_allowed_bookmaker(self, tmp_path: Path) -> None:
        # Only DraftKings odds, but betting is restricted to Betfair/Bet365.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 2, 0, 45, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "DraftKings - Live Odds"),
            bet_provider_hints=("betfair", "bet365"),
        )
        outcomes = svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is False           # no usable book -> no bet
        assert outcomes[0].reason == "no_usable_odds"

    def test_synthetic_bet_when_no_real_odds_and_confident(self, tmp_path: Path) -> None:
        # No allowed bookmaker odds -> simulate a bet at the synthetic price,
        # tagged synthetic, when confidence clears the (time-relaxed) threshold.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 2, 0, 45, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "DraftKings - Live Odds"),
            bet_provider_hints=("betfair", "bet365"), synthetic_odds=1.2,
        )
        outcomes = svc.run_cycle(now=NOW)
        locked = bets.get("e1")
        assert locked is not None and locked.synthetic is True
        assert locked.odds == 1.2 and locked.bookmaker == "Sintetica"
        assert outcomes[0].reason == "locked_bet"

    def test_no_synthetic_bet_below_threshold(self, tmp_path: Path) -> None:
        # Confidence under the threshold -> tracked, no synthetic bet placed.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 1, 0, 30, False)},  # early, base 80
            _FakePredRepo(), calls, bet_repo=bets, result_prob=70,   # 70 < 80
            dossier_path=_odds_dossier(tmp_path, "DraftKings"),
            bet_provider_hints=("betfair", "bet365"), synthetic_odds=1.2,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is False
        assert outcomes[0].reason == "no_usable_odds"

    def test_synthetic_respects_time_relaxed_threshold(self, tmp_path: Path) -> None:
        # 65% at minute 80: base 80 relaxes to 60 -> synthetic bet placed.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 1, 0, 80, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=65,
            dossier_path=_odds_dossier(tmp_path, "DraftKings"),
            bet_provider_hints=("betfair", "bet365"), synthetic_odds=1.2,
        )
        svc.run_cycle(now=NOW)
        assert bets.get("e1").synthetic is True

    def test_no_synthetic_bet_when_disabled(self, tmp_path: Path) -> None:
        # synthetic_odds None (disabled) -> old behaviour: no bet, no_usable_odds.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 2, 0, 45, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "DraftKings"),
            bet_provider_hints=("betfair", "bet365"), synthetic_odds=None,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is False
        assert outcomes[0].reason == "no_usable_odds"

    def test_locks_when_allowed_bookmaker_present(self, tmp_path: Path) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 2, 0, 45, False)},
            _FakePredRepo(), calls, bet_repo=bets, result_prob=88,
            dossier_path=_odds_dossier(tmp_path, "Betfair Exchange"),
            bet_provider_hints=("betfair", "bet365"),
        )
        svc.run_cycle(now=NOW)
        assert bets.is_locked("e1") is True
        assert bets.get("e1").bookmaker == "Betfair Exchange"

    def test_locked_match_skips_until_finished(self) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo({"e1": SimpleNamespace(predicted_result="2", settled=False)})
        svc = _service(
            [_match("e1")], {"e1": MatchState(1, 0, 0, 55, False)},
            _FakePredRepo(), calls, bet_repo=bets,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == []               # no work while locked
        assert outcomes[0] .action == "skip" and outcomes[0].reason == "locked"

    def test_no_bet_past_max_minute(self) -> None:
        calls = {"dossier": [], "predict": []}
        svc = _service(
            [_match("e1")], {"e1": MatchState(3, 1, 0, 85, False)},  # minute 85 > 80
            _FakePredRepo(), calls,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert calls["dossier"] == [] and calls["predict"] == []  # no build, no LLM
        assert outcomes[0].action == "skip" and outcomes[0].reason == "past_bet_window"

    def test_match_without_play_by_play_is_skipped(self, tmp_path: Path) -> None:
        dossier = tmp_path / "e1.md"
        dossier.write_text(
            "## 6. Current live statistics\n"
            "No data found (source: ESPN API, section: Current live statistics).\n\n"
            "## 7. News\n",
            encoding="utf-8",
        )
        calls = {"dossier": [], "predict": []}
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 0, 0, 30, False)},
            _FakePredRepo(), calls, dossier_path=dossier,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert calls["predict"] == []  # LLM skipped: no play-by-play coverage
        assert outcomes[0].action == "skip" and outcomes[0].reason == "no_play_by_play"

    def test_predicts_on_stats_when_play_by_play_empty(self, tmp_path: Path) -> None:
        # A covered but quiet match: empty section 6 event timeline, but real
        # section 4 boxscore stats -> predict (on stats + baseline), not skip.
        dossier = tmp_path / "e1.md"
        dossier.write_text(
            "## 4. Team statistics\n"
            "| Metric | Home | Away |\n| --- | --- | --- |\n"
            "| Possession Pct | 62.0 | 38.0 |\n| Total Shots | 9 | 3 |\n\n"
            "## 6. Current live statistics\n"
            "No data found (source: ESPN API, section: Current live statistics).\n\n"
            "## 7. News\n",
            encoding="utf-8",
        )
        calls = {"dossier": [], "predict": []}
        svc = _service(
            [_match("e1")], {"e1": MatchState(0, 0, 0, 30, False)},
            _FakePredRepo(), calls, dossier_path=dossier,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert len(calls["predict"]) == 1            # predicted, not skipped
        assert outcomes[0].action == "predict"

    def test_locked_match_settles_on_finish(self) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo(
            {"e1": SimpleNamespace(predicted_result="2", settled=False, outcome=None)}
        )
        svc = _service(
            [_match("e1")], {"e1": MatchState(2, 1, 0, 90, True)},  # 2-1 home win
            _FakePredRepo(), calls, bet_repo=bets,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert outcomes[0].action == "done" and outcomes[0].reason == "bet_settled"
        assert bets.settlements["e1"] == "lost"     # picked away, home won

    def test_settled_bet_not_re_emitted_next_cycle(self) -> None:
        # A locked+finished match stays in the active window for hours; it must
        # emit "bet_settled" ONLY on the cycle it actually settles, otherwise the
        # Telegram settlement message is re-sent every cycle.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo(
            {"e1": SimpleNamespace(predicted_result="2", settled=False, outcome=None)}
        )
        svc = _service(
            [_match("e1")], {"e1": MatchState(2, 1, 0, 90, True)},
            _FakePredRepo(), calls, bet_repo=bets,
        )
        first = svc.run_cycle(now=NOW)
        assert first[0].action == "done" and first[0].reason == "bet_settled"
        second = svc.run_cycle(now=NOW)   # same finished match, still in window
        assert second[0].reason != "bet_settled"   # not re-notified

    def test_stale_pending_bet_out_of_window_is_settled(self) -> None:
        # A locked bet whose match has dropped out of the active window (too old
        # to be returned by get_started_matches) must still be settled, even if
        # ESPN's status has not flipped to "finished" (status lag). Its current
        # score is effectively final.
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo(
            {"e9": SimpleNamespace(predicted_result="2", settled=False, outcome=None)}
        )
        svc = _service(
            [],  # out of window: nothing started this cycle
            {"e9": MatchState(0, 2, 0, 95, False)},  # away leads, ESPN not flagged done
            _FakePredRepo(), calls, bet_repo=bets,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert bets.settlements["e9"] == "won"      # picked away, away won 0-2
        assert any(
            o.event_id == "e9" and o.action == "done" for o in outcomes
        )

    def test_settled_bet_out_of_window_is_not_reprocessed(self) -> None:
        calls = {"dossier": [], "predict": []}
        bets = _FakeBetRepo(
            {"e9": SimpleNamespace(predicted_result="2", settled=True, outcome="won")}
        )
        svc = _service(
            [], {"e9": MatchState(0, 2, 0, 95, True)},
            _FakePredRepo(), calls, bet_repo=bets,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert outcomes == []                        # already settled: no work

    def test_cycle_decisions_are_persisted_to_status_repo(self) -> None:
        calls = {"dossier": [], "predict": []}
        status = _FakeStatusRepo()
        svc = _service(
            [_match("e1")], {"e1": MatchState(1, 0, 0, 20, False)},
            _FakePredRepo(), calls, status_repo=status,
        )
        outcomes = svc.run_cycle(now=NOW)
        assert status.rows["e1"].action == outcomes[0].action
        assert status.rows["e1"].reason == outcomes[0].reason

    def test_skip_reason_is_persisted(self) -> None:
        calls = {"dossier": [], "predict": []}
        status = _FakeStatusRepo()
        # No probe state -> skip with reason "no_state" that would otherwise
        # leave no record in predictions/bets.
        svc = _service([_match("e1")], {"e1": None}, _FakePredRepo(), calls,
                       status_repo=status)
        svc.run_cycle(now=NOW)
        assert status.rows["e1"].action == "skip"
        assert status.rows["e1"].reason == "no_state"

    def test_no_status_repo_still_works(self) -> None:
        calls = {"dossier": [], "predict": []}
        svc = _service([_match("e1")], {"e1": MatchState(1, 0, 0, 20, False)},
                       _FakePredRepo(), calls)  # status_repo defaults to None
        outcomes = svc.run_cycle(now=NOW)
        assert outcomes[0].action == "predict"   # no crash without a status repo
