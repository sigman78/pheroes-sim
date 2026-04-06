from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RewardWeights:
    damage_dealt: float = 0.1
    damage_taken: float = -0.1
    units_killed: float = 1.5
    units_lost: float = -1.5
    action_selected: float = 0.0
    win: float = 100.0
    loss: float = -100.0
    draw: float = 0.0


@dataclass(slots=True)
class RewardTracker:
    weights: RewardWeights = field(default_factory=RewardWeights)
    totals: dict[int, float] = field(default_factory=lambda: {1: 0.0, 2: 0.0})

    def empty_delta(self) -> dict[int, dict[str, float]]:
        return {1: {}, 2: {}}

    def register_metric(self, owner: int, metric: str, value: float, delta: dict[int, dict[str, float]]) -> None:
        if value == 0:
            return
        weighted_value = getattr(self.weights, metric) * value
        delta[owner][metric] = delta[owner].get(metric, 0.0) + weighted_value
        self.totals[owner] += weighted_value

    def register_terminal(self, winner: int | None, delta: dict[int, dict[str, float]]) -> None:
        if winner is None:
            for owner in (1, 2):
                self.register_metric(owner, "draw", 1.0, delta)
            return
        loser = 1 if winner == 2 else 2
        self.register_metric(winner, "win", 1.0, delta)
        self.register_metric(loser, "loss", 1.0, delta)
