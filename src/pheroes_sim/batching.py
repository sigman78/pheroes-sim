from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class PlayerBatchStats:
    wins: int
    losses: int
    draws: int
    win_rate: float
    win_rate_ci_95: ConfidenceInterval
    mean_reward: float


@dataclass(frozen=True, slots=True)
class SideSplitStats:
    matches: int
    wins: int
    losses: int
    draws: int
    win_rate: float


def normal_approximation_ci(successes: int, trials: int, z: float = 1.96) -> ConfidenceInterval:
    if trials <= 0:
        return ConfidenceInterval(lower=0.0, upper=0.0)
    p = successes / trials
    margin = z * sqrt((p * (1.0 - p)) / trials)
    return ConfidenceInterval(lower=max(0.0, p - margin), upper=min(1.0, p + margin))


# ---------------------------------------------------------------------------
# ELO rating system
# ---------------------------------------------------------------------------


class EloRatings:
    def __init__(self, strategy_ids: list[str], initial: float = 1000.0) -> None:
        self.ratings: dict[str, float] = {sid: initial for sid in strategy_ids}


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(
    ratings: EloRatings,
    winner_id: str,
    loser_id: str,
    k: float = 32.0,
    draw: bool = False,
) -> None:
    score_w = 0.5 if draw else 1.0
    score_l = 0.5 if draw else 0.0
    exp_w = expected_score(ratings.ratings[winner_id], ratings.ratings[loser_id])
    exp_l = expected_score(ratings.ratings[loser_id], ratings.ratings[winner_id])
    ratings.ratings[winner_id] += k * (score_w - exp_w)
    ratings.ratings[loser_id] += k * (score_l - exp_l)


# ---------------------------------------------------------------------------
# Matchup and tournament result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchupStats:
    challenger: str
    opponent: str
    num_sims: int
    challenger_wins: int
    challenger_losses: int
    draws: int
    challenger_win_rate: float
    challenger_mean_reward: float
    opponent_mean_reward: float


@dataclass(frozen=True, slots=True)
class StrategyStandings:
    strategy_id: str
    total_wins: int
    total_losses: int
    total_draws: int
    win_rate: float
    mean_reward: float
    elo: float
