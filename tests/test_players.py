from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.engine import BattleSimulator
from pheroes_sim.hexgrid import HexCoord
from pheroes_sim.models import ActionType, ArmyStack, Battlefield, BattleState, CreatureTemplate
from pheroes_sim.strategies import list_available_strategy_ids, load_strategy


class StrategyLoaderTests(unittest.TestCase):
    def test_lists_expected_builtin_strategy_ids(self) -> None:
        self.assertEqual(list_available_strategy_ids(), ["random", "weighted_a", "weighted_b"])

    def test_unknown_strategy_id_fails_with_available_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown strategy 'missing_strategy'.*weighted_a"):
            load_strategy("missing_strategy")

    def test_seed_override_is_applied(self) -> None:
        strategy = load_strategy("weighted_a", seed_override=1234)
        self.assertEqual(strategy.seed, 1234)

    def test_weighted_variants_produce_distinct_score_profiles(self) -> None:
        melee = CreatureTemplate(
            name="melee",
            attack=5,
            defense=4,
            min_damage=2,
            max_damage=4,
            health=10,
            speed=4,
            initiative=5,
        )
        state = BattleState(
            battlefield=Battlefield(width=6, height=5),
            stacks={
                "a": ArmyStack.from_template("a", 1, melee, 10, HexCoord(0, 0)),
                "b": ArmyStack.from_template("b", 2, melee, 10, HexCoord(1, 0)),
            },
        )
        legal_actions = BattleSimulator(
            state, {1: load_strategy("random", seed_override=1), 2: load_strategy("random", seed_override=2)}
        ).legal_actions("a")
        weighted_a = load_strategy("weighted_a", seed_override=1)
        weighted_b = load_strategy("weighted_b", seed_override=1)
        decision_a = weighted_a.choose_action(state, "a", legal_actions)
        decision_b = weighted_b.choose_action(state, "a", legal_actions)
        scores_a = {candidate.action.stable_key(): candidate.total_score for candidate in decision_a.candidate_scores}
        scores_b = {candidate.action.stable_key(): candidate.total_score for candidate in decision_b.candidate_scores}
        self.assertNotEqual(scores_a, scores_b)
        self.assertEqual(decision_a.action.action_type, ActionType.ATTACK_MELEE)
        self.assertEqual(decision_b.action.action_type, ActionType.ATTACK_MELEE)


if __name__ == "__main__":
    unittest.main()
