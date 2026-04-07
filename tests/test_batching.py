from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pheroes_sim.batching import EloRatings, expected_score, normal_approximation_ci, update_elo


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


class EloTests(unittest.TestCase):
    def test_expected_score_equal_ratings_is_half(self) -> None:
        self.assertAlmostEqual(expected_score(1000.0, 1000.0), 0.5)

    def test_expected_score_symmetry(self) -> None:
        a, b = 1200.0, 1000.0
        self.assertAlmostEqual(expected_score(a, b) + expected_score(b, a), 1.0)

    def test_expected_score_higher_rated_favoured(self) -> None:
        self.assertGreater(expected_score(1200.0, 1000.0), 0.5)
        self.assertLess(expected_score(1000.0, 1200.0), 0.5)

    def test_update_elo_win_gains_rating(self) -> None:
        ratings = EloRatings(["a", "b"])
        update_elo(ratings, "a", "b")
        self.assertGreater(ratings.ratings["a"], 1000.0)
        self.assertLess(ratings.ratings["b"], 1000.0)

    def test_update_elo_sum_conserved(self) -> None:
        ratings = EloRatings(["a", "b"])
        update_elo(ratings, "a", "b")
        self.assertAlmostEqual(ratings.ratings["a"] + ratings.ratings["b"], 2000.0)

    def test_update_elo_equal_ratings_win_gains_16(self) -> None:
        ratings = EloRatings(["a", "b"])
        update_elo(ratings, "a", "b", k=32.0)
        self.assertAlmostEqual(ratings.ratings["a"], 1016.0)
        self.assertAlmostEqual(ratings.ratings["b"], 984.0)

    def test_update_elo_draw_equal_ratings_no_change(self) -> None:
        ratings = EloRatings(["a", "b"])
        update_elo(ratings, "a", "b", draw=True)
        self.assertAlmostEqual(ratings.ratings["a"], 1000.0)
        self.assertAlmostEqual(ratings.ratings["b"], 1000.0)

    def test_update_elo_higher_rated_draw_loses_rating(self) -> None:
        ratings = EloRatings(["a", "b"])
        ratings.ratings["a"] = 1200.0
        ratings.ratings["b"] = 1000.0
        update_elo(ratings, "a", "b", draw=True)
        self.assertLess(ratings.ratings["a"], 1200.0)
        self.assertGreater(ratings.ratings["b"], 1000.0)

    def test_elo_ratings_initialised_correctly(self) -> None:
        ratings = EloRatings(["x", "y", "z"], initial=1500.0)
        self.assertEqual(ratings.ratings, {"x": 1500.0, "y": 1500.0, "z": 1500.0})

    def test_elo_ratings_empty(self) -> None:
        ratings = EloRatings([])
        self.assertEqual(ratings.ratings, {})


if __name__ == "__main__":
    unittest.main()
