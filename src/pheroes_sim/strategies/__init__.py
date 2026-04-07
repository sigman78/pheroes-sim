from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from ..strategy_core import Strategy


def list_available_strategy_ids() -> list[str]:
    package_path = Path(__file__).resolve().parent
    return sorted(
        module.name
        for module in pkgutil.iter_modules([str(package_path)])
        if not module.name.startswith("_")
    )


def load_strategy(strategy_id: str, *, seed_override: int | None = None) -> Strategy:
    available = list_available_strategy_ids()
    if strategy_id not in available:
        raise ValueError(f"Unknown strategy '{strategy_id}'. Available strategies: {', '.join(available)}")

    module = importlib.import_module(f"{__name__}.{strategy_id}")
    build_strategy = getattr(module, "build_strategy", None)
    if build_strategy is None:
        raise ValueError(f"Strategy module '{strategy_id}' is missing build_strategy(seed=None)")
    return build_strategy(seed=seed_override)
