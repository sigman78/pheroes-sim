from __future__ import annotations

from ..strategy_core import Strategy, create_weighted_heuristic_strategy

STRATEGY_NAME = "weighted_a"
DEFAULT_SEED = 11
WEIGHTS = {
    "base_bias": 0.0,
    "is_wait": -2.0,
    "is_defend": -0.5,
    "is_move": 0.2,
    "is_melee_attack": 3.0,
    "is_ranged_attack": 2.5,
    "adjacent_enemy_pressure": -1.0,
    "target_value": 0.1,
    "estimated_damage_ratio": 8.0,
    "estimated_kills": 5.0,
    "retaliation_risk": -4.0,
    "distance_closed": 0.8,
    "move_cost": -0.1,
}


def build_strategy(*, seed: int | None = None) -> Strategy:
    return create_weighted_heuristic_strategy(
        weights=WEIGHTS,
        seed=DEFAULT_SEED if seed is None else seed,
        strategy_name=STRATEGY_NAME,
    )
