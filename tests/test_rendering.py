from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sim_matter.hexgrid import HexCoord
from sim_matter.models import ArmyStack, Battlefield, BattleState, CreatureTemplate
from sim_matter.rendering import render_ascii_board


class RenderingTests(unittest.TestCase):
    def test_ascii_board_renders_stacks_and_legend(self) -> None:
        template = CreatureTemplate(
            name="griffin",
            attack=8,
            defense=8,
            min_damage=3,
            max_damage=6,
            health=25,
            speed=6,
            initiative=9,
        )
        state = BattleState(
            battlefield=Battlefield(width=4, height=3),
            stacks={
                "p1_griffins": ArmyStack.from_template("p1_griffins", 1, template, 5, HexCoord(1, 1)),
                "p2_griffins": ArmyStack.from_template("p2_griffins", 2, template, 4, HexCoord(3, 0)),
            },
        )

        frame = render_ascii_board(state, "=== ASCII BOARD: TEST ===").render()
        self.assertIn("=== ASCII BOARD: TEST ===", frame)
        self.assertIn("1G", frame)
        self.assertIn("2G", frame)
        self.assertIn("Legend:", frame)
        self.assertIn("p1_griffins", frame)


if __name__ == "__main__":
    unittest.main()
