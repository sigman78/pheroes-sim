from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum
from math import exp
from typing import Any

from ..hexgrid import HexCoord, reachable_hexes
from ..models import Ability, ActionType, ArmyStack, BattleState
from ..strategy_core import CandidateScore, Strategy, StrategyDecision

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GlobalPosture(StrEnum):
    AGGRESSIVE = "aggressive"
    NEUTRAL = "neutral"
    DEFENSIVE = "defensive"
    KITE = "kite"


class LocalRole(StrEnum):
    FLANKER = "flanker"
    ARTILLERY = "artillery"
    BARRIER = "barrier"
    GENERALIST = "generalist"


# ---------------------------------------------------------------------------
# Response curves
# ---------------------------------------------------------------------------


def _logistic(x: float, k: float, x0: float) -> float:
    """Logistic S-curve: 0 at x<<x0, 0.5 at x=x0, ~1 at x>>x0."""
    return 1.0 / (1.0 + exp(-k * (x - x0)))


def _exp_decay(threat: float, lam: float) -> float:
    """Exponential decay: 1.0 at threat=0, approaches 0 as threat grows."""
    return exp(-lam * threat)


# ---------------------------------------------------------------------------
# Threat map
# ---------------------------------------------------------------------------


def _build_threat_map(
    state: BattleState,
    actor_id: str,
    p: dict[str, float],
) -> dict[HexCoord, float]:
    """
    For each hex, sum estimated damage from all enemies that could reach it
    on the next turn, then normalize by actor's total HP.
    """
    actor = state.stacks[actor_id]
    actor_hp = max(1, actor.total_health())
    enemy_owner = 2 if actor.owner == 1 else 1
    enemy_ids = state.living_stack_ids(enemy_owner)

    threat_raw: dict[HexCoord, float] = {}

    # All occupied hexes (for blocking calculations, ignoring actor itself)
    occupied = state.occupied_hexes(exclude_stack_id=actor_id)

    for eid in enemy_ids:
        enemy = state.stacks[eid]
        if enemy.position is None:
            continue
        dmg = float(enemy.estimated_average_damage())
        flying = Ability.FLYING in enemy.template.abilities

        # Hexes enemy can reach by moving
        reachable = reachable_hexes(
            enemy.position,
            state.battlefield.width,
            state.battlefield.height,
            enemy.template.speed,
            occupied,
            flying=flying,
        )
        # Also include hexes adjacent to enemy's current position (melee reach)
        melee_hexes = set(enemy.position.neighbors())

        for h in reachable | melee_hexes:
            threat_raw[h] = threat_raw.get(h, 0.0) + dmg

    return {h: v / actor_hp for h, v in threat_raw.items()}


# ---------------------------------------------------------------------------
# Global posture
# ---------------------------------------------------------------------------


def _compute_posture(
    state: BattleState,
    actor_id: str,
    p: dict[str, float],
) -> GlobalPosture:
    actor = state.stacks[actor_id]
    own_owner = actor.owner
    enemy_owner = 2 if own_owner == 1 else 1

    own_hp = sum(
        state.stacks[sid].total_health() for sid in state.living_stack_ids(own_owner)
    )
    enemy_hp = sum(
        state.stacks[sid].total_health() for sid in state.living_stack_ids(enemy_owner)
    )
    hp_ratio = own_hp / max(1, enemy_hp)

    own_ranged_hp = sum(
        state.stacks[sid].total_health()
        for sid in state.living_stack_ids(own_owner)
        if state.stacks[sid].template.is_ranged
    )
    ranged_fraction = own_ranged_hp / max(1, own_hp)

    if ranged_fraction > p["kite_ranged_fraction"]:
        return GlobalPosture.KITE
    if hp_ratio > p["aggression_hp_threshold"]:
        return GlobalPosture.AGGRESSIVE
    if hp_ratio < p["defensive_hp_threshold"]:
        return GlobalPosture.DEFENSIVE
    return GlobalPosture.NEUTRAL


# ---------------------------------------------------------------------------
# Local role
# ---------------------------------------------------------------------------


