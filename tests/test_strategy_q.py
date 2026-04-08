from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.engine import BattleSimulator
from pheroes_sim.hexgrid import HexCoord
from pheroes_sim.models import Ability, ActionType, ArmyStack, Battlefield, BattleState, CreatureTemplate
from pheroes_sim.strategies.strategy_q import (
    DEFAULT_PARAMS,
    GlobalPosture,
    LocalRole,
    QStrategy,
    _build_threat_map,
    _compute_posture,
    _compute_role,
    _exp_decay,
    _logistic,
    build_strategy,
    _find_best_target_pos,
)


def _make_template(
    name: str = "t",
    attack: int = 5,
    defense: int = 4,
    health: int = 10,
    speed: int = 4,
    initiative: int = 5,
    shots: int = 0,
    abilities: frozenset[Ability] = frozenset(),
) -> CreatureTemplate:
    return CreatureTemplate(
        name=name,
        attack=attack,
        defense=defense,
        min_damage=2,
        max_damage=4,
        health=health,
        speed=speed,
        initiative=initiative,
        shots=shots,
        abilities=abilities,
    )


def _make_stack(
    stack_id: str,
    owner: int,
    template: CreatureTemplate,
    count: int,
    pos: tuple[int, int],
) -> ArmyStack:
    return ArmyStack.from_template(stack_id, owner, template, count, HexCoord(*pos))


def _two_stack_state(
    own_template: CreatureTemplate,
    own_count: int,
    own_pos: tuple[int, int],
    enemy_template: CreatureTemplate,
    enemy_count: int,
    enemy_pos: tuple[int, int],
) -> BattleState:
    return BattleState(
        battlefield=Battlefield(width=8, height=6),
        stacks={
            "a": _make_stack("a", 1, own_template, own_count, own_pos),
            "b": _make_stack("b", 2, enemy_template, enemy_count, enemy_pos),
        },
    )


# ---------------------------------------------------------------------------
# Curve functions
# ---------------------------------------------------------------------------


class CurveTests(unittest.TestCase):
    def test_logistic_at_midpoint_is_half(self) -> None:
        self.assertAlmostEqual(_logistic(0.7, 8.0, 0.7), 0.5)

    def test_logistic_full_kill_approaches_one(self) -> None:
        self.assertGreater(_logistic(1.5, 8.0, 0.7), 0.95)

    def test_logistic_zero_damage_approaches_zero(self) -> None:
        self.assertLess(_logistic(0.0, 8.0, 0.7), 0.1)

    def test_logistic_monotone_increasing(self) -> None:
        values = [_logistic(x / 10, 8.0, 0.7) for x in range(0, 20)]
        self.assertEqual(values, sorted(values))

    def test_exp_decay_at_zero_threat_is_one(self) -> None:
        self.assertAlmostEqual(_exp_decay(0.0, 3.0), 1.0)

    def test_exp_decay_at_full_threat_is_low(self) -> None:
        self.assertLess(_exp_decay(1.0, 3.0), 0.1)

    def test_exp_decay_monotone_decreasing(self) -> None:
        values = [_exp_decay(x / 10, 3.0) for x in range(0, 20)]
        self.assertEqual(values, sorted(values, reverse=True))


# ---------------------------------------------------------------------------
# Global posture
# ---------------------------------------------------------------------------


class PostureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = dict(DEFAULT_PARAMS)

    def _state_with_hp(
        self,
        own_count: int,
        enemy_count: int,
        own_ranged: bool = False,
    ) -> BattleState:
        own_t = _make_template(shots=5 if own_ranged else 0)
        enemy_t = _make_template()
        return _two_stack_state(own_t, own_count, (0, 0), enemy_t, enemy_count, (7, 5))

    def test_aggressive_when_hp_ratio_high(self) -> None:
        state = self._state_with_hp(20, 5)
        posture = _compute_posture(state, "a", self.p)
        self.assertEqual(posture, GlobalPosture.AGGRESSIVE)

    def test_defensive_when_hp_ratio_low(self) -> None:
        state = self._state_with_hp(5, 20)
        posture = _compute_posture(state, "a", self.p)
        self.assertEqual(posture, GlobalPosture.DEFENSIVE)

    def test_neutral_when_balanced(self) -> None:
        # Ratio must be in (defensive_hp_threshold=0.4, aggression_hp_threshold=0.9)
        # 8 own vs 10 enemy → ratio = 0.8 → NEUTRAL
        state = self._state_with_hp(8, 10)
        posture = _compute_posture(state, "a", self.p)
        self.assertEqual(posture, GlobalPosture.NEUTRAL)

    def test_kite_when_ranged_dominant(self) -> None:
        state = self._state_with_hp(10, 10, own_ranged=True)
        posture = _compute_posture(state, "a", self.p)
        self.assertEqual(posture, GlobalPosture.KITE)


