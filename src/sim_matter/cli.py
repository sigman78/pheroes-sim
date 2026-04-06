from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from .engine import BattleSimulator
from .io import JsonlLogger, load_json, load_reward_tracker, load_scenario, load_strategy
from .rendering import render_ascii_board


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim-matter", description="Heroes-style tactical battle simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a battle simulation")
    run_parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    run_parser.add_argument("--player1-ai", required=True, help="Path to player 1 AI JSON")
    run_parser.add_argument("--player2-ai", required=True, help="Path to player 2 AI JSON")
    run_parser.add_argument("--log", required=True, help="Path to JSONL event log")
    run_parser.add_argument("--reward-config", help="Optional reward weights JSON")
    run_parser.add_argument("--summary-out", help="Optional path to write summary JSON")
    run_parser.add_argument("--stats", action="store_true", help="Include simulation timing stats in the summary")
    run_parser.add_argument(
        "--board",
        action="append",
        choices=("start", "end", "turn"),
        default=[],
        help="Render ASCII board frames to stdout. Repeat for multiple phases.",
    )
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    scenario_data = load_json(args.scenario)
    state = load_scenario(args.scenario)
    seed = int(scenario_data.get("battle_options", {}).get("seed", 0))
    simulator = BattleSimulator(
        state=state,
        strategies={1: load_strategy(args.player1_ai), 2: load_strategy(args.player2_ai)},
        reward_tracker=load_reward_tracker(args.reward_config),
        seed=seed,
    )
    logger = JsonlLogger(args.log)
    ascii_modes = set(args.board)
    rendered_frames: list[str] = []

    def observer(event_type: str, observed_state, payload: dict[str, object]) -> None:
        if event_type == "battle_started" and "start" in ascii_modes:
            rendered_frames.append(render_ascii_board(observed_state, "=== ASCII BOARD: START ===").render())
        elif event_type == "action_resolved" and "turn" in ascii_modes:
            turn = payload["turn"]
            actor_id = payload["actor_id"]
            rendered_frames.append(
                render_ascii_board(observed_state, f"=== ASCII BOARD: TURN {turn} ({actor_id}) ===").render()
            )
        elif event_type == "battle_finished" and "end" in ascii_modes:
            rendered_frames.append(render_ascii_board(observed_state, "=== ASCII BOARD: END ===").render())

    started_at = perf_counter()
    summary, rewards = simulator.run(logger=logger, observer=observer if ascii_modes else None)
    elapsed_seconds = perf_counter() - started_at

    summary_payload = {
        "winner": summary.winner,
        "outcome": summary.outcome,
        "rounds_completed": summary.rounds_completed,
        "turns_taken": summary.turns_taken,
        "reward_totals": rewards,
    }
    if args.stats:
        turns_per_second = round(summary.turns_taken / elapsed_seconds, 6) if elapsed_seconds > 0 else None
        print(
            "Simulation stats:"
            f" elapsed={elapsed_seconds:.6f}s"
            f", turns={summary.turns_taken}"
            f", turns_per_second={turns_per_second if turns_per_second is not None else 'n/a'}"
        )

    for frame in rendered_frames:
        print(frame)

    print(json.dumps(summary_payload, sort_keys=True))

    if args.summary_out:
        path = Path(args.summary_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return cmd_run(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