def _compute_role(
    stack: ArmyStack,
    own_stacks: list[ArmyStack],
    p: dict[str, float],
) -> LocalRole:
    if Ability.FLYING in stack.template.abilities:
        return LocalRole.FLANKER
    if stack.template.is_ranged:
        return LocalRole.ARTILLERY

    if own_stacks:
        mean_defense = sum(s.template.defense for s in own_stacks) / len(own_stacks)
        mean_hp_pool = sum(s.total_health() for s in own_stacks) / len(own_stacks)
    else:
        mean_defense = 0.0
        mean_hp_pool = 0.0

    is_tank = (
        stack.template.defense > mean_defense + p["tank_defense_above_mean_by"]
        or stack.total_health() > mean_hp_pool * (1.0 + p["tank_health_pool_above_mean_by"])
    )
    if is_tank:
        return LocalRole.BARRIER
    return LocalRole.GENERALIST


# ---------------------------------------------------------------------------
# Role fulfillment score
# ---------------------------------------------------------------------------


def _highest_threat_enemy_id(state: BattleState, actor_id: str) -> str | None:
    """Return the enemy stack ID with the highest estimated damage."""
    actor = state.stacks[actor_id]
    enemy_owner = 2 if actor.owner == 1 else 1
    enemy_ids = state.living_stack_ids(enemy_owner)
    if not enemy_ids:
        return None
    return max(enemy_ids, key=lambda eid: state.stacks[eid].estimated_average_damage())


def _destination_hex(action: Any, actor_pos: HexCoord | None) -> HexCoord | None:
    """Resolve destination hex for threat and role scoring."""
    if action.attack_from is not None:
        return action.attack_from
    if action.target_pos is not None:
        return action.target_pos
    return actor_pos


def _role_score(
    role: LocalRole,
    action: Any,
    state: BattleState,
    actor_id: str,
    p: dict[str, float],
) -> float:
    actor = state.stacks[actor_id]

    if role == LocalRole.FLANKER:
        if action.target_id is None:
            return p["flanker_nonpriority_score"]
        priority = _highest_threat_enemy_id(state, actor_id)
        return p["flanker_priority_score"] if action.target_id == priority else p["flanker_nonpriority_score"]

    if role == LocalRole.ARTILLERY:
        dest = _destination_hex(action, actor.position)
        if dest is None:
            return p["artillery_safe_score"]
        # Check for adjacent enemies at destination
        enemy_owner = 2 if actor.owner == 1 else 1
        enemy_positions = {
            state.stacks[eid].position
            for eid in state.living_stack_ids(enemy_owner)
            if state.stacks[eid].position is not None
        }
        adjacent_to_dest = set(dest.neighbors())
        exposed = bool(adjacent_to_dest & enemy_positions)
        return p["artillery_exposed_score"] if exposed else p["artillery_safe_score"]

    if role == LocalRole.BARRIER:
        dest = _destination_hex(action, actor.position)
        if dest is None:
            return p["barrier_other_score"]
        own_owner = actor.owner
        own_ranged_positions = {
            state.stacks[sid].position
            for sid in state.living_stack_ids(own_owner)
            if state.stacks[sid].template.is_ranged and state.stacks[sid].position is not None
            and sid != actor_id
        }
        adjacent_to_dest = set(dest.neighbors())
        protecting = bool(adjacent_to_dest & own_ranged_positions)
        return p["barrier_adjacent_friendly_score"] if protecting else p["barrier_other_score"]

    # GENERALIST
    return p["generalist_score"]


# ---------------------------------------------------------------------------
# Action type bias
# ---------------------------------------------------------------------------

_ACTION_WEIGHT_KEY: dict[ActionType, str] = {
    ActionType.ATTACK_MELEE: "w_melee_attack",
    ActionType.ATTACK_RANGED: "w_ranged_attack",
    ActionType.MOVE: "w_move",
    ActionType.WAIT: "w_wait",
    ActionType.DEFEND: "w_defend",
    ActionType.SKIP: "w_wait",  # treat skip like wait
}


