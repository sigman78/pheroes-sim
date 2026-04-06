from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.batching import normal_approximation_ci


class BatchingTests(unittest.TestCase):
    def test_confidence_interval_bounds(self) -> None:
        ci = normal_approximation_ci(60, 100)
        self.assertGreaterEqual(ci.lower, 0.0)
        self.assertLessEqual(ci.upper, 1.0)
        self.assertLess(ci.lower, ci.upper)

    def test_confidence_interval_edge_zero(self) -> None:
        ci = normal_approximation_ci(0, 10)
        self.assertEqual(ci.lower, 0.0)
        self.assertGreaterEqual(ci.upper, 0.0)

    def test_confidence_interval_edge_full(self) -> None:
        ci = normal_approximation_ci(10, 10)
        self.assertLessEqual(ci.lower, 1.0)
        self.assertEqual(ci.upper, 1.0)


if __name__ == "__main__":
    unittest.main()