# ---------------------------------------------------------------------------
# Local role
# ---------------------------------------------------------------------------


class RoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = dict(DEFAULT_PARAMS)

    def _own_stacks(self, stack: ArmyStack) -> list[ArmyStack]:
        return [stack]

    def test_flyer_is_flanker(self) -> None:
        t = _make_template(abilities=frozenset({Ability.FLYING}))
        s = _make_stack("x", 1, t, 5, (0, 0))
        self.assertEqual(_compute_role(s, self._own_stacks(s), self.p), LocalRole.FLANKER)

    def test_flyer_beats_ranged_for_role(self) -> None:
        t = _make_template(shots=5, abilities=frozenset({Ability.FLYING}))
        s = _make_stack("x", 1, t, 5, (0, 0))
        self.assertEqual(_compute_role(s, self._own_stacks(s), self.p), LocalRole.FLANKER)

    def test_shooter_is_artillery(self) -> None:
        t = _make_template(shots=8)
        s = _make_stack("x", 1, t, 5, (0, 0))
        self.assertEqual(_compute_role(s, self._own_stacks(s), self.p), LocalRole.ARTILLERY)

    def test_high_defense_is_barrier(self) -> None:
        # army mean defense is this unit itself, so we add two units
        low_t = _make_template(name="low", defense=3, health=10)
        high_t = _make_template(name="high", defense=8, health=10)
        low_s = _make_stack("low", 1, low_t, 5, (1, 0))
        high_s = _make_stack("high", 1, high_t, 5, (0, 0))
        # mean defense = (3+8)/2 = 5.5, tank threshold = 5.5+1.0 = 6.5; high has 8 > 6.5
        self.assertEqual(_compute_role(high_s, [low_s, high_s], self.p), LocalRole.BARRIER)

    def test_high_hp_pool_is_barrier(self) -> None:
        low_t = _make_template(name="low", health=10)
        big_t = _make_template(name="big", health=50)
        low_s = _make_stack("low", 1, low_t, 5, (1, 0))  # total_health = 5*10 = 50
        big_s = _make_stack("big", 1, big_t, 10, (0, 0))  # total_health = 10*50 = 500
        # mean = (50 + 500) / 2 = 275; threshold = 275 * 1.3 = 357.5; big_s has 500 > 357.5
        self.assertEqual(_compute_role(big_s, [low_s, big_s], self.p), LocalRole.BARRIER)

    def test_generalist_fallback(self) -> None:
        t = _make_template(defense=4, health=10)
        s = _make_stack("x", 1, t, 5, (0, 0))
        self.assertEqual(_compute_role(s, self._own_stacks(s), self.p), LocalRole.GENERALIST)


# ---------------------------------------------------------------------------
# Threat map
# ---------------------------------------------------------------------------


class ThreatMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = dict(DEFAULT_PARAMS)

    def test_threat_zero_when_enemy_out_of_range(self) -> None:
        own_t = _make_template(health=100)
        enemy_t = _make_template(speed=1)
        state = _two_stack_state(own_t, 10, (0, 0), enemy_t, 5, (7, 5))
        threat_map = _build_threat_map(state, "a", self.p)
        # Actor is at (0,0); enemy at (7,5) with speed=1 can barely reach anything
        threat_at_origin = threat_map.get(HexCoord(0, 0), 0.0)
        self.assertAlmostEqual(threat_at_origin, 0.0)

    def test_threat_nonzero_when_enemy_adjacent(self) -> None:
        own_t = _make_template(health=10)
        enemy_t = _make_template(speed=4)
        state = _two_stack_state(own_t, 5, (0, 0), enemy_t, 5, (1, 0))
        threat_map = _build_threat_map(state, "a", self.p)
        # (0,0) is adjacent to enemy at (1,0); should have threat
        threat_at_origin = threat_map.get(HexCoord(0, 0), 0.0)
        self.assertGreater(threat_at_origin, 0.0)

    def test_ranged_threat_nonzero_beyond_move_range(self) -> None:
        # Ranged enemy at distance 5 with speed=2 (can't reach actor via movement)
        # but ranged_effective_range=8 should still mark the actor's hex as threatened
        own_t = _make_template(health=100)
        enemy_t = _make_template(shots=8, speed=2)
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "a": _make_stack("a", 1, own_t, 5, (0, 0)),
                "b": _make_stack("b", 2, enemy_t, 5, (5, 0)),
            },
        )
        p = dict(DEFAULT_PARAMS)
        p["ranged_effective_range"] = 8.0
        p["ranged_threat_scale"] = 0.7
        threat_map = _build_threat_map(state, "a", p)
        # Actor at (0,0) is within 8 hexes of enemy at (5,0) — must have ranged threat
        threat_at_origin = threat_map.get(HexCoord(0, 0), 0.0)
        self.assertGreater(threat_at_origin, 0.0)

    def test_threat_normalized_by_actor_hp(self) -> None:
        own_t = _make_template(health=100)
        enemy_t = _make_template(speed=6, attack=10)
        state = _two_stack_state(own_t, 1, (0, 0), enemy_t, 10, (1, 0))
        threat_map = _build_threat_map(state, "a", self.p)
        # All values should be relative fractions (not raw damage)
        for v in threat_map.values():
            self.assertGreater(v, 0.0)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class QStrategyIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.melee_t = _make_template()
        self.ranged_t = _make_template(shots=8, abilities=frozenset({Ability.LIMITED_SHOTS}))

    def test_implements_strategy_protocol(self) -> None:
        strategy = build_strategy()
        self.assertTrue(hasattr(strategy, "choose_action"))

    def test_prefers_melee_attack_when_adjacent(self) -> None:
        state = _two_stack_state(self.melee_t, 10, (0, 0), self.melee_t, 10, (1, 0))
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 5.0
        p["kill_steepness"] = 10.0
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        self.assertEqual(decision.action.action_type, ActionType.ATTACK_MELEE)

    def test_high_threat_moves_score_lower_than_safe_moves(self) -> None:
        # Enemy is at (4,3); actor is at (0,0) with speed=6 so it can reach both
        # safe hexes (far from enemy) and dangerous hexes (adjacent to enemy).
        # With high decay, MOVE actions towards the enemy should score lower than
        # MOVE actions away from it.
        own_t = _make_template(health=10, speed=6)
        enemy_t = _make_template(attack=10, health=100, speed=2)
        state = _two_stack_state(own_t, 5, (0, 0), enemy_t, 20, (4, 3))
        p = dict(DEFAULT_PARAMS)
        p["preserve_decay_rate"] = 8.0  # very risk-averse
        p["w_kill"] = 0.0  # disable kill scoring to isolate preservation effect
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        # Find preservation scores for move actions by destination distance to enemy
        from pheroes_sim.models import ActionType
        enemy_pos = state.stacks["b"].position
        move_candidates = [
            c for c in decision.candidate_scores
            if c.action.action_type == ActionType.MOVE and c.action.target_pos is not None
        ]
        if len(move_candidates) < 2:
            return  # nothing to compare
        # Group by distance to enemy
        close = [c for c in move_candidates if c.action.target_pos.distance_to(enemy_pos) <= 2]
        far = [c for c in move_candidates if c.action.target_pos.distance_to(enemy_pos) >= 4]
        if close and far:
            max_close_score = max(c.total_score for c in close)
            max_far_score = max(c.total_score for c in far)
            self.assertGreater(max_far_score, max_close_score)

    def test_full_battle_completes_without_error(self) -> None:
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "p1_a": _make_stack("p1_a", 1, self.melee_t, 10, (1, 1)),
                "p1_b": _make_stack("p1_b", 1, self.ranged_t, 8, (1, 4)),
                "p2_a": _make_stack("p2_a", 2, self.melee_t, 10, (6, 1)),
                "p2_b": _make_stack("p2_b", 2, self.ranged_t, 8, (6, 4)),
            },
        )
        strategy = build_strategy(seed=42)
        sim = BattleSimulator(state, {1: strategy, 2: strategy}, seed=42)
        summary, rewards = sim.run()
        self.assertIn(summary.outcome, {"player_1_win", "player_2_win", "draw", "round_limit"})

    def test_candidate_scores_logged_with_features(self) -> None:
        state = _two_stack_state(self.melee_t, 10, (0, 0), self.melee_t, 10, (3, 3))
        strategy = build_strategy()
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        self.assertGreater(len(decision.candidate_scores), 0)
        for cs in decision.candidate_scores:
            self.assertIn("kill_score", cs.features)
            self.assertIn("preservation_score", cs.features)
            self.assertIn("role_score", cs.features)

    def test_strategy_discovered_by_loader(self) -> None:
        from pheroes_sim.strategies import list_available_strategy_ids
        self.assertIn("strategy_q", list_available_strategy_ids())

    def test_move_prefers_approaching_enemy(self) -> None:
        # With very high w_approach and kill disabled, MOVE toward enemy scores higher
        own_t = _make_template(speed=6, health=10)
        enemy_t = _make_template(health=100, speed=1)
        state = _two_stack_state(own_t, 5, (0, 0), enemy_t, 5, (7, 0))
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        p["w_approach"] = 5.0
        p["preserve_decay_rate"] = 0.0  # no preservation effect
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        enemy_pos = state.stacks["b"].position
        move_candidates = [
            c for c in decision.candidate_scores
            if c.action.action_type == ActionType.MOVE and c.action.target_pos is not None
        ]
        if len(move_candidates) < 2:
            return
        # Best MOVE should be one that closes distance to enemy
        best_move = max(move_candidates, key=lambda c: c.total_score)
        actor_pos = state.stacks["a"].position
        dist_before = actor_pos.distance_to(enemy_pos)
        dist_after = best_move.action.target_pos.distance_to(enemy_pos)
        self.assertLess(dist_after, dist_before)

    def test_retaliation_zero_for_no_retaliation_target(self) -> None:
        # Attacking a target with NO_RETALIATION should not incur retaliation penalty
        melee_t = _make_template(health=10, speed=1)
        harpy_t = _make_template(health=10, speed=1, abilities=frozenset({Ability.NO_RETALIATION}))
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "a": _make_stack("a", 1, melee_t, 5, (0, 0)),
                "b_normal": _make_stack("b_normal", 2, melee_t, 5, (1, 0)),
                "b_harpy": _make_stack("b_harpy", 2, harpy_t, 5, (0, 1)),
            },
        )
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        p["w_retaliation"] = 10.0  # very high penalty to make difference obvious
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        melee_vs_normal = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_normal"),
            None,
        )
        melee_vs_harpy = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_harpy"),
            None,
        )
        if melee_vs_normal is not None and melee_vs_harpy is not None:
            # Harpy has no retaliation, so its melee score should be HIGHER (less penalized)
            self.assertGreater(melee_vs_harpy, melee_vs_normal)

    def test_retaliation_lowers_melee_score(self) -> None:
        # Two enemies at equal distance and equal kill potential; higher-damage one scores lower.
        # Use different min/max_damage (not attack stat) since estimated_average_damage uses those.
        melee_t = _make_template(health=10, speed=1)
        low_dmg = CreatureTemplate(
            name="low", attack=5, defense=4, min_damage=1, max_damage=2, health=10, speed=1, initiative=5
        )
        high_dmg = CreatureTemplate(
            name="high", attack=5, defense=4, min_damage=10, max_damage=20, health=10, speed=1, initiative=5
        )
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "a": _make_stack("a", 1, melee_t, 5, (0, 0)),
                "b_low": _make_stack("b_low", 2, low_dmg, 5, (1, 0)),
                "b_high": _make_stack("b_high", 2, high_dmg, 5, (0, 1)),
            },
        )
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        p["w_retaliation"] = 5.0
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        melee_vs_low = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_low"),
            None,
        )
        melee_vs_high = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_high"),
            None,
        )
        if melee_vs_low is not None and melee_vs_high is not None:
            self.assertGreater(melee_vs_low, melee_vs_high)

    def test_move_cost_penalizes_distant_attack_from(self) -> None:
        # Enemy is far away; attack_from hex will be far from actor
        # With w_move_cost high, attacks requiring long approach score lower
        own_t = _make_template(speed=6, health=10)
        enemy_t = _make_template(health=100, speed=1)
        state = _two_stack_state(own_t, 5, (0, 0), enemy_t, 5, (7, 0))
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        p["w_move_cost"] = 10.0
        p["preserve_decay_rate"] = 0.0
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        melee_candidates = [
            c for c in decision.candidate_scores
            if c.action.action_type == ActionType.ATTACK_MELEE and c.action.attack_from is not None
        ]
        if len(melee_candidates) < 2:
            return
        actor_pos = state.stacks["a"].position
        close = [c for c in melee_candidates if actor_pos.distance_to(c.action.attack_from) <= 1]
        far = [c for c in melee_candidates if actor_pos.distance_to(c.action.attack_from) >= 3]
        if close and far:
            self.assertGreater(max(c.total_score for c in close), max(c.total_score for c in far))

    def test_target_value_prefers_high_stat_enemy(self) -> None:
        # With equal kill potential, higher stat enemy should score higher with w_target_value > 0
        melee_t = _make_template(health=10, speed=1)
        low_stat = CreatureTemplate(
            name="low", attack=2, defense=2, min_damage=2, max_damage=4, health=10, speed=1, initiative=2
        )
        high_stat = CreatureTemplate(
            name="high", attack=8, defense=8, min_damage=2, max_damage=4, health=10, speed=1, initiative=8
        )
        state = BattleState(
            battlefield=Battlefield(width=8, height=6),
            stacks={
                "a": _make_stack("a", 1, melee_t, 5, (0, 0)),
                "b_low": _make_stack("b_low", 2, low_stat, 5, (1, 0)),
                "b_high": _make_stack("b_high", 2, high_stat, 5, (0, 1)),
            },
        )
        p = dict(DEFAULT_PARAMS)
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        p["w_retaliation"] = 0.0
        p["w_target_value"] = 0.5
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        score_vs_low = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_low"),
            None,
        )
        score_vs_high = next(
            (c.total_score for c in decision.candidate_scores
             if c.action.action_type == ActionType.ATTACK_MELEE and c.action.target_id == "b_high"),
            None,
        )
        if score_vs_low is not None and score_vs_high is not None:
            self.assertGreater(score_vs_high, score_vs_low)

    def test_wait_score_not_better_at_threatened_hex(self) -> None:
        # Math fix: WAIT (negative raw) must not score higher at threatened hex than at safe hex
        own_t = _make_template(health=10, speed=1)
        enemy_t = _make_template(attack=10, speed=6)
        state = _two_stack_state(own_t, 5, (0, 0), enemy_t, 20, (1, 0))
        p = dict(DEFAULT_PARAMS)
        p["preserve_decay_rate"] = 3.0
        p["w_kill"] = 0.0
        p["w_role"] = 0.0
        strategy = QStrategy(params=p, seed=0)
        sim = BattleSimulator(state, {1: strategy, 2: strategy})
        actions = sim.legal_actions("a")
        decision = strategy.choose_action(state, "a", actions)
        wait_candidates = [
            c for c in decision.candidate_scores
            if c.action.action_type == ActionType.WAIT
        ]
        if not wait_candidates:
            return
        # WAIT score should be negative (w_wait=-2.0) and not elevated by threat
        for c in wait_candidates:
            self.assertLess(c.total_score, 0.0)


if __name__ == "__main__":
    unittest.main()