# ---------------------------------------------------------------------------
# QStrategy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class QStrategy:
    params: dict[str, float]
    seed: int = 0
    strategy_name: str = "strategy_q"
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def choose_action(
        self,
        state: BattleState,
        actor_id: str,
        legal_actions: list[Any],
    ) -> StrategyDecision:
        p = self.params
        actor = state.stacks[actor_id]

        # Compute context once for this decision
        threat_map = _build_threat_map(state, actor_id, p)
        posture = _compute_posture(state, actor_id, p)
        own_stacks = [state.stacks[sid] for sid in state.living_stack_ids(actor.owner)]
        role = _compute_role(actor, own_stacks, p)

        # Apply posture multipliers to working copies
        effective_w_kill = p["w_kill"] * (p["aggression_kill_multiplier"] if posture == GlobalPosture.AGGRESSIVE else 1.0)
        effective_w_role = p["w_role"] * (p["defensive_role_multiplier"] if posture == GlobalPosture.DEFENSIVE else 1.0)
        effective_decay = p["preserve_decay_rate"] * (p["kite_preserve_multiplier"] if posture == GlobalPosture.KITE else 1.0)

        candidate_scores: list[CandidateScore] = []
        for action in sorted(legal_actions, key=lambda a: a.stable_key()):
            score, features = self._score_action(
                action, state, actor_id, threat_map,
                role, effective_w_kill, effective_w_role, effective_decay, p,
            )
            candidate_scores.append(CandidateScore(action=action, total_score=score, features=features))

        best_score = max(c.total_score for c in candidate_scores)
        best = [c for c in candidate_scores if c.total_score == best_score]
        chosen = self.rng.choice(best).action if len(best) > 1 else best[0].action
        return StrategyDecision(action=chosen, strategy_name=self.strategy_name, candidate_scores=candidate_scores)

    def _score_action(
        self,
        action: Any,
        state: BattleState,
        actor_id: str,
        threat_map: dict[HexCoord, float],
        role: LocalRole,
        effective_w_kill: float,
        effective_w_role: float,
        effective_decay: float,
        p: dict[str, float],
    ) -> tuple[float, dict[str, float]]:
        actor = state.stacks[actor_id]

        # Action type bias
        action_bias = p.get(_ACTION_WEIGHT_KEY.get(action.action_type, "w_wait"), 0.0)

        # Kill score (0 if no target)
        kill_s = 0.0
        if action.target_id is not None:
            target = state.stacks[action.target_id]
            x = min(actor.estimated_average_damage() / max(1, target.total_health()), 2.0)
            kill_s = _logistic(x, p["kill_steepness"], p["kill_midpoint"])

        # Role score
        role_s = _role_score(role, action, state, actor_id, p)

        # Preservation score
        dest = _destination_hex(action, actor.position)
        threat = threat_map.get(dest, 0.0) if dest is not None else 0.0
        preserve_s = _exp_decay(threat, effective_decay)

        raw = action_bias + kill_s * effective_w_kill + role_s * effective_w_role
        score = raw * preserve_s

        features = {
            "action_bias": action_bias,
            "kill_score": kill_s,
            "role_score": role_s,
            "preservation_score": preserve_s,
            "threat": threat,
            "effective_w_kill": effective_w_kill,
            "effective_w_role": effective_w_role,
            "effective_decay": effective_decay,
            "posture_applied": 1.0 if effective_w_kill != p["w_kill"] or effective_decay != p["preserve_decay_rate"] else 0.0,
            "role": float(list(LocalRole).index(role)),
        }
        return score, features


# ---------------------------------------------------------------------------
# Default parameters and builder
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: dict[str, float] = {
    # action type base weights
    "w_melee_attack": 3.0,
    "w_ranged_attack": 2.5,
    "w_move": 0.5,
    "w_wait": -1.0,
    "w_defend": -0.3,
    # kill curve
    "kill_steepness": 8.0,
    "kill_midpoint": 0.7,
    # preservation curve
    "preserve_decay_rate": 3.0,
    # score composition
    "w_kill": 2.0,
    "w_role": 1.0,
    # posture thresholds
    "aggression_hp_threshold": 1.5,
    "defensive_hp_threshold": 0.7,
    "kite_ranged_fraction": 0.5,
    # posture multipliers
    "aggression_kill_multiplier": 1.4,
    "defensive_role_multiplier": 1.5,
    "kite_preserve_multiplier": 1.5,
    # role classification
    "tank_defense_above_mean_by": 1.0,
    "tank_health_pool_above_mean_by": 0.3,
    # role fulfillment scores
    "flanker_priority_score": 1.0,
    "flanker_nonpriority_score": 0.5,
    "artillery_safe_score": 1.0,
    "artillery_exposed_score": 0.0,
    "barrier_adjacent_friendly_score": 1.0,
    "barrier_other_score": 0.3,
    "generalist_score": 0.5,
}

STRATEGY_NAME = "strategy_q"
DEFAULT_SEED = 7


def build_strategy(*, seed: int | None = None) -> Strategy:
    return QStrategy(
        params=dict(DEFAULT_PARAMS),
        seed=DEFAULT_SEED if seed is None else seed,
        strategy_name=STRATEGY_NAME,
    )
