from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any, Callable

from .hexgrid import reachable_hexes
from .models import Ability, ActionType, ArmyStack, BattleAction, BattleState
from .rewards import RewardTracker
from .strategies import Strategy, StrategyDecision


Observer = Callable[[str, BattleState, dict[str, Any]], None]


class BattleSimulator:
    def __init__(
        self,
        state: BattleState,
        strategies: dict[int, Strategy],
        reward_tracker: RewardTracker | None = None,
        seed: int = 0,
    ) -> None:
        self.state = state
        self.strategies = strategies
        self.reward_tracker = reward_tracker or RewardTracker()
        self.rng = random.Random(seed)
        self._start_round()

    def run(
        self,
        logger: Any | None = None,
        observer: Observer | None = None,
    ) -> tuple[Any, dict[int, float]]:
        if logger is not None:
            logger.write(self._event("battle_started", {"round": self.state.round_number}))
        if observer is not None:
            observer("battle_started", self.state, {"round": self.state.round_number})

        while not self.state.is_finished():
            actor_id = self._next_actor_id()
            if actor_id is None:
                self.state.round_number += 1
                if self.state.is_finished():
                    break
                self._start_round()
                if logger is not None:
                    logger.write(self._event("round_started", {"round": self.state.round_number}))
                if observer is not None:
                    observer("round_started", self.state, {"round": self.state.round_number})
                continue

            actor = self.state.stacks[actor_id]
            if not actor.alive:
                continue

            self.state.active_stack_id = actor_id
            legal_actions = self.legal_actions(actor_id)
            strategy = self.strategies[actor.owner]
            decision = strategy.choose_action(self.state, actor_id, legal_actions)
            reward_delta = self.reward_tracker.empty_delta()
            self.reward_tracker.register_metric(actor.owner, "action_selected", 1.0, reward_delta)

            if logger is not None:
                logger.write(
                    self._event(
                        "decision",
                        {
                            "round": self.state.round_number,
                            "turn": self.state.turns_taken + 1,
                            "actor_id": actor_id,
                            "owner": actor.owner,
                            "strategy": decision.strategy_name,
                            "legal_actions": [action.to_dict() for action in legal_actions],
                            "candidate_scores": [candidate.to_dict() for candidate in decision.candidate_scores],
                            "selected_action": decision.action.to_dict(),
                        },
                    )
                )

            resolution = self.resolve_action(decision, reward_delta)
            self.state.turns_taken += 1
            if logger is not None:
                logger.write(self._event("action_resolved", resolution))
            if observer is not None:
                observer("action_resolved", self.state, resolution)

        summary = self.state.summary()
        terminal_delta = self.reward_tracker.empty_delta()
        self.reward_tracker.register_terminal(summary.winner, terminal_delta)
        if logger is not None:
            logger.write(self._event("battle_finished", {"summary": asdict(summary), "terminal_rewards": terminal_delta}))
        if observer is not None:
            observer("battle_finished", self.state, {"summary": asdict(summary), "terminal_rewards": terminal_delta})
        return summary, self.reward_tracker.totals

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.state.log_index += 1
        return {"event_index": self.state.log_index, "event_type": event_type, **payload}

    def _start_round(self) -> None:
        for stack in self.state.stacks.values():
            if stack.alive:
                stack.defended = False
                stack.retaliated_round = 0
                stack.waited_round = None
        self.state.pending_order = sorted(
            self.state.living_stack_ids(),
            key=lambda stack_id: (
                self.state.stacks[stack_id].template.initiative,
                self.state.stacks[stack_id].template.speed,
                stack_id,
            ),
            reverse=True,
        )
        self.state.waiting_order = []
        self.state.active_stack_id = None

    def _next_actor_id(self) -> str | None:
        while self.state.pending_order:
            stack_id = self.state.pending_order.pop(0)
            if self.state.stacks[stack_id].alive:
                return stack_id
        while self.state.waiting_order:
            stack_id = self.state.waiting_order.pop(0)
            if self.state.stacks[stack_id].alive:
                return stack_id
        return None

    def legal_actions(self, actor_id: str) -> list[BattleAction]:
        actor = self.state.stacks[actor_id]
        if not actor.alive or actor.position is None:
            return [BattleAction(action_type=ActionType.SKIP, actor_id=actor_id)]

        enemy_owner = 2 if actor.owner == 1 else 1
        enemy_ids = self.state.living_stack_ids(enemy_owner)
        occupied = self.state.occupied_hexes(exclude_stack_id=actor_id)
        reachable = reachable_hexes(
            actor.position,
            self.state.battlefield.width,
            self.state.battlefield.height,
            actor.template.speed,
            occupied,
            flying=Ability.FLYING in actor.template.abilities,
        )

        actions: list[BattleAction] = []
        adjacent_enemies = {
            enemy_id: self.state.stacks[enemy_id]
            for enemy_id in enemy_ids
            if self.state.stacks[enemy_id].position in actor.position.neighbors()
        }

        for enemy_id in adjacent_enemies:
            actions.append(BattleAction(action_type=ActionType.ATTACK_MELEE, actor_id=actor_id, target_id=enemy_id))

        for enemy_id in enemy_ids:
            enemy = self.state.stacks[enemy_id]
            if enemy.position is None:
                continue
            for tile in sorted(neighbor for neighbor in enemy.position.neighbors() if neighbor in reachable):
                actions.append(
                    BattleAction(
                        action_type=ActionType.ATTACK_MELEE,
                        actor_id=actor_id,
                        target_id=enemy_id,
                        attack_from=tile,
                    )
                )

        if actor.template.is_ranged and actor.shots_remaining > 0 and not adjacent_enemies:
            for enemy_id in enemy_ids:
                actions.append(BattleAction(action_type=ActionType.ATTACK_RANGED, actor_id=actor_id, target_id=enemy_id))

        for destination in sorted(reachable):
            actions.append(BattleAction(action_type=ActionType.MOVE, actor_id=actor_id, target_pos=destination))

        actions.append(BattleAction(action_type=ActionType.WAIT, actor_id=actor_id))
        actions.append(BattleAction(action_type=ActionType.DEFEND, actor_id=actor_id))
        deduped = {action.stable_key(): action for action in actions}
        return list(sorted(deduped.values(), key=lambda item: item.stable_key()))

    def resolve_action(self, decision: StrategyDecision, reward_delta: dict[int, dict[str, float]]) -> dict[str, Any]:
        action = decision.action
        actor = self.state.stacks[action.actor_id]
        before = self.state.stack_snapshots()

        if action.action_type == ActionType.WAIT:
            actor.waited_round = self.state.round_number
            self.state.waiting_order.append(actor.stack_id)
            self.state.waiting_order.sort(
                key=lambda stack_id: (
                    self.state.stacks[stack_id].template.initiative,
                    self.state.stacks[stack_id].template.speed,
                    stack_id,
                ),
                reverse=True,
            )
        elif action.action_type == ActionType.DEFEND:
            actor.defended = True
        elif action.action_type == ActionType.MOVE:
            actor.position = action.target_pos
        elif action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
            self._resolve_attack(actor, action, reward_delta)

        after = self.state.stack_snapshots()
        return {
            "round": self.state.round_number,
            "turn": self.state.turns_taken + 1,
            "actor_id": actor.stack_id,
            "owner": actor.owner,
            "action": action.to_dict(),
            "reward_delta": reward_delta,
            "before": {stack_id: asdict(snapshot) for stack_id, snapshot in before.items()},
            "after": {stack_id: asdict(snapshot) for stack_id, snapshot in after.items()},
        }

    def _resolve_attack(self, actor: ArmyStack, action: BattleAction, reward_delta: dict[int, dict[str, float]]) -> None:
        if action.target_id is None:
            raise ValueError("Attack action requires target_id")

        if action.attack_from is not None:
            actor.position = action.attack_from

        defender = self.state.stacks[action.target_id]
        damage = self._compute_damage(actor, defender, ranged=action.action_type == ActionType.ATTACK_RANGED)
        actual_damage, units_killed = defender.apply_damage(damage)
        self.reward_tracker.register_metric(actor.owner, "damage_dealt", actual_damage, reward_delta)
        self.reward_tracker.register_metric(defender.owner, "damage_taken", actual_damage, reward_delta)
        self.reward_tracker.register_metric(actor.owner, "units_killed", units_killed, reward_delta)
        self.reward_tracker.register_metric(defender.owner, "units_lost", units_killed, reward_delta)

        if action.action_type == ActionType.ATTACK_RANGED and actor.shots_remaining > 0:
            actor.shots_remaining -= 1

        if (
            defender.alive
            and action.action_type == ActionType.ATTACK_MELEE
            and Ability.NO_RETALIATION not in actor.template.abilities
            and defender.retaliated_round != self.state.round_number
        ):
            retaliation_damage = self._compute_damage(defender, actor, ranged=False)
            actual_retaliation, retaliation_kills = actor.apply_damage(retaliation_damage)
            defender.retaliated_round = self.state.round_number
            self.reward_tracker.register_metric(defender.owner, "damage_dealt", actual_retaliation, reward_delta)
            self.reward_tracker.register_metric(actor.owner, "damage_taken", actual_retaliation, reward_delta)
            self.reward_tracker.register_metric(defender.owner, "units_killed", retaliation_kills, reward_delta)
            self.reward_tracker.register_metric(actor.owner, "units_lost", retaliation_kills, reward_delta)

        if defender.alive and Ability.DOUBLE_STRIKE in actor.template.abilities:
            second_damage = self._compute_damage(actor, defender, ranged=False)
            actual_second, second_kills = defender.apply_damage(second_damage)
            self.reward_tracker.register_metric(actor.owner, "damage_dealt", actual_second, reward_delta)
            self.reward_tracker.register_metric(defender.owner, "damage_taken", actual_second, reward_delta)
            self.reward_tracker.register_metric(actor.owner, "units_killed", second_kills, reward_delta)
            self.reward_tracker.register_metric(defender.owner, "units_lost", second_kills, reward_delta)

    def _compute_damage(self, attacker: ArmyStack, defender: ArmyStack, *, ranged: bool) -> int:
        attack_diff = attacker.template.attack - defender.template.defense
        modifier = max(0.3, 1.0 + (0.05 * attack_diff))
        if defender.defended:
            modifier *= 0.7
        if ranged and attacker.position is not None and defender.position is not None:
            if attacker.position.distance_to(defender.position) > 6:
                modifier *= 0.5
            if any(
                enemy.position in attacker.position.neighbors()
                for enemy in self.state.stacks.values()
                if enemy.alive and enemy.owner != attacker.owner and enemy.position is not None
            ):
                modifier *= 0.5
        return max(1, int(round(attacker.estimated_average_damage() * modifier)))
