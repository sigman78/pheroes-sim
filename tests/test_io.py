from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.io import load_scenario, load_scenario_data


class ScenarioLoaderTests(unittest.TestCase):
    def test_inline_only_scenario_still_loads(self) -> None:
        state = load_scenario_data(
            {
                "schema_version": 1,
                "battlefield": {"width": 4, "height": 4},
                "creatures": {
                    "archer": {
                        "attack": 6,
                        "defense": 3,
                        "min_damage": 2,
                        "max_damage": 4,
                        "health": 8,
                        "speed": 4,
                        "initiative": 7,
                        "shots": 8,
                        "abilities": ["limited_shots"],
                    }
                },
                "armies": [
                    {
                        "owner": 1,
                        "stacks": [{"stack_id": "a1", "creature": "archer", "count": 10, "position": {"q": 0, "r": 0}}],
                    },
                    {
                        "owner": 2,
                        "stacks": [{"stack_id": "a2", "creature": "archer", "count": 10, "position": {"q": 3, "r": 3}}],
                    },
                ],
            }
        )
        self.assertEqual(state.stacks["a1"].template.name, "archer")
        self.assertEqual(state.stacks["a1"].shots_remaining, 8)

    def test_catalog_and_local_variants_load(self) -> None:
        root = ROOT / ".tmp-tests" / "io-loader"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        catalog_path = root / "creatures.json"
        scenario_path = root / "scenario.json"
        self._write_json(
            catalog_path,
            {
                "archer": {
                    "attack": 6,
                    "defense": 3,
                    "min_damage": 2,
                    "max_damage": 4,
                    "health": 8,
                    "speed": 4,
                    "initiative": 7,
                    "shots": 8,
                    "abilities": ["limited_shots"],
                },
                "harpy": {
                    "attack": 6,
                    "defense": 5,
                    "min_damage": 2,
                    "max_damage": 4,
                    "health": 14,
                    "speed": 7,
                    "initiative": 8,
                    "abilities": ["flying", "no_retaliation"],
                },
                "griffin": {
                    "attack": 8,
                    "defense": 8,
                    "min_damage": 3,
                    "max_damage": 6,
                    "health": 25,
                    "speed": 6,
                    "initiative": 9,
                    "abilities": ["flying", "double_strike"],
                },
            },
        )
        self._write_json(
            scenario_path,
            {
                "schema_version": 1,
                "battlefield": {"width": 4, "height": 4},
                "creature_catalog": "creatures.json",
                "creatures": {
                    "archers_low_ammo": {"extends": "archer", "shots": 4},
                    "heavy_harpies": {"extends": "harpy", "defense": "+2", "health": "150%"},
                    "half_griffin": {"extends": "griffin", "health": "50%"},
                },
                "armies": [
                    {
                        "owner": 1,
                        "stacks": [
                            {"stack_id": "a1", "creature": "archers_low_ammo", "count": 10, "position": {"q": 0, "r": 0}}
                        ],
                    },
                    {
                        "owner": 2,
                        "stacks": [
                            {"stack_id": "h1", "creature": "heavy_harpies", "count": 7, "position": {"q": 3, "r": 3}},
                            {"stack_id": "g1", "creature": "half_griffin", "count": 2, "position": {"q": 3, "r": 2}},
                        ],
                    },
                ],
            },
        )

        state = load_scenario(scenario_path)

        self.assertEqual(state.stacks["a1"].template.shots, 4)
        self.assertEqual(state.stacks["h1"].template.defense, 7)
        self.assertEqual(state.stacks["h1"].template.health, 21)
        self.assertEqual(state.stacks["g1"].template.health, 12)

    def test_variant_can_extend_variant(self) -> None:
        state = load_scenario_data(
            {
                "schema_version": 1,
                "battlefield": {"width": 4, "height": 4},
                "creatures": {
                    "archer": {
                        "attack": 6,
                        "defense": 3,
                        "min_damage": 2,
                        "max_damage": 4,
                        "health": 8,
                        "speed": 4,
                        "initiative": 7,
                        "shots": 8,
                    },
                    "archers_low_ammo": {"extends": "archer", "shots": 4},
                    "archers_slow": {"extends": "archers_low_ammo", "speed": "-1"},
                },
                "armies": [
                    {
                        "owner": 1,
                        "stacks": [{"stack_id": "a1", "creature": "archers_slow", "count": 10, "position": {"q": 0, "r": 0}}],
                    },
                    {
                        "owner": 2,
                        "stacks": [{"stack_id": "a2", "creature": "archer", "count": 10, "position": {"q": 3, "r": 3}}],
                    },
                ],
            }
        )
        self.assertEqual(state.stacks["a1"].template.shots, 4)
        self.assertEqual(state.stacks["a1"].template.speed, 3)

    def test_missing_creature_reference_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown creature referenced"):
            load_scenario_data(
                {
                    "schema_version": 1,
                    "battlefield": {"width": 4, "height": 4},
                    "creatures": {
                        "archer": {
                            "attack": 6,
                            "defense": 3,
                            "min_damage": 2,
                            "max_damage": 4,
                            "health": 8,
                            "speed": 4,
                            "initiative": 7,
                        }
                    },
                    "armies": [
                        {
                            "owner": 1,
                            "stacks": [{"stack_id": "a1", "creature": "missing", "count": 10, "position": {"q": 0, "r": 0}}],
                        },
                        {
                            "owner": 2,
                            "stacks": [{"stack_id": "a2", "creature": "archer", "count": 10, "position": {"q": 3, "r": 3}}],
                        },
                    ],
                }
            )

    def test_invalid_modifier_syntax_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid override syntax"):
            load_scenario_data(
                {
                    "schema_version": 1,
                    "battlefield": {"width": 4, "height": 4},
                    "creatures": {
                        "archer": {
                            "attack": 6,
                            "defense": 3,
                            "min_damage": 2,
                            "max_damage": 4,
                            "health": 8,
                            "speed": 4,
                            "initiative": 7,
                        },
                        "bad_archer": {"extends": "archer", "health": "*2"},
                    },
                    "armies": [
                        {
                            "owner": 1,
                            "stacks": [{"stack_id": "a1", "creature": "bad_archer", "count": 10, "position": {"q": 0, "r": 0}}],
                        },
                        {
                            "owner": 2,
                            "stacks": [{"stack_id": "a2", "creature": "archer", "count": 10, "position": {"q": 3, "r": 3}}],
                        },
                    ],
                }
            )

    def test_missing_extends_base_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Creature definition not found: missing_archer"):
            load_scenario_data(
                {
                    "schema_version": 1,
                    "battlefield": {"width": 4, "height": 4},
                    "creatures": {
                        "bad_archer": {
                            "extends": "missing_archer",
                            "attack": 6,
                            "defense": 3,
                            "min_damage": 2,
                            "max_damage": 4,
                            "health": 8,
                            "speed": 4,
                            "initiative": 7,
                        }
                    },
                    "armies": [
                        {
                            "owner": 1,
                            "stacks": [{"stack_id": "a1", "creature": "bad_archer", "count": 10, "position": {"q": 0, "r": 0}}],
                        },
                        {
                            "owner": 2,
                            "stacks": [{"stack_id": "a2", "creature": "bad_archer", "count": 10, "position": {"q": 3, "r": 3}}],
                        },
                    ],
                }
            )

    def test_inheritance_cycle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Creature inheritance cycle detected"):
            load_scenario_data(
                {
                    "schema_version": 1,
                    "battlefield": {"width": 4, "height": 4},
                    "creatures": {
                        "a": {"extends": "b", "attack": 6, "defense": 3, "min_damage": 2, "max_damage": 4, "health": 8, "speed": 4, "initiative": 7},
                        "b": {"extends": "a", "attack": 6, "defense": 3, "min_damage": 2, "max_damage": 4, "health": 8, "speed": 4, "initiative": 7},
                    },
                    "armies": [
                        {"owner": 1, "stacks": [{"stack_id": "a1", "creature": "a", "count": 10, "position": {"q": 0, "r": 0}}]},
                        {"owner": 2, "stacks": [{"stack_id": "b1", "creature": "b", "count": 10, "position": {"q": 3, "r": 3}}]},
                    ],
                }
            )

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
