from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hexgrid import HexCoord
from .models import Ability, ArmyStack, Battlefield, BattleState, CreatureTemplate
from .rewards import RewardTracker, RewardWeights
from .strategies import load_strategy as load_strategy_module
from .strategy_core import Strategy

NUMERIC_CREATURE_FIELDS = {
    "attack",
    "defense",
    "min_damage",
    "max_damage",
    "health",
    "speed",
    "initiative",
    "shots",
}
REQUIRED_CREATURE_FIELDS = (
    "attack",
    "defense",
    "min_damage",
    "max_damage",
    "health",
    "speed",
    "initiative",
)
ALLOWED_CREATURE_FIELDS = NUMERIC_CREATURE_FIELDS | {"extends", "abilities"}


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scenario(path: str | Path) -> BattleState:
    scenario_path = Path(path)
    return load_scenario_data(load_json(scenario_path), base_path=scenario_path.parent)


def load_scenario_data(data: dict[str, Any], *, base_path: str | Path | None = None) -> BattleState:
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported scenario schema_version")

    battlefield_data = data["battlefield"]
    walls = frozenset(
        HexCoord(int(c[0]), int(c[1]))
        for c in battlefield_data.get("walls", [])
    )
    rocks = frozenset(
        HexCoord(int(c[0]), int(c[1]))
        for c in battlefield_data.get("rocks", [])
    )
    battlefield = Battlefield(
        width=int(battlefield_data["width"]),
        height=int(battlefield_data["height"]),
        round_limit=int(battlefield_data.get("round_limit", 50)),
        walls=walls,
        rocks=rocks,
    )

    creature_library = _load_creature_library(data, base_path=Path(base_path) if base_path is not None else None)

    stacks: dict[str, ArmyStack] = {}
    for army in data["armies"]:
        owner = int(army["owner"])
        for item in army["stacks"]:
            creature_name = item["creature"]
            if creature_name not in creature_library:
                raise ValueError(f"Unknown creature referenced by stack '{item['stack_id']}': {creature_name}")
            stack = ArmyStack.from_template(
                stack_id=item["stack_id"],
                owner=owner,
                template=creature_library[creature_name],
                count=int(item["count"]),
                position=HexCoord(int(item["position"]["q"]), int(item["position"]["r"])),
            )
            stacks[stack.stack_id] = stack

    return BattleState(battlefield=battlefield, stacks=stacks)


def list_scenario_files(path: str | Path) -> list[Path]:
    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Scenario set directory not found: {root}")
    files = sorted(item for item in root.iterdir() if item.is_file() and item.suffix.lower() == ".json")
    if not files:
        raise ValueError(f"No scenario JSON files found in: {root}")
    return files


def _load_creature_library(data: dict[str, Any], *, base_path: Path | None) -> dict[str, CreatureTemplate]:
    raw_definitions: dict[str, Any] = {}
    catalog_path = data.get("creature_catalog")
    if catalog_path is not None:
        if base_path is None:
            raise ValueError("creature_catalog requires a base path for relative resolution")
        catalog_file = (base_path / catalog_path).resolve()
        if not catalog_file.exists():
            raise ValueError(f"Creature catalog not found: {catalog_file}")
        catalog_data = load_json(catalog_file)
        raw_definitions.update(catalog_data)

    raw_definitions.update(data.get("creatures", {}))
    if not raw_definitions:
        raise ValueError("Scenario must define creatures inline or via creature_catalog")

    resolved: dict[str, dict[str, Any]] = {}
    visiting: list[str] = []

    def resolve_definition(name: str) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            cycle = " -> ".join(visiting + [name])
            raise ValueError(f"Creature inheritance cycle detected: {cycle}")
        if name not in raw_definitions:
            raise ValueError(f"Creature definition not found: {name}")

        entry = raw_definitions[name]
        if not isinstance(entry, dict):
            raise ValueError(f"Creature definition for '{name}' must be an object")
        unknown_fields = set(entry) - ALLOWED_CREATURE_FIELDS
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Creature '{name}' has unsupported fields: {names}")

        visiting.append(name)
        if "extends" in entry:
            base_name = entry["extends"]
            if not isinstance(base_name, str) or not base_name:
                raise ValueError(f"Creature '{name}' must use a non-empty string in extends")
            base_definition = resolve_definition(base_name).copy()
            merged = _apply_creature_overrides(name, base_definition, entry)
        else:
            merged = _normalize_creature_definition(name, entry)
        visiting.pop()
        resolved[name] = merged
        return merged

    return {
        name: _build_creature_template(name, resolve_definition(name))
        for name in sorted(raw_definitions)
    }


def _apply_creature_overrides(name: str, base_definition: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = base_definition.copy()
    for field, raw_value in entry.items():
        if field == "extends":
            continue
        if field in NUMERIC_CREATURE_FIELDS:
            merged[field] = _resolve_numeric_override(name, field, int(base_definition.get(field, 0)), raw_value)
            continue
        if field == "abilities":
            if not isinstance(raw_value, list):
                raise ValueError(f"Creature '{name}' field 'abilities' must be a list")
            merged[field] = list(raw_value)
    return _normalize_creature_definition(name, merged)


def _normalize_creature_definition(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    missing_fields = [field for field in REQUIRED_CREATURE_FIELDS if field not in entry]
    if missing_fields:
        raise ValueError(f"Creature '{name}' is missing required fields: {', '.join(missing_fields)}")

    normalized: dict[str, Any] = {}
    for field in REQUIRED_CREATURE_FIELDS:
        normalized[field] = _coerce_numeric_field(name, field, entry[field])
    normalized["shots"] = _coerce_numeric_field(name, "shots", entry.get("shots", 0))
    abilities = entry.get("abilities", [])
    if not isinstance(abilities, list):
        raise ValueError(f"Creature '{name}' field 'abilities' must be a list")
    normalized["abilities"] = list(abilities)
    return normalized


def _coerce_numeric_field(name: str, field: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Creature '{name}' field '{field}' must resolve to an integer")
    return int(value)


def _resolve_numeric_override(name: str, field: str, base_value: int, raw_value: Any) -> int:
    if isinstance(raw_value, bool):
        raise ValueError(f"Creature '{name}' field '{field}' must resolve to an integer")
    if isinstance(raw_value, int):
        return raw_value
    if not isinstance(raw_value, str):
        raise ValueError(f"Creature '{name}' field '{field}' has invalid override value: {raw_value!r}")

    if raw_value.endswith("%"):
        amount = raw_value[:-1]
        if amount.lstrip("+-").isdigit():
            return int(round(base_value * (int(amount) / 100.0)))
        raise ValueError(f"Creature '{name}' field '{field}' has invalid percentage override: {raw_value}")

    if raw_value.startswith(("+", "-")) and raw_value[1:].isdigit():
        return base_value + int(raw_value)

    raise ValueError(f"Creature '{name}' field '{field}' has invalid override syntax: {raw_value}")


def _build_creature_template(name: str, creature: dict[str, Any]) -> CreatureTemplate:
    return CreatureTemplate(
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


def load_strategy(strategy_id: str, *, seed_override: int | None = None) -> Strategy:
    return load_strategy_module(strategy_id, seed_override=seed_override)


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
