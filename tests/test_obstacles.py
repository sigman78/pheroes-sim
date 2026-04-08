"""Integration tests for the battlefield obstacles feature (walls and rocks)."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.engine import BattleSimulator
from pheroes_sim.hexgrid import HexCoord
from pheroes_sim.io import load_scenario
from pheroes_sim.models import (
    Ability, ActionType, ArmyStack, Battlefield, BattleAction, BattleState, CreatureTemplate,
)
from pheroes_sim.rendering import render_ascii_board
from pheroes_sim.strategy_core import StrategyDecision


class _StaticStrategy:
    def choose_action(self, state: BattleState, actor_id: str, legal_actions: list[BattleAction]) -> StrategyDecision:
        return StrategyDecision(action=legal_actions[0], strategy_name="static", candidate_scores=[])


def _make_stack(stack_id: str, owner: int, template: CreatureTemplate, count: int, pos: tuple[int, int]) -> ArmyStack:
    return ArmyStack.from_template(stack_id, owner, template, count, HexCoord(*pos))


def _ground_template() -> CreatureTemplate:
    return CreatureTemplate(name="ground", attack=5, defense=4, min_damage=2, max_damage=4, health=10, speed=5, initiative=5)


def _flying_template() -> CreatureTemplate:
    return CreatureTemplate(
        name="flyer", attack=5, defense=4, min_damage=2, max_damage=4, health=10, speed=5, initiative=5,
        abilities=frozenset({Ability.FLYING}),
    )


def _ranged_template() -> CreatureTemplate:
    return CreatureTemplate(
        name="ranged", attack=6, defense=3, min_damage=2, max_damage=4, health=8, speed=4, initiative=7,
        shots=5, abilities=frozenset({Ability.LIMITED_SHOTS}),
    )


class WallMovementTests(unittest.TestCase):
    def test_wall_blocks_ground_movement(self) -> None:
        # Wall column at q=3; attacker at (1,2) with speed 5 cannot reach (5,2)
        walls = frozenset({HexCoord(3, 0), HexCoord(3, 1), HexCoord(3, 2), HexCoord(3, 3), HexCoord(3, 4)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=6, walls=walls),
            stacks={
                "a": _make_stack("a", 1, _ground_template(), 5, (1, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        move_dests = {a.target_pos for a in actions if a.action_type == ActionType.MOVE}
        self.assertNotIn(HexCoord(5, 2), move_dests)
        self.assertNotIn(HexCoord(4, 2), move_dests)

    def test_wall_blocks_flying(self) -> None:
        # Walls block flying units too
        walls = frozenset({HexCoord(3, 0), HexCoord(3, 1), HexCoord(3, 2), HexCoord(3, 3), HexCoord(3, 4)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=6, walls=walls),
            stacks={
                "a": _make_stack("a", 1, _flying_template(), 5, (1, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        move_dests = {a.target_pos for a in actions if a.action_type == ActionType.MOVE}
        self.assertNotIn(HexCoord(3, 2), move_dests)
        self.assertNotIn(HexCoord(5, 2), move_dests)

    def test_wall_open_path_is_reachable(self) -> None:
        # Walls block centre but top row is open; unit can reach the other side via top
        walls = frozenset({HexCoord(3, 1), HexCoord(3, 2), HexCoord(3, 3)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=5, walls=walls),
            stacks={
                "a": _make_stack("a", 1, _ground_template(), 5, (1, 0)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 0)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        move_dests = {a.target_pos for a in actions if a.action_type == ActionType.MOVE}
        # Top row (r=0) path around wall is open
        self.assertIn(HexCoord(4, 0), move_dests)


class RockMovementTests(unittest.TestCase):
    def test_rock_blocks_ground_not_flying(self) -> None:
        rocks = frozenset({HexCoord(3, 2)})
        bf = Battlefield(width=8, height=5, rocks=rocks)
        ground_state = BattleState(
            battlefield=bf,
            stacks={
                "a": _make_stack("a", 1, _ground_template(), 5, (2, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        flying_state = BattleState(
            battlefield=bf,
            stacks={
                "a": _make_stack("a", 1, _flying_template(), 5, (2, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        sim_g = BattleSimulator(ground_state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        sim_f = BattleSimulator(flying_state, {1: _StaticStrategy(), 2: _StaticStrategy()})

        ground_dests = {a.target_pos for a in sim_g.legal_actions("a") if a.action_type == ActionType.MOVE}
        flying_dests = {a.target_pos for a in sim_f.legal_actions("a") if a.action_type == ActionType.MOVE}

        self.assertNotIn(HexCoord(3, 2), ground_dests)
        self.assertIn(HexCoord(3, 2), flying_dests)


class RangedLoSTests(unittest.TestCase):
    def test_ranged_blocked_by_wall(self) -> None:
        # Vertical wall between shooter (q=1) and target (q=6) at q=3
        walls = frozenset({HexCoord(3, 0), HexCoord(3, 1), HexCoord(3, 2), HexCoord(3, 3), HexCoord(3, 4)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=6, walls=walls),
            stacks={
                "a": _make_stack("a", 1, _ranged_template(), 5, (1, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        ranged = [a for a in actions if a.action_type == ActionType.ATTACK_RANGED]
        self.assertEqual(len(ranged), 0)

    def test_ranged_not_blocked_by_rock(self) -> None:
        # Rock between shooter and target — ranged should still be legal
        rocks = frozenset({HexCoord(3, 2)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=6, rocks=rocks),
            stacks={
                "a": _make_stack("a", 1, _ranged_template(), 5, (1, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (5, 2)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        ranged = [a for a in actions if a.action_type == ActionType.ATTACK_RANGED]
        self.assertTrue(len(ranged) > 0)

    def test_ranged_no_wall_has_shot(self) -> None:
        # Baseline: no obstacles, ranged attack is available
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "a": _make_stack("a", 1, _ranged_template(), 5, (1, 2)),
                "b": _make_stack("b", 2, _ground_template(), 5, (6, 2)),
            },
        )
        sim = BattleSimulator(state, {1: _StaticStrategy(), 2: _StaticStrategy()})
        actions = sim.legal_actions("a")
        ranged = [a for a in actions if a.action_type == ActionType.ATTACK_RANGED]
        self.assertTrue(len(ranged) > 0)


class ObstacleScenarioTests(unittest.TestCase):
    SCENARIOS_DIR = ROOT / "examples" / "scenario_sets" / "core"

    def test_scenario_11_loads_with_walls(self) -> None:
        state = load_scenario(str(self.SCENARIOS_DIR / "scenario_11_wall_corridor.json"))
        self.assertTrue(len(state.battlefield.walls) > 0)
        self.assertEqual(len(state.battlefield.rocks), 0)

    def test_scenario_12_loads_with_rocks(self) -> None:
        state = load_scenario(str(self.SCENARIOS_DIR / "scenario_12_rocks_shooters.json"))
        self.assertEqual(len(state.battlefield.walls), 0)
        self.assertTrue(len(state.battlefield.rocks) > 0)

    def test_scenario_13_loads_with_walls(self) -> None:
        state = load_scenario(str(self.SCENARIOS_DIR / "scenario_13_wall_los.json"))
        self.assertTrue(len(state.battlefield.walls) > 0)


class RenderingTests(unittest.TestCase):
    def test_render_shows_wall_and_rock(self) -> None:
        walls = frozenset({HexCoord(2, 1)})
        rocks = frozenset({HexCoord(4, 1)})
        state = BattleState(
            battlefield=Battlefield(width=8, height=4, walls=walls, rocks=rocks),
            stacks={
                "a": _make_stack("a", 1, _ground_template(), 5, (0, 0)),
                "b": _make_stack("b", 2, _ground_template(), 5, (7, 3)),
            },
        )
        frame = render_ascii_board(state, "test")
        self.assertIn("WW", frame.board)
        self.assertIn("##", frame.board)

    def test_render_no_obstacles_no_symbols(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=6, height=4),
            stacks={
                "a": _make_stack("a", 1, _ground_template(), 5, (0, 0)),
                "b": _make_stack("b", 2, _ground_template(), 5, (5, 3)),
            },
        )
        frame = render_ascii_board(state, "test")
        self.assertNotIn("WW", frame.board)
        self.assertNotIn("##", frame.board)


if __name__ == "__main__":
    unittest.main()
