from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sim_matter.engine import BattleSimulator
from sim_matter.hexgrid import HexCoord
from sim_matter.models import Ability, ActionType, ArmyStack, Battlefield, BattleAction, BattleState, CreatureTemplate
from sim_matter.strategies import StrategyDecision, WeightedHeuristicStrategy


class StaticStrategy:
    def __init__(self, action_type: ActionType) -> None:
        self.action_type = action_type

    def choose_action(self, state: BattleState, actor_id: str, legal_actions: list[BattleAction]) -> StrategyDecision:
        chosen = next(action for action in legal_actions if action.action_type == self.action_type)
        return StrategyDecision(action=chosen, strategy_name="static", candidate_scores=[])


def make_stack(
    stack_id: str,
    owner: int,
    template: CreatureTemplate,
    count: int,
    position: tuple[int, int],
) -> ArmyStack:
    return ArmyStack.from_template(stack_id, owner, template, count, HexCoord(*position))


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.melee = CreatureTemplate(
            name="melee",
            attack=5,
            defense=4,
            min_damage=2,
            max_damage=4,
            health=10,
            speed=4,
            initiative=5,
        )
        self.ranged = CreatureTemplate(
            name="ranged",
            attack=6,
            defense=3,
            min_damage=2,
            max_damage=4,
            health=8,
            speed=4,
            initiative=7,
            shots=5,
            abilities=frozenset({Ability.LIMITED_SHOTS}),
        )

    def test_legal_actions_include_wait_defend_and_movement(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": make_stack("a", 1, self.melee, 10, (0, 0)),
                "b": make_stack("b", 2, self.melee, 10, (5, 4)),
            },
        )
        sim = BattleSimulator(state, {1: StaticStrategy(ActionType.WAIT), 2: StaticStrategy(ActionType.WAIT)})
        actions = sim.legal_actions("a")
        self.assertTrue(any(action.action_type == ActionType.MOVE for action in actions))
        self.assertTrue(any(action.action_type == ActionType.WAIT for action in actions))
        self.assertTrue(any(action.action_type == ActionType.DEFEND for action in actions))

    def test_ranged_attack_available_when_not_engaged(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": make_stack("a", 1, self.ranged, 10, (0, 0)),
                "b": make_stack("b", 2, self.melee, 10, (4, 2)),
            },
        )
        sim = BattleSimulator(state, {1: StaticStrategy(ActionType.WAIT), 2: StaticStrategy(ActionType.WAIT)})
        self.assertTrue(any(action.action_type == ActionType.ATTACK_RANGED for action in sim.legal_actions("a")))

    def test_melee_attack_reduces_enemy_units(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": make_stack("a", 1, self.melee, 12, (0, 0)),
                "b": make_stack("b", 2, self.melee, 10, (1, 0)),
            },
        )
        sim = BattleSimulator(state, {1: StaticStrategy(ActionType.ATTACK_MELEE), 2: StaticStrategy(ActionType.DEFEND)})
        action = next(action for action in sim.legal_actions("a") if action.action_type == ActionType.ATTACK_MELEE)
        resolution = sim.resolve_action(StrategyDecision(action=action, strategy_name="test", candidate_scores=[]), sim.reward_tracker.empty_delta())
        self.assertLess(resolution["after"]["b"]["count"], 10)

    def test_double_strike_hits_twice(self) -> None:
        striker = CreatureTemplate(
            name="striker",
            attack=8,
            defense=5,
            min_damage=4,
            max_damage=4,
            health=12,
            speed=4,
            initiative=6,
            abilities=frozenset({Ability.DOUBLE_STRIKE}),
        )
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": make_stack("a", 1, striker, 5, (0, 0)),
                "b": make_stack("b", 2, self.melee, 8, (1, 0)),
            },
        )
        sim = BattleSimulator(state, {1: StaticStrategy(ActionType.ATTACK_MELEE), 2: StaticStrategy(ActionType.DEFEND)})
        action = next(action for action in sim.legal_actions("a") if action.action_type == ActionType.ATTACK_MELEE)
        sim.resolve_action(StrategyDecision(action=action, strategy_name="test", candidate_scores=[]), sim.reward_tracker.empty_delta())
        self.assertLess(state.stacks["b"].count, 6)

    def test_weighted_strategy_prefers_attack(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": make_stack("a", 1, self.melee, 10, (0, 0)),
                "b": make_stack("b", 2, self.melee, 10, (1, 0)),
            },
        )
        sim = BattleSimulator(state, {1: StaticStrategy(ActionType.WAIT), 2: StaticStrategy(ActionType.WAIT)})
        strategy = WeightedHeuristicStrategy(
            weights={
                "is_melee_attack": 5.0,
                "estimated_kills": 2.0,
                "retaliation_risk": -1.0,
                "is_wait": -5.0,
                "is_defend": -2.0,
            },
            seed=1,
        )
        decision = strategy.choose_action(state, "a", sim.legal_actions("a"))
        self.assertEqual(decision.action.action_type, ActionType.ATTACK_MELEE)


if __name__ == "__main__":
    unittest.main()
