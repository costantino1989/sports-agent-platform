"""Live prediction cycle: probe each started match, then skip or re-predict.

A confident, stable prediction is not recomputed (the LLM call dominates cost);
it is only re-run when the score moves against the pick, a red card appears, or a
bounded number of skip cycles have elapsed. State is persisted per match so the
decision survives across cycles (e.g. a cron every few minutes).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.prediction.betting import (
    capped_kelly_stake,
    is_bettable,
    select_predicted_odds,
    settle_bet,
)
from src.prediction.models import PredictionUnavailableError
from src.prediction.prompt_compact import has_play_by_play, has_team_statistics
from src.prediction.live_decision import (
    MatchState,
    PredictionAction,
    decide_action,
    required_confidence,
    should_lock_bet,
)
from src.utils import get_logger

if TYPE_CHECKING:
    from src.models.live_models import MatchRecordModel
    from src.prediction.models import PredictionResult
    from src.schedule.repositories import MatchRepository
    from src.schedule.repositories.bet_repo import BetRepository
    from src.schedule.repositories.prediction_repo import PredictionRepository
    from src.schedule.repositories.status_repo import StatusRepository

LOGGER = get_logger()


@dataclass(frozen=True)
class CycleOutcome:
    """Result of evaluating one match in a cycle."""

    event_id: str
    action: str
    reason: str


class LivePredictionService:
    """Evaluate started matches once per cycle, skipping settled predictions."""

    def __init__(
        self,
        match_repo: "MatchRepository",
        prediction_repo: "PredictionRepository",
        bet_repo: "BetRepository",
        prober: "Callable[[MatchRecordModel], MatchState | None]",
        dossier_runner: "Callable[[MatchRecordModel], Path | None]",
        predictor: "Callable[[Path], PredictionResult]",
        force_refresh_every: int,
        lock_confidence: int,
        lock_odds: float,
        min_odds: float,
        kelly_fraction: float,
        active_window_hours: int,
        max_bet_minute: int,
        status_repo: "StatusRepository | None" = None,
        bet_provider_hints: tuple[str, ...] | None = None,
        synthetic_odds: float | None = None,
        max_stake_fraction: float = 1.0,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            match_repo: Source of started matches.
            prediction_repo: Persistence for the last prediction/state.
            bet_repo: Persistence for locked bets and their settlement.
            prober: Cheap current-state probe for one match.
            dossier_runner: Builds a dossier and returns its markdown path.
            predictor: Produces a prediction from a dossier markdown path.
            force_refresh_every: Re-predict after this many skip cycles.
            lock_confidence: Confidence at or above which the bet is locked.
            lock_odds: Odds at or below which the bet is locked (near the floor).
            min_odds: Minimum odds allowed for a real bet.
            kelly_fraction: Fraction of full Kelly to stake.
            active_window_hours: Only consider matches kicked off within this many
                hours, so finished matches are not re-probed indefinitely.
            max_bet_minute: Latest match minute at which a bet may be locked;
                past it, bookmakers pull markets and the outcome is near-decided,
                so no bet is placed.
            status_repo: Optional store for the per-match cycle decision, used by
                the "today" dashboard page. When omitted, decisions are not
                persisted (the core cycle is unaffected).
            bet_provider_hints: Lowercased-alphanumeric bookmaker substrings a bet
                may be priced from (e.g. ``("betfair", "bet365")``). A prediction
                is only locked into a bet when odds from one of these books are
                present; otherwise no bet is placed. ``None`` allows any book.
            synthetic_odds: Placeholder decimal odds used to simulate a bet when
                no real bookmaker odds exist. When set, a confident pick (meeting
                the time-relaxed threshold) is locked as a synthetic bet at this
                price; ``None`` disables synthetic betting (pick tracked, no bet).
        """

        self._match_repo = match_repo
        self._prediction_repo = prediction_repo
        self._bet_repo = bet_repo
        self._prober = prober
        self._dossier_runner = dossier_runner
        self._predictor = predictor
        self._force_refresh_every = force_refresh_every
        self._lock_confidence = lock_confidence
        self._lock_odds = lock_odds
        self._min_odds = min_odds
        self._kelly_fraction = kelly_fraction
        self._active_window_hours = active_window_hours
        self._max_bet_minute = max_bet_minute
        self._status_repo = status_repo
        self._bet_provider_hints = bet_provider_hints
        self._synthetic_odds = synthetic_odds
        self._max_stake_fraction = max_stake_fraction

    def run_cycle(self, now: datetime) -> list[CycleOutcome]:
        """Evaluate every started match once and return per-match outcomes.

        Args:
            now: Current UTC time (used for the started-match cut-off and stamps).

        Returns:
            One outcome per started match.
        """

        outcomes: list[CycleOutcome] = []
        started = self._match_repo.get_started_matches(
            now_utc=now, active_window_hours=self._active_window_hours
        )
        processed: set[str] = set()
        for match in started:
            event_id = match.event.id
            if not event_id:
                continue
            processed.add(event_id)
            outcomes.append(self._evaluate(match=match, event_id=event_id, now=now))
        outcomes.extend(self._settle_stale_bets(processed=processed))
        self._record_statuses(outcomes=outcomes, now=now)
        return outcomes

    def _record_statuses(
        self, outcomes: list[CycleOutcome], now: datetime
    ) -> None:
        """Persist each cycle decision so the today page can display it."""

        if self._status_repo is None:
            return
        for outcome in outcomes:
            self._status_repo.upsert(
                event_id=outcome.event_id,
                action=outcome.action,
                reason=outcome.reason,
                updated_at=now,
            )

    def _settle_stale_bets(self, processed: set[str]) -> list[CycleOutcome]:
        """Settle locked bets whose match has aged out of the active window.

        A bet locks while its match is live, but the match then drops out of the
        active window (and out of ``get_started_matches``) after a few hours. If
        no cycle caught ``finished`` before then — e.g. ESPN's status lagged and
        never flipped to "post" — the bet would stay pending forever. Any
        unsettled locked bet not handled by the in-window pass above belongs to a
        match that is too old to still be running, so its current score is final:
        probe it once more and settle.

        Args:
            processed: Event ids already evaluated this cycle (in-window).

        Returns:
            One outcome per stale bet acted upon.
        """

        outcomes: list[CycleOutcome] = []
        for bet in self._bet_repo.list_all():
            if bet.settled or bet.event_id in processed:
                continue
            match = self._match_repo.get_match_record(bet.event_id)
            if match is None:
                LOGGER.warn(f"Stale bet [{bet.event_id}]: match row missing; skipping.")
                outcomes.append(CycleOutcome(bet.event_id, "skip", "no_match"))
                continue
            state = self._prober(match)
            if state is None:
                LOGGER.warn(f"Stale bet [{bet.event_id}]: no probe state; skipping.")
                outcomes.append(CycleOutcome(bet.event_id, "skip", "no_state"))
                continue
            self._settle(bet.event_id, state)
            outcomes.append(CycleOutcome(bet.event_id, "done", "bet_settled"))
        return outcomes

    def _evaluate(
        self, match: "MatchRecordModel", event_id: str, now: datetime
    ) -> CycleOutcome:
        """Probe, decide, and act for a single match."""

        state = self._prober(match)
        if state is None:
            LOGGER.warn(f"Live probe returned no state [{event_id}]; skipping.")
            return CycleOutcome(event_id, "skip", "no_state")

        # Once a bet is locked the match is left alone until it finishes, then
        # the bet is settled against the final score.
        if self._bet_repo.is_locked(event_id):
            if state.finished:
                # Only report "bet_settled" (which fires the Telegram message) on
                # the cycle that actually settles it. The finished match lingers in
                # the active window for hours; re-emitting would spam duplicates.
                settled_now = self._settle(event_id, state)
                reason = "bet_settled" if settled_now else "already_settled"
                return CycleOutcome(event_id, "done", reason)
            return CycleOutcome(event_id, "skip", "locked")

        last = self._prediction_repo.get_last(event_id)
        action, reason = decide_action(
            last=last,
            current=state,
            force_refresh_every=self._force_refresh_every,
        )

        if action is PredictionAction.DONE:
            if last is not None:
                self._persist(
                    event_id,
                    last.predicted_result,
                    last.success_probability,
                    state,
                    cycles=last.cycles_since_full,
                    status="done",
                    now=now,
                )
            return CycleOutcome(event_id, "done", reason)

        if action is PredictionAction.SKIP:
            self._persist(
                event_id,
                last.predicted_result,
                last.success_probability,  # type: ignore[union-attr]
                state,
                cycles=last.cycles_since_full + 1,
                status="live",
                now=now,
            )  # type: ignore[union-attr]
            LOGGER.info(f"Prediction skipped [{event_id}] ({reason}).")
            return CycleOutcome(event_id, "skip", reason)

        # PREDICT — but never place a late bet: past the max minute the market
        # is pulled and the outcome is near-decided, so it is worthless.
        if state.minute > self._max_bet_minute:
            LOGGER.info(
                f"Past bet window [{event_id}] (minute {state.minute} > "
                f"{self._max_bet_minute}); no bet."
            )
            return CycleOutcome(event_id, "skip", "past_bet_window")
        markdown_path = self._dossier_runner(match)
        if markdown_path is None:
            LOGGER.warn(f"Dossier build produced no file [{event_id}]; skipping.")
            return CycleOutcome(event_id, "skip", "no_dossier")
        if not self._has_coverage(markdown_path):
            LOGGER.info(f"Skipping prediction [{event_id}]: no play-by-play coverage.")
            return CycleOutcome(event_id, "skip", "no_play_by_play")
        try:
            result = self._predictor(markdown_path)
        except PredictionUnavailableError as error:
            # Model failed (e.g. out of credits): persist nothing and place no
            # bet. A fabricated placeholder would corrupt the tracked data.
            LOGGER.warn(f"Prediction unavailable [{event_id}]: {error}; skipping.")
            return CycleOutcome(event_id, "skip", "model_unavailable")
        self._persist(
            event_id,
            result.predicted_result,
            result.success_probability,
            state,
            cycles=0,
            status="live",
            now=now,
            rationale=result.rationale,
            evidence=list(result.evidence_refs),
            over_under_result=result.over_under_result,
            over_under_line=result.over_under_line,
            over_under_probability=result.over_under_probability,
        )
        LOGGER.info(
            f"Prediction refreshed [{event_id}] ({reason}) -> "
            f"{result.predicted_result} ({result.success_probability}%)."
        )
        # Relax the confidence bar as the match nears full time (the outcome is
        # more settled late); the model's evidence-based probability and the EV
        # filter still gate the actual bet.
        threshold = required_confidence(state.minute, self._lock_confidence)
        odds, bookmaker = self._read_odds(markdown_path, result.predicted_result)
        if odds is None:
            return self._maybe_synthetic_bet(event_id, result, state, now, threshold)
        if should_lock_bet(
            result.success_probability, odds, threshold, self._lock_odds
        ):
            self._lock_bet(event_id, result, odds, bookmaker, state, now)
            return CycleOutcome(event_id, "predict", "locked_bet")
        return CycleOutcome(event_id, "predict", reason)

    def _maybe_synthetic_bet(
        self,
        event_id: str,
        result: "PredictionResult",
        state: MatchState,
        now: datetime,
        threshold: int,
    ) -> CycleOutcome:
        """Lock a synthetic bet when no real odds exist but the pick is confident.

        No odds from an allowed bookmaker means a real bet could not be placed.
        When synthetic betting is enabled, a pick clearing the (time-relaxed)
        confidence threshold is still simulated at a conservative placeholder
        price so it can be evaluated; otherwise the pick is only tracked.
        """

        if self._synthetic_odds is None:
            LOGGER.info(
                f"No usable bookmaker odds for [{event_id}]; tracking without a bet."
            )
            return CycleOutcome(event_id, "predict", "no_usable_odds")
        # The synthetic price is not a market signal, so lock purely on the
        # (time-relaxed) confidence rather than the odds-floor trigger.
        if result.success_probability >= threshold:
            self._lock_bet(
                event_id, result, self._synthetic_odds, "Sintetica", state, now,
                synthetic=True,
            )
            return CycleOutcome(event_id, "predict", "locked_bet")
        LOGGER.info(
            f"No usable odds and confidence {result.success_probability}% below "
            f"threshold {threshold}% for [{event_id}]; tracking without a bet."
        )
        return CycleOutcome(event_id, "predict", "no_usable_odds")

    @staticmethod
    def _has_coverage(markdown_path: Path) -> bool:
        """Return whether the dossier is rich enough to predict (fail-open).

        A match is worth predicting when ESPN gives it either a play-by-play
        event timeline OR a live boxscore (team statistics) — with the latter the
        model still has real dominance signals plus the score/time baseline. Only
        matches with neither (competitions ESPN barely covers) are skipped. If the
        file cannot be read we do not skip (fail open).
        """

        try:
            text = markdown_path.read_text(encoding="utf-8")
        except OSError:
            return True
        return has_play_by_play(text) or has_team_statistics(text)

    def _read_odds(
        self, markdown_path: Path, predicted_result: str
    ) -> tuple[float | None, str | None]:
        """Parse the predicted outcome's decimal odds and bookmaker from the file.

        Only odds from an allowed bookmaker (``self._bet_provider_hints``) are
        returned, so a bet is priced solely from books it could be placed on.
        """

        try:
            text = markdown_path.read_text(encoding="utf-8")
        except OSError:
            return None, None
        pick = select_predicted_odds(text, predicted_result, self._bet_provider_hints)
        if pick is None:
            return None, None
        return pick

    def _lock_bet(
        self,
        event_id: str,
        result: "PredictionResult",
        odds: float | None,
        bookmaker: str | None,
        state: MatchState,
        now: datetime,
        synthetic: bool = False,
    ) -> None:
        """Lock the prediction as the bet and decide whether/how much to stake."""

        self._bet_repo.lock(
            event_id=event_id,
            predicted_result=result.predicted_result,
            model_prob=result.success_probability,
            odds=odds,
            minute=state.minute,
            locked_at=now,
            rationale=result.rationale,
            evidence=list(result.evidence_refs),
            bookmaker=bookmaker,
            synthetic=synthetic,
        )
        if synthetic:
            LOGGER.info(
                f"Synthetic bet locked [{event_id}] -> {result.predicted_result} @ "
                f"{odds} ({result.success_probability}%): no real odds, flat-stake "
                "simulation (reported separately)."
            )
            return
        book_label = f" [{bookmaker}]" if bookmaker else ""
        if odds is not None and is_bettable(
            odds, result.success_probability, self._min_odds
        ):
            stake = capped_kelly_stake(
                result.success_probability, odds, self._kelly_fraction,
                self._max_stake_fraction,
            )
            LOGGER.info(
                f"Bet locked [{event_id}] -> {result.predicted_result} @ {odds}"
                f"{book_label} ({result.success_probability}%); "
                f"stake {stake * 100:.1f}% of bankroll."
            )
        else:
            LOGGER.info(
                f"Bet locked [{event_id}] -> {result.predicted_result} @ "
                f"{odds if odds is not None else 'n/a'}{book_label}: NO bet "
                f"(odds < {self._min_odds} or negative value)."
            )

    def _settle(self, event_id: str, state: MatchState) -> bool:
        """Settle a locked bet against the final score, once.

        Returns:
            True when this call settled the bet; False when there was no bet or
            it was already settled (so callers do not re-notify).
        """

        bet = self._bet_repo.get(event_id)
        if bet is None or bet.settled:
            return False
        outcome = settle_bet(bet.predicted_result, state.home_score, state.away_score)
        self._bet_repo.settle(
            event_id=event_id,
            final_home=state.home_score,
            final_away=state.away_score,
            outcome=outcome,
        )
        LOGGER.info(
            f"Bet settled [{event_id}] -> {outcome} "
            f"(final {state.home_score}-{state.away_score})."
        )
        return True

    def _persist(
        self,
        event_id: str,
        predicted_result: str,
        success_probability: int,
        state: MatchState,
        cycles: int,
        status: str,
        now: datetime,
        rationale: str | None = None,
        evidence: list[str] | None = None,
        over_under_result: str | None = None,
        over_under_line: float | None = None,
        over_under_probability: int | None = None,
    ) -> None:
        """Write the prediction/state row for one match.

        ``rationale``/``evidence`` and the ``over_under_*`` fields are supplied
        only on a fresh prediction; skip and done cycles omit them so the stored
        reasoning and Over/Under pick are preserved.
        """

        self._prediction_repo.upsert(
            event_id=event_id,
            predicted_result=predicted_result,
            success_probability=success_probability,
            home_score=state.home_score,
            away_score=state.away_score,
            red_cards=state.red_cards,
            minute=state.minute,
            cycles_since_full=cycles,
            status=status,
            updated_at=now,
            rationale=rationale,
            evidence=evidence,
            over_under_result=over_under_result,
            over_under_line=over_under_line,
            over_under_probability=over_under_probability,
        )
