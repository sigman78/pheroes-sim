from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.hexgrid import HexCoord, hex_line_of_sight, reachable_hexes


class HexGridTests(unittest.TestCase):
    def test_distance(self) -> None:
        self.assertEqual(HexCoord(0, 0).distance_to(HexCoord(2, 0)), 2)
        self.assertEqual(HexCoord(1, 1).distance_to(HexCoord(2, 3)), 3)

    def test_reachable_without_flying(self) -> None:
        start = HexCoord(1, 1)
        blocked = {HexCoord(2, 1)}
        reachable = reachable_hexes(start, width=5, height=5, move_range=2, blocked=blocked)
        self.assertIn(HexCoord(1, 3), reachable)
        self.assertNotIn(HexCoord(2, 1), reachable)

    def test_reachable_with_flying(self) -> None:
        start = HexCoord(1, 1)
        blocked = {HexCoord(2, 1)}
        reachable = reachable_hexes(start, width=5, height=5, move_range=2, blocked=blocked, flying=True)
        self.assertIn(HexCoord(3, 1), reachable)
        self.assertNotIn(HexCoord(2, 1), reachable)


class LineOfSightTests(unittest.TestCase):
    def test_los_clear_path(self) -> None:
        origin = HexCoord(0, 0)
        target = HexCoord(4, 0)
        walls: frozenset[HexCoord] = frozenset()
        self.assertTrue(hex_line_of_sight(origin, target, walls, width=8, height=6))

    def test_los_same_hex(self) -> None:
        h = HexCoord(2, 2)
        self.assertTrue(hex_line_of_sight(h, h, frozenset(), width=8, height=6))

    def test_los_wall_on_path(self) -> None:
        origin = HexCoord(0, 0)
        target = HexCoord(4, 0)
        walls: frozenset[HexCoord] = frozenset({HexCoord(2, 0)})
        self.assertFalse(hex_line_of_sight(origin, target, walls, width=8, height=6))

    def test_los_wall_adjacent_but_not_on_path(self) -> None:
        # Wall is beside the line, not on it
        origin = HexCoord(0, 0)
        target = HexCoord(4, 0)
        walls: frozenset[HexCoord] = frozenset({HexCoord(2, 1)})
        self.assertTrue(hex_line_of_sight(origin, target, walls, width=8, height=6))

    def test_los_wall_at_target_not_blocking(self) -> None:
        # Target hex itself is a wall: LoS checks intermediate hexes only
        origin = HexCoord(0, 0)
        target = HexCoord(4, 0)
        walls: frozenset[HexCoord] = frozenset({HexCoord(4, 0)})
        # No intermediate hex is blocked -> still returns True
        self.assertTrue(hex_line_of_sight(origin, target, walls, width=8, height=6))

    def test_los_wall_near_origin_blocks(self) -> None:
        origin = HexCoord(0, 2)
        target = HexCoord(6, 2)
        walls: frozenset[HexCoord] = frozenset({HexCoord(1, 2)})
        self.assertFalse(hex_line_of_sight(origin, target, walls, width=8, height=6))


if __name__ == "__main__":
    unittest.main()
