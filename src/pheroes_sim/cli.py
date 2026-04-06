from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from time import perf_counter

from .batching import PlayerBatchStats, SideSplitStats, normal_approximation_ci
from .engine import BattleSimulator
from .io import JsonlLogger, list_scenario_files, load_json, load_reward_tracker, load_scenario, load_strategy
from .rendering import render_ascii_board


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pheroes-sim", description="Heroes-style tactical battle simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a battle simulation")
    _add_common_simulation_args(run_parser)
    run_parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    run_parser.add_argument("--log", required=True, help="Path to JSONL event log")
    run_parser.add_argument("--stats", action="store_true", help="Include simulation timing stats in the summary")
    run_parser.add_argument(
        "--board",
        action="append",
        choices=("start", "end", "turn"),
        default=[],
        help="Render ASCII board frames to stdout. Repeat for multiple phases.",
    )

    batch_parser = subparsers.add_parser("batch", help="Run repeated battle simulations")
    _add_common_simulation_args(batch_parser)
    batch_scenarios = batch_parser.add_mutually_exclusive_group(required=True)
    batch_scenarios.add_argument("--scenario", help="Path to scenario JSON")
    batch_scenarios.add_argument("--scenario-set", help="Directory containing scenario JSON files")
    batch_parser.add_argument("--num-sims", type=int, default=100, help="Number of simulations to run")
    batch_parser.add_argument("--seed", type=int, help="Batch seed used to derive per-simulation seeds")
    batch_parser.add_argument("--stats", action="store_true", help="Print batch timing and throughput stats")
    return parser


def _add_common_simulation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--player1-ai", required=True, help="Path to player 1 AI JSON")
    parser.add_argument("--player2-ai", required=True, help="Path to player 2 AI JSON")
    parser.add_argument("--reward-config", help="Optional reward weights JSON")
    parser.add_argument("--summary-out", help="Optional path to write summary JSON")


def _create_simulator(
    *,
    scenario_path: str,
    owner_to_strategy_path: dict[int, str],
    owner_to_seed: dict[int, int] | None,
    reward_config_path: str | None,
    simulation_seed: int,
) -> BattleSimulator:
    state = load_scenario(scenario_path)
    return BattleSimulator(
        state=state,
        strategies={
            1: load_strategy(owner_to_strategy_path[1], seed_override=None if owner_to_seed is None else owner_to_seed[1]),
            2: load_strategy(owner_to_strategy_path[2], seed_override=None if owner_to_seed is None else owner_to_seed[2]),
        },
        reward_tracker=load_reward_tracker(reward_config_path),
        seed=simulation_seed,
    )


def _write_summary_out(path_str: str | None, payload: dict[str, object]) -> None:
    if not path_str:
        return
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _resolve_batch_scenarios(args: argparse.Namespace) -> list[Path]:
    if args.scenario:
        return [Path(args.scenario)]
    return list_scenario_files(args.scenario_set)


