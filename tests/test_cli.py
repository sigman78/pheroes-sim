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
                "sim_matter.cli",
                "run",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--player1-ai",
                str(ROOT / "examples" / "player1_ai.json"),
                "--player2-ai",
                str(ROOT / "examples" / "player2_ai.json"),
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
                "sim_matter.cli",
                "run",
                "--scenario",
                str(ROOT / "examples" / "scenario_basic.json"),
                "--player1-ai",
                str(ROOT / "examples" / "player1_ai.json"),
                "--player2-ai",
                str(ROOT / "examples" / "player2_ai.json"),
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


if __name__ == "__main__":
    unittest.main()
