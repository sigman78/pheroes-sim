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
