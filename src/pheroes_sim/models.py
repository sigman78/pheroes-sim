from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .hexgrid import HexCoord  # noqa: F401 (re-exported for callers)


class Ability(StrEnum):
    FLYING = "flying"
    NO_RETALIATION = "no_retaliation"
    DOUBLE_STRIKE = "double_strike"
    LIMITED_SHOTS = "limited_shots"


class ActionType(StrEnum):
    MOVE = "move"
    ATTACK_MELEE = "attack_melee"
    ATTACK_RANGED = "attack_ranged"
    WAIT = "wait"
    DEFEND = "defend"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CreatureTemplate:
    name: str
    attack: int
    defense: int
    min_damage: int
    max_damage: int
    health: int
    speed: int
    initiative: int
    shots: int = 0
    abilities: frozenset[Ability] = frozenset()

    @property
    def is_ranged(self) -> bool:
        return self.shots > 0 or Ability.LIMITED_SHOTS in self.abilities


@dataclass(frozen=True, slots=True)
class StackSnapshot:
    stack_id: str
    owner: int
    creature_name: str
    count: int
    current_hp: int
    position: tuple[int, int] | None
    defended: bool
    retaliated_round: int
    waited_round: int | None
    shots_remaining: int
    alive: bool


@dataclass(frozen=True, slots=True)
class BattleAction:
    action_type: ActionType
    actor_id: str
    target_id: str | None = None
    target_pos: HexCoord | None = None
    attack_from: HexCoord | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "target_pos": None if self.target_pos is None else {"q": self.target_pos.q, "r": self.target_pos.r},
            "attack_from": None
            if self.attack_from is None
            else {"q": self.attack_from.q, "r": self.attack_from.r},
        }

    def stable_key(self) -> tuple[Any, ...]:
        target_pos = (-1, -1) if self.target_pos is None else (self.target_pos.q, self.target_pos.r)
        attack_from = (-1, -1) if self.attack_from is None else (self.attack_from.q, self.attack_from.r)
        return (self.action_type.value, self.actor_id, self.target_id or "", target_pos, attack_from)


@dataclass(slots=True)
class ArmyStack:
    stack_id: str
    owner: int
    template: CreatureTemplate
    count: int
    current_hp: int
    position: HexCoord | None
    defended: bool = False
    retaliated_round: int = 0
    waited_round: int | None = None
    shots_remaining: int = 0

    @classmethod
    def from_template(
        cls,
        stack_id: str,
        owner: int,
        template: CreatureTemplate,
        count: int,
        position: HexCoord,
    ) -> "ArmyStack":
        shots_remaining = template.shots if template.is_ranged else 0
        return cls(
            stack_id=stack_id,
            owner=owner,
            template=template,
            count=count,
            current_hp=template.health,
            position=position,
            shots_remaining=shots_remaining,
        )

    @property
    def alive(self) -> bool:
        return self.count > 0 and self.position is not None

    def snapshot(self) -> StackSnapshot:
        return StackSnapshot(
            stack_id=self.stack_id,
            owner=self.owner,
            creature_name=self.template.name,
            count=self.count,
            current_hp=self.current_hp,
            position=None if self.position is None else (self.position.q, self.position.r),
            defended=self.defended,
            retaliated_round=self.retaliated_round,
            waited_round=self.waited_round,
            shots_remaining=self.shots_remaining,
            alive=self.alive,
        )

    def total_health(self) -> int:
        if not self.alive:
            return 0
        return (self.count - 1) * self.template.health + self.current_hp

    def apply_damage(self, damage: int) -> tuple[int, int]:
        if not self.alive or damage <= 0:
            return (0, 0)

        total_before = self.total_health()
        total_after = max(0, total_before - damage)
        units_before = self.count
        if total_after == 0:
            self.count = 0
            self.current_hp = 0
            self.position = None
            return (min(damage, total_before), units_before)

        full_units, rem = divmod(total_after, self.template.health)
        self.count = full_units + (1 if rem else 0)
        self.current_hp = rem if rem else self.template.health
        return (total_before - total_after, units_before - self.count)

    def estimated_average_damage(self) -> int:
        base = (self.template.min_damage + self.template.max_damage) / 2
        return max(1, int(round(base * self.count)))


@dataclass(frozen=True, slots=True)
class Battlefield:
    width: int
    height: int
    round_limit: int = 50
    walls: frozenset[HexCoord] = field(default_factory=frozenset)
    rocks: frozenset[HexCoord] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class BattleSummary:
    winner: int | None
    rounds_completed: int
    turns_taken: int
    outcome: str
    survivors: dict[int, list[StackSnapshot]]


@dataclass(slots=True)
class BattleState:
    battlefield: Battlefield
    stacks: dict[str, ArmyStack]
    round_number: int = 1
    turns_taken: int = 0
    pending_order: list[str] = field(default_factory=list)
    waiting_order: list[str] = field(default_factory=list)
    active_stack_id: str | None = None
    log_index: int = 0

    def living_stack_ids(self, owner: int | None = None) -> list[str]:
        stack_ids = [
            stack_id
            for stack_id, stack in self.stacks.items()
            if stack.alive and (owner is None or stack.owner == owner)
        ]
        return sorted(stack_ids)

    def occupied_hexes(self, *, exclude_stack_id: str | None = None) -> set[HexCoord]:
        return {
            stack.position
            for stack_id, stack in self.stacks.items()
            if stack.alive and stack.position is not None and stack_id != exclude_stack_id
        }

    def stack_snapshots(self) -> dict[str, StackSnapshot]:
        return {stack_id: stack.snapshot() for stack_id, stack in self.stacks.items()}

    def is_finished(self) -> bool:
        owners_alive = {self.stacks[stack_id].owner for stack_id in self.living_stack_ids()}
        return len(owners_alive) <= 1 or self.round_number > self.battlefield.round_limit

    def winner(self) -> int | None:
        owners_alive = {self.stacks[stack_id].owner for stack_id in self.living_stack_ids()}
        if len(owners_alive) == 1:
            return next(iter(owners_alive))
        return None

    def summary(self) -> BattleSummary:
        winner = self.winner()
        outcome = "draw"
        if winner is not None:
            outcome = f"player_{winner}_win"
        elif self.round_number > self.battlefield.round_limit:
            outcome = "round_limit"
        survivors = {
            owner: [self.stacks[stack_id].snapshot() for stack_id in self.living_stack_ids(owner)]
            for owner in (1, 2)
        }
        return BattleSummary(
            winner=winner,
            rounds_completed=min(self.round_number, self.battlefield.round_limit),
            turns_taken=self.turns_taken,
            outcome=outcome,
            survivors=survivors,
        )
