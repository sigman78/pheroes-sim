from __future__ import annotations

from dataclasses import dataclass

from .hexgrid import HexCoord
from .models import BattleState


@dataclass(frozen=True, slots=True)
class BoardFrame:
    label: str
    board: str

    def render(self) -> str:
        return f"{self.label}\n{self.board}"


def render_ascii_board(state: BattleState, label: str) -> BoardFrame:
    rows: list[str] = []
    occupied = {
        (stack.position.q, stack.position.r): stack
        for stack in state.stacks.values()
        if stack.alive and stack.position is not None
    }
    legend: list[str] = []

    bf = state.battlefield
    for r in range(bf.height):
        prefix = " " if r % 2 else ""
        cells: list[str] = []
        for q in range(bf.width):
            coord = HexCoord(q, r)
            if coord in bf.walls:
                cells.append("WW")
            elif coord in bf.rocks:
                cells.append("##")
            else:
                stack = occupied.get((q, r))
                if stack is None:
                    cells.append("..")
                else:
                    cells.append(f"{stack.owner}{stack.template.name[:1].upper()}")
        rows.append(f"{prefix}{' '.join(cells)}")

    for stack_id in state.living_stack_ids():
        stack = state.stacks[stack_id]
        assert stack.position is not None
        legend.append(
            f"{stack.owner}{stack.template.name[:1].upper()}={stack.stack_id}"
            f" {stack.template.name} x{stack.count} @({stack.position.q},{stack.position.r})"
        )

    board_lines = rows + ["Legend:"] + legend
    return BoardFrame(label=label, board="\n".join(board_lines))
