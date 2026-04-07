from __future__ import annotations

from ..strategy_core import Strategy, create_random_strategy

STRATEGY_NAME = "random"
DEFAULT_SEED = 0


def build_strategy(*, seed: int | None = None) -> Strategy:
    return create_random_strategy(
        seed=DEFAULT_SEED if seed is None else seed,
        strategy_name=STRATEGY_NAME,
    )
