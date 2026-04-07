from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_cli_run_generates_log(self) -> None:
        tmpdir = ROOT / ".tmp-tests"
        tmpdir.mkdir(exist_ok=True)
        log_path = tmpdir / "battle.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "run",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--p1",
                "weighted_a",
                "--p2",
                "weighted_b",
                "--log",
                str(log_path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        payload = json.loads(result.stdout)
        self.assertIn(payload["outcome"], {"player_1_win", "player_2_win", "draw", "round_limit"})
        self.assertTrue(log_path.exists())
        self.assertGreater(len(log_path.read_text(encoding="utf-8").strip().splitlines()), 3)

    def test_cli_run_with_stats_and_ascii_output(self) -> None:
        tmpdir = ROOT / ".tmp-tests"
        tmpdir.mkdir(exist_ok=True)
        log_path = tmpdir / "battle-ascii.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "run",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--p1",
                "weighted_a",
                "--p2",
                "weighted_b",
                "--log",
                str(log_path),
                "--stats",
                "--board",
                "start",
                "--board",
                "end",
                "--board",
                "turn",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertNotIn("simulation_stats", payload)
        self.assertIn("Simulation stats:", result.stdout)
        self.assertIn("turns_per_second=", result.stdout)
        self.assertIn("=== ASCII BOARD: START ===", result.stdout)
        self.assertIn("=== ASCII BOARD: END ===", result.stdout)
        self.assertIn("=== ASCII BOARD: TURN", result.stdout)
        self.assertNotIn("ASCII BOARD", log_path.read_text(encoding="utf-8"))

    def test_cli_batch_outputs_summary_json(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "batch",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--p1",
                "weighted_a",
                "--p2",
                "weighted_b",
                "--num-sims",
                "6",
                "--seed",
                "123",
                "--stats",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertEqual(payload["num_sims"], 6)
        self.assertEqual(payload["side_swap_policy"], "alternate_sides_each_sim")
        self.assertEqual(payload["batch_seed"], 123)
        self.assertIn("strategy_a", payload["strategies"])
        self.assertIn("strategy_b", payload["strategies"])
        self.assertEqual(
            payload["strategies"]["strategy_a"]["wins"]
            + payload["strategies"]["strategy_a"]["losses"]
            + payload["strategies"]["strategy_a"]["draws"],
            6,
        )
        self.assertIn("as_owner1", payload["strategies"]["strategy_a"])
        self.assertIn("as_owner2", payload["strategies"]["strategy_a"])
        self.assertIn("Batch summary:", result.stdout)
        self.assertIn("Batch stats:", result.stdout)
        self.assertNotIn("ASCII BOARD", result.stdout)

    def test_cli_batch_scenario_set_outputs_per_scenario_summary(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "batch",
                "--scenario-set",
                str(ROOT / "examples" / "scenario_sets" / "core"),
                "--p1",
                "weighted_a",
                "--p2",
                "weighted_b",
                "--num-sims",
                "10",
                "--seed",
                "321",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertEqual(payload["scenario_source"], "scenario_set")
        self.assertEqual(payload["scenario_count"], 10)
        self.assertEqual(len(payload["scenario_ids"]), 10)
        self.assertIn("per_scenario", payload)
        self.assertGreaterEqual(len(payload["per_scenario"]), 1)
        first_key = next(iter(payload["per_scenario"]))
        self.assertIn("strategy_a", payload["per_scenario"][first_key])
        self.assertIn("strategy_b", payload["per_scenario"][first_key])
        self.assertIn("Scenario ", result.stdout)


class BenchmarkCliTests(unittest.TestCase):
    def _run(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "benchmark",
                "--challenger",
                "weighted_a",
                "--pool",
                "weighted_b",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--num-sims",
                "4",
                "--seed",
                "42",
                *extra_args,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_benchmark_metric_only_outputs_single_float(self) -> None:
        result = self._run("--metric-only")
        self.assertEqual(result.returncode, 0)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        float(lines[0])  # must parse without error

    def test_benchmark_metric_only_stats_to_stderr(self) -> None:
        result = self._run("--metric-only", "--stats")
        self.assertEqual(result.returncode, 0)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)  # stdout still just the float
        float(lines[0])
        self.assertIn("elapsed", result.stderr)

    def test_benchmark_default_output_is_json(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["challenger"], "weighted_a")
        self.assertIn("metric_value", payload)
        self.assertIn("matchups", payload)
        self.assertIn("elo_ratings", payload)
        self.assertIn("pool", payload)

    def test_benchmark_elo_metric_returns_float(self) -> None:
        result = self._run("--metric", "elo", "--metric-only")
        self.assertEqual(result.returncode, 0)
        value = float(result.stdout.strip())
        self.assertIsInstance(value, float)

    def test_benchmark_reward_metric_returns_float(self) -> None:
        result = self._run("--metric", "reward", "--metric-only")
        self.assertEqual(result.returncode, 0)
        float(result.stdout.strip())

    def test_benchmark_pool_explicit_single_opponent(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["pool"], ["weighted_b"])
        self.assertEqual(len(payload["matchups"]), 1)

    def test_benchmark_unknown_challenger_fails(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable, "-m", "pheroes_sim.cli", "benchmark",
                "--challenger", "nonexistent",
                "--scenario", str(ROOT / "examples" / "scenario_basic.json"),
                "--num-sims", "2", "--seed", "0",
            ],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_benchmark_seed_determinism(self) -> None:
        r1 = self._run("--metric-only")
        r2 = self._run("--metric-only")
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_benchmark_scenario_set(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable, "-m", "pheroes_sim.cli", "benchmark",
                "--challenger", "weighted_a",
                "--pool", "weighted_b",
                "--scenario-set", str(ROOT / "examples" / "scenario_sets" / "core"),
                "--num-sims", "4", "--seed", "7",
            ],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIn("metric_value", payload)


class TournamentCliTests(unittest.TestCase):
    def _run(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pheroes_sim.cli",
                "tournament",
                "--strategies",
                "weighted_a",
                "weighted_b",
                "random",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--num-sims",
                "4",
                "--seed",
                "42",
                *extra_args,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_tournament_three_strategies_json(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["standings"]), 3)

    def test_tournament_win_matrix_complete(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        strategies = payload["strategies"]
        for sid in strategies:
            for opp in strategies:
                if sid != opp:
                    self.assertIn(opp, payload["win_matrix"][sid])

    def test_tournament_standings_sorted_by_elo(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        elos = [s["elo"] for s in payload["standings"]]
        self.assertEqual(elos, sorted(elos, reverse=True))

    def test_tournament_elo_ratings_all_strategies(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        for sid in payload["strategies"]:
            self.assertIn(sid, payload["elo_ratings"])

    def test_tournament_seed_determinism(self) -> None:
        r1 = self._run()
        r2 = self._run()
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_tournament_requires_two_strategies(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable, "-m", "pheroes_sim.cli", "tournament",
                "--strategies", "weighted_a",
                "--scenario", str(ROOT / "examples" / "scenario_basic.json"),
                "--num-sims", "2", "--seed", "0",
            ],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_tournament_win_matrix_symmetric_sum(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        matrix = payload["win_matrix"]
        strategies = payload["strategies"]
        for i, a in enumerate(strategies):
            for b in strategies[i + 1:]:
                m_ab = matrix[a][b]
                m_ba = matrix[b][a]
                self.assertEqual(m_ab["challenger_wins"], m_ba["challenger_losses"])
                self.assertEqual(m_ab["challenger_losses"], m_ba["challenger_wins"])
                self.assertEqual(m_ab["draws"], m_ba["draws"])

    def test_tournament_num_sims_per_pair_in_output(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["num_sims_per_pair"], 4)


if __name__ == "__main__":
    unittest.main()
