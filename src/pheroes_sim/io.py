from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hexgrid import HexCoord
from .models import Ability, ArmyStack, Battlefield, BattleState, CreatureTemplate
from .rewards import RewardTracker, RewardWeights
from .strategies import RandomStrategy, Strategy, WeightedHeuristicStrategy


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scenario(path: str | Path) -> BattleState:
    data = load_json(path)
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported scenario schema_version")

    battlefield_data = data["battlefield"]
    battlefield = Battlefield(
        width=int(battlefield_data["width"]),
        height=int(battlefield_data["height"]),
        round_limit=int(battlefield_data.get("round_limit", 50)),
    )

    creature_library = {
        name: CreatureTemplate(
            name=name,
            attack=int(creature["attack"]),
            defense=int(creature["defense"]),
            min_damage=int(creature["min_damage"]),
            max_damage=int(creature["max_damage"]),
            health=int(creature["health"]),
            speed=int(creature["speed"]),
            initiative=int(creature["initiative"]),
            shots=int(creature.get("shots", 0)),
            abilities=frozenset(Ability(value) for value in creature.get("abilities", [])),
        )
        for name, creature in data["creatures"].items()
    }

    stacks: dict[str, ArmyStack] = {}
    for army in data["armies"]:
        owner = int(army["owner"])
        for item in army["stacks"]:
            stack = ArmyStack.from_template(
                stack_id=item["stack_id"],
                owner=owner,
                template=creature_library[item["creature"]],
                count=int(item["count"]),
                position=HexCoord(int(item["position"]["q"]), int(item["position"]["r"])),
            )
            stacks[stack.stack_id] = stack

    return BattleState(battlefield=battlefield, stacks=stacks)


def load_strategy(path: str | Path, *, seed_override: int | None = None) -> Strategy:
    data = load_json(path)
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported AI schema_version")

    strategy_type = data["strategy"]
    seed = int(data.get("seed", 0) if seed_override is None else seed_override)
    if strategy_type == "weighted_heuristic":
        return WeightedHeuristicStrategy(weights={k: float(v) for k, v in data.get("weights", {}).items()}, seed=seed)
    if strategy_type == "random":
        return RandomStrategy(seed=seed)
    raise ValueError(f"Unsupported strategy type: {strategy_type}")


def load_reward_tracker(path: str | Path | None = None) -> RewardTracker:
    if path is None:
        return RewardTracker()
    data = load_json(path)
    return RewardTracker(weights=RewardWeights(**{k: float(v) for k, v in data.items()}))


class JsonlLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True))
            handle.write("\n")
