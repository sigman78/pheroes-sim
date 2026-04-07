from __future__ import annotations

from ..strategy_core import Strategy, create_weighted_heuristic_strategy

STRATEGY_NAME = "weighted_b"
DEFAULT_SEED = 29
WEIGHTS = {
    "base_bias": 0.0,
    "is_wait": -1.0,
    "is_defend": 0.5,
    "is_move": 0.4,
    "is_melee_attack": 2.8,
    "is_ranged_attack": 2.2,
    "adjacent_enemy_pressure": -0.4,
    "target_value": 0.2,
    "estimated_damage_ratio": 6.5,
    "estimated_kills": 4.0,
    "retaliation_risk": -3.0,
    "distance_closed": 1.0,
    "move_cost": -0.05,
}


def build_strategy(*, seed: int | None = None) -> Strategy:
    return create_weighted_heuristic_strategy(
        weights=WEIGHTS,
        seed=DEFAULT_SEED if seed is None else seed,
        strategy_name=STRATEGY_NAME,
    )