def cmd_run(args: argparse.Namespace) -> int:
    scenario_data = load_json(args.scenario)
    seed = int(scenario_data.get("battle_options", {}).get("seed", 0))
    simulator = _create_simulator(
        scenario_path=args.scenario,
        owner_to_strategy_path={1: args.player1_ai, 2: args.player2_ai},
        owner_to_seed=None,
        reward_config_path=args.reward_config,
        simulation_seed=seed,
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
    _write_summary_out(args.summary_out, summary_payload)
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    started_at = perf_counter()
    total_turns = 0
    scenario_paths = _resolve_batch_scenarios(args)
    scenario_data = load_json(scenario_paths[0])
    batch_seed = args.seed if args.seed is not None else int(scenario_data.get("battle_options", {}).get("seed", 0))
    shuffled_scenarios = list(scenario_paths)
    random.Random(batch_seed).shuffle(shuffled_scenarios)
    strategies = {
        "strategy_a": args.player1_ai,
        "strategy_b": args.player2_ai,
    }
    totals = {
        "strategy_a": {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "total_reward": 0.0,
            "owner1": {"matches": 0, "wins": 0, "losses": 0, "draws": 0},
            "owner2": {"matches": 0, "wins": 0, "losses": 0, "draws": 0},
        },
        "strategy_b": {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "total_reward": 0.0,
            "owner1": {"matches": 0, "wins": 0, "losses": 0, "draws": 0},
            "owner2": {"matches": 0, "wins": 0, "losses": 0, "draws": 0},
        },
    }
    per_scenario: dict[str, dict[str, dict[str, int | float]]] = {}

    for index in range(args.num_sims):
        swapped = index % 2 == 1
        scenario_path = shuffled_scenarios[index % len(shuffled_scenarios)]
        scenario_key = scenario_path.name
        if scenario_key not in per_scenario:
            per_scenario[scenario_key] = {
                "strategy_a": {"matches": 0, "wins": 0, "losses": 0, "draws": 0, "total_reward": 0.0},
                "strategy_b": {"matches": 0, "wins": 0, "losses": 0, "draws": 0, "total_reward": 0.0},
            }
        sim_seed = _derive_simulation_seed(batch_seed, index)
        strategy_seed_a = _derive_strategy_seed(sim_seed, 11)
        strategy_seed_b = _derive_strategy_seed(sim_seed, 29)
        owner_to_strategy_name = {1: "strategy_a", 2: "strategy_b"} if not swapped else {1: "strategy_b", 2: "strategy_a"}
        simulator = _create_simulator(
            scenario_path=str(scenario_path),
            owner_to_strategy_path={
                1: strategies[owner_to_strategy_name[1]],
                2: strategies[owner_to_strategy_name[2]],
            },
            owner_to_seed={
                1: strategy_seed_a if owner_to_strategy_name[1] == "strategy_a" else strategy_seed_b,
                2: strategy_seed_a if owner_to_strategy_name[2] == "strategy_a" else strategy_seed_b,
            },
            reward_config_path=args.reward_config,
            simulation_seed=sim_seed,
        )
        summary, rewards = simulator.run()
        total_turns += summary.turns_taken

        for owner, strategy_name in owner_to_strategy_name.items():
            side_key = f"owner{owner}"
            totals[strategy_name]["total_reward"] += rewards[owner]
            totals[strategy_name][side_key]["matches"] += 1
            per_scenario[scenario_key][strategy_name]["matches"] += 1
            per_scenario[scenario_key][strategy_name]["total_reward"] += rewards[owner]

        if summary.winner is None:
            for strategy_name in ("strategy_a", "strategy_b"):
                totals[strategy_name]["draws"] += 1
                per_scenario[scenario_key][strategy_name]["draws"] += 1
            for owner, strategy_name in owner_to_strategy_name.items():
                totals[strategy_name][f"owner{owner}"]["draws"] += 1
        else:
            winner_strategy = owner_to_strategy_name[summary.winner]
            loser_owner = 1 if summary.winner == 2 else 2
            loser_strategy = owner_to_strategy_name[loser_owner]
            totals[winner_strategy]["wins"] += 1
            totals[loser_strategy]["losses"] += 1
            per_scenario[scenario_key][winner_strategy]["wins"] += 1
            per_scenario[scenario_key][loser_strategy]["losses"] += 1
            totals[winner_strategy][f"owner{summary.winner}"]["wins"] += 1
            totals[loser_strategy][f"owner{loser_owner}"]["losses"] += 1

    elapsed_seconds = perf_counter() - started_at
    strategy_a_stats = _build_player_batch_stats(totals["strategy_a"], args.num_sims)
    strategy_b_stats = _build_player_batch_stats(totals["strategy_b"], args.num_sims)
    strategy_a_owner1 = _build_side_split_stats(totals["strategy_a"]["owner1"])
    strategy_a_owner2 = _build_side_split_stats(totals["strategy_a"]["owner2"])
    strategy_b_owner1 = _build_side_split_stats(totals["strategy_b"]["owner1"])
    strategy_b_owner2 = _build_side_split_stats(totals["strategy_b"]["owner2"])

    print(
        f"Batch summary: sims={args.num_sims}, side_swap=alternate, batch_seed={batch_seed}, "
        f"scenario_count={len(shuffled_scenarios)}"
    )
    print(
        f"Strategy A: wins={strategy_a_stats.wins}, losses={strategy_a_stats.losses}, draws={strategy_a_stats.draws}, "
        f"win_rate={strategy_a_stats.win_rate:.4f}, "
        f"ci95=[{strategy_a_stats.win_rate_ci_95.lower:.4f}, {strategy_a_stats.win_rate_ci_95.upper:.4f}], "
        f"mean_reward={strategy_a_stats.mean_reward:.4f}, "
        f"as_owner1={strategy_a_owner1.win_rate:.4f}, as_owner2={strategy_a_owner2.win_rate:.4f}"
    )
    print(
        f"Strategy B: wins={strategy_b_stats.wins}, losses={strategy_b_stats.losses}, draws={strategy_b_stats.draws}, "
        f"win_rate={strategy_b_stats.win_rate:.4f}, "
        f"ci95=[{strategy_b_stats.win_rate_ci_95.lower:.4f}, {strategy_b_stats.win_rate_ci_95.upper:.4f}], "
        f"mean_reward={strategy_b_stats.mean_reward:.4f}, "
        f"as_owner1={strategy_b_owner1.win_rate:.4f}, as_owner2={strategy_b_owner2.win_rate:.4f}"
    )
    print(f"Average turns per simulation: {total_turns / args.num_sims:.4f}")
    for scenario_key in sorted(per_scenario):
        scenario_a = _build_per_scenario_stats(per_scenario[scenario_key]["strategy_a"])
        scenario_b = _build_per_scenario_stats(per_scenario[scenario_key]["strategy_b"])
        print(
            f"Scenario {scenario_key}: "
            f"A win_rate={scenario_a['win_rate']:.4f}, mean_reward={scenario_a['mean_reward']:.4f}; "
            f"B win_rate={scenario_b['win_rate']:.4f}, mean_reward={scenario_b['mean_reward']:.4f}"
        )
    if args.stats:
        turns_per_second = total_turns / elapsed_seconds if elapsed_seconds > 0 else None
        print(
            "Batch stats:"
            f" elapsed={elapsed_seconds:.6f}s"
            f", total_turns={total_turns}"
            f", turns_per_second={round(turns_per_second, 6) if turns_per_second is not None else 'n/a'}"
        )

    summary_payload = {
        "num_sims": args.num_sims,
        "batch_seed": batch_seed,
        "side_swap_policy": "alternate_players_each_sim",
        "scenario_source": "scenario_set" if args.scenario_set else "single_scenario",
        "scenario_count": len(shuffled_scenarios),
        "scenario_ids": [path.name for path in shuffled_scenarios],
        "average_turns_per_sim": total_turns / args.num_sims,
        "strategies": {
            "strategy_a": _strategy_summary_to_dict(
                label=args.player1_ai,
                stats=strategy_a_stats,
                owner1=strategy_a_owner1,
                owner2=strategy_a_owner2,
            ),
            "strategy_b": _strategy_summary_to_dict(
                label=args.player2_ai,
                stats=strategy_b_stats,
                owner1=strategy_b_owner1,
                owner2=strategy_b_owner2,
            ),
        },
        "per_scenario": {
            scenario_key: {
                "strategy_a": _build_per_scenario_stats(per_scenario[scenario_key]["strategy_a"]),
                "strategy_b": _build_per_scenario_stats(per_scenario[scenario_key]["strategy_b"]),
            }
            for scenario_key in sorted(per_scenario)
        },
    }
    if args.stats:
        summary_payload["batch_stats"] = {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "turns_per_second": round(total_turns / elapsed_seconds, 6) if elapsed_seconds > 0 else None,
        }
    print(json.dumps(summary_payload, sort_keys=True))
    _write_summary_out(args.summary_out, summary_payload)
    return 0


def _derive_simulation_seed(batch_seed: int, index: int) -> int:
    return batch_seed * 1_000_003 + index * 9_176 + 97


def _derive_strategy_seed(simulation_seed: int, offset: int) -> int:
    return simulation_seed + offset


def _build_player_batch_stats(outcomes: dict[str, object], num_sims: int) -> PlayerBatchStats:
    wins = int(outcomes["wins"])
    ci = normal_approximation_ci(wins, num_sims)
    return PlayerBatchStats(
        wins=wins,
        losses=int(outcomes["losses"]),
        draws=int(outcomes["draws"]),
        win_rate=wins / num_sims,
        win_rate_ci_95=ci,
        mean_reward=float(outcomes["total_reward"]) / num_sims,
    )


def _build_side_split_stats(outcomes: dict[str, int]) -> SideSplitStats:
    matches = outcomes["matches"]
    win_rate = outcomes["wins"] / matches if matches > 0 else 0.0
    return SideSplitStats(
        matches=matches,
        wins=outcomes["wins"],
        losses=outcomes["losses"],
        draws=outcomes["draws"],
        win_rate=win_rate,
    )


def _player_batch_stats_to_dict(stats: PlayerBatchStats) -> dict[str, object]:
    return {
        "wins": stats.wins,
        "losses": stats.losses,
        "draws": stats.draws,
        "win_rate": round(stats.win_rate, 6),
        "win_rate_ci_95": {
            "lower": round(stats.win_rate_ci_95.lower, 6),
            "upper": round(stats.win_rate_ci_95.upper, 6),
        },
        "mean_reward": round(stats.mean_reward, 6),
    }


def _side_split_to_dict(stats: SideSplitStats) -> dict[str, object]:
    return {
        "matches": stats.matches,
        "wins": stats.wins,
        "losses": stats.losses,
        "draws": stats.draws,
        "win_rate": round(stats.win_rate, 6),
    }


def _strategy_summary_to_dict(
    *,
    label: str,
    stats: PlayerBatchStats,
    owner1: SideSplitStats,
    owner2: SideSplitStats,
) -> dict[str, object]:
    return {
        "config_path": label,
        **_player_batch_stats_to_dict(stats),
        "as_owner1": _side_split_to_dict(owner1),
        "as_owner2": _side_split_to_dict(owner2),
    }


def _build_per_scenario_stats(bucket: dict[str, int | float]) -> dict[str, object]:
    matches = int(bucket["matches"])
    win_rate = (int(bucket["wins"]) / matches) if matches > 0 else 0.0
    mean_reward = (float(bucket["total_reward"]) / matches) if matches > 0 else 0.0
    return {
        "matches": matches,
        "wins": int(bucket["wins"]),
        "losses": int(bucket["losses"]),
        "draws": int(bucket["draws"]),
        "win_rate": round(win_rate, 6),
        "mean_reward": round(mean_reward, 6),
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return cmd_run(args)
    if args.command == "batch":
        return cmd_batch(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
