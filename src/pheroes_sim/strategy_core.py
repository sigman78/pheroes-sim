from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from .models import ActionType, BattleAction, BattleState


@dataclass(frozen=True, slots=True)
class CandidateScore:
    action: BattleAction
    total_score: float
    features: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.to_dict(),
            "total_score": self.total_score,
            "features": self.features,
        }


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    action: BattleAction
    strategy_name: str
    candidate_scores: list[CandidateScore]


class Strategy(Protocol):
    def choose_action(
        self,
        state: BattleState,
        actor_id: str,
        legal_actions: list[BattleAction],
    ) -> StrategyDecision: ...


@dataclass(slots=True)
class RandomStrategy:
    seed: int = 0
    strategy_name: str = "random"
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def choose_action(
        self,
        state: BattleState,
        actor_id: str,
        legal_actions: list[BattleAction],
    ) -> StrategyDecision:
        ordered_actions = sorted(legal_actions, key=lambda action: action.stable_key())
        choice = self.rng.choice(ordered_actions)
        scores = [
            CandidateScore(
                action=action,
                total_score=1.0 if action == choice else 0.0,
                features={"picked": 1.0 if action == choice else 0.0},
            )
            for action in ordered_actions
        ]
        return StrategyDecision(action=choice, strategy_name=self.strategy_name, candidate_scores=scores)


@dataclass(slots=True)
class WeightedHeuristicStrategy:
    weights: dict[str, float]
    seed: int = 0
    strategy_name: str = "weighted_heuristic"
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def choose_action(
        self,
        state: BattleState,
        actor_id: str,
        legal_actions: list[BattleAction],
    ) -> StrategyDecision:
        candidate_scores: list[CandidateScore] = []
        for action in sorted(legal_actions, key=lambda item: item.stable_key()):
            features = self._score_features(state, actor_id, action)
            total = sum(self.weights.get(name, 0.0) * value for name, value in features.items())
            candidate_scores.append(CandidateScore(action=action, total_score=total, features=features))

        best_total = max(candidate.total_score for candidate in candidate_scores)
        best = [candidate for candidate in candidate_scores if candidate.total_score == best_total]
        choice = self.rng.choice(best).action if len(best) > 1 else best[0].action
        return StrategyDecision(action=choice, strategy_name=self.strategy_name, candidate_scores=candidate_scores)

    def _score_features(self, state: BattleState, actor_id: str, action: BattleAction) -> dict[str, float]:
        actor = state.stacks[actor_id]
        enemy_ids = state.living_stack_ids(2 if actor.owner == 1 else 1)
        adjacent_enemies = (
            1.0
            if actor.position is not None
            and any(
                state.stacks[enemy_id].position in actor.position.neighbors()
                for enemy_id in enemy_ids
                if state.stacks[enemy_id].position is not None
            )
            else 0.0
        )

        features: dict[str, float] = {
            "base_bias": 1.0,
            "is_wait": 1.0 if action.action_type == ActionType.WAIT else 0.0,
            "is_defend": 1.0 if action.action_type == ActionType.DEFEND else 0.0,
            "is_move": 1.0 if action.action_type == ActionType.MOVE else 0.0,
            "is_melee_attack": 1.0 if action.action_type == ActionType.ATTACK_MELEE else 0.0,
            "is_ranged_attack": 1.0 if action.action_type == ActionType.ATTACK_RANGED else 0.0,
            "adjacent_enemy_pressure": adjacent_enemies,
        }

        if action.target_id is not None:
            target = state.stacks[action.target_id]
            target_health = max(1, target.total_health())
            estimated_damage = actor.estimated_average_damage()
            estimated_kills = min(target.count, estimated_damage / max(1, target.template.health))
            retaliation_risk = 0.0
            if action.action_type == ActionType.ATTACK_MELEE:
                retaliation_risk = target.estimated_average_damage() / max(1, actor.total_health())
            features.update(
                {
                    "target_value": float(target.template.attack + target.template.defense + target.template.initiative),
                    "estimated_damage_ratio": estimated_damage / target_health,
                    "estimated_kills": estimated_kills,
                    "retaliation_risk": retaliation_risk,
                }
            )

        if action.target_pos is not None and actor.position is not None:
            enemy_positions = [
                state.stacks[enemy_id].position
                for enemy_id in enemy_ids
                if state.stacks[enemy_id].position is not None
            ]
            features["distance_closed"] = 0.0
            if enemy_positions:
                current_distance = min(actor.position.distance_to(pos) for pos in enemy_positions)
                next_distance = min(action.target_pos.distance_to(pos) for pos in enemy_positions)
                features["distance_closed"] = float(current_distance - next_distance)
        else:
            features["distance_closed"] = 0.0

        if action.attack_from is not None and actor.position is not None:
            features["move_cost"] = float(actor.position.distance_to(action.attack_from))
        else:
            features["move_cost"] = 0.0
        return features


def create_random_strategy(*, seed: int = 0, strategy_name: str = "random") -> RandomStrategy:
    return RandomStrategy(seed=seed, strategy_name=strategy_name)


def create_weighted_heuristic_strategy(
    *,
    weights: dict[str, float],
    seed: int = 0,
    strategy_name: str = "weighted_heuristic",
) -> WeightedHeuristicStrategy:
    return WeightedHeuristicStrategy(weights=weights, seed=seed, strategy_name=strategy_name)
