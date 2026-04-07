from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
import random
from time import perf_counter

from .batching import (
    EloRatings,
    MatchupStats,
    PlayerBatchStats,
    SideSplitStats,
    StrategyStandings,
    expected_score,
    normal_approximation_ci,
    update_elo,
)
from .engine import BattleSimulator
from .io import JsonlLogger, list_scenario_files, load_json, load_reward_tracker, load_scenario, load_strategy
from .rendering import render_ascii_board
from .strategies import list_available_strategy_ids


@dataclass
class _SimResult:
    winner_strategy: str | None  # strategy_a_id, strategy_b_id, or None (draw)
    reward_a: float
    reward_b: float


def _resolve_scenarios(args: argparse.Namespace) -> list[Path]:
    if getattr(args, "scenario", None):
        return [Path(args.scenario)]
    return list_scenario_files(args.scenario_set)


def _run_matchup(
    strategy_a_id: str,
    strategy_b_id: str,
    scenarios: list[Path],
    num_sims: int,
    base_seed: int,
    reward_config_path: str | None,
    *,
    sim_index_offset: int = 0,
) -> list[_SimResult]:
    results: list[_SimResult] = []
    for i in range(num_sims):
        swapped = i % 2 == 1
        scenario_path = scenarios[(sim_index_offset + i) % len(scenarios)]
        sim_seed = _derive_simulation_seed(base_seed, sim_index_offset + i)
        seed_a = _derive_strategy_seed(sim_seed, 11)
        seed_b = _derive_strategy_seed(sim_seed, 29)
        owner_to_strategy = {1: strategy_b_id, 2: strategy_a_id} if swapped else {1: strategy_a_id, 2: strategy_b_id}
        simulator = _create_simulator(
            scenario_path=str(scenario_path),
            owner_to_strategy_id={
                1: owner_to_strategy[1],
                2: owner_to_strategy[2],
            },
            owner_to_seed={
                1: seed_a if owner_to_strategy[1] == strategy_a_id else seed_b,
                2: seed_a if owner_to_strategy[2] == strategy_a_id else seed_b,
            },
            reward_config_path=reward_config_path,
            simulation_seed=sim_seed,
        )
        summary, rewards = simulator.run()
        # map owner → strategy name
        owner_to_name = {v: k for k, v in owner_to_strategy.items()}
        reward_a = rewards[owner_to_name[strategy_a_id]]
        reward_b = rewards[owner_to_name[strategy_b_id]]
        if summary.winner is None:
            winner_strategy = None
        else:
            winner_strategy = owner_to_strategy[summary.winner]
        results.append(_SimResult(winner_strategy=winner_strategy, reward_a=reward_a, reward_b=reward_b))
    return results


def _build_matchup_stats(
    challenger_id: str,
    opponent_id: str,
    results: list[_SimResult],
) -> MatchupStats:
    wins = sum(1 for r in results if r.winner_strategy == challenger_id)
    losses = sum(1 for r in results if r.winner_strategy == opponent_id)
    draws = sum(1 for r in results if r.winner_strategy is None)
    n = len(results)
    return MatchupStats(
        challenger=challenger_id,
        opponent=opponent_id,
        num_sims=n,
        challenger_wins=wins,
        challenger_losses=losses,
        draws=draws,
        challenger_win_rate=wins / n if n > 0 else 0.0,
        challenger_mean_reward=sum(r.reward_a for r in results) / n if n > 0 else 0.0,
        opponent_mean_reward=sum(r.reward_b for r in results) / n if n > 0 else 0.0,
    )


def _matchup_stats_to_dict(m: MatchupStats) -> dict[str, object]:
    return {
        "challenger": m.challenger,
        "opponent": m.opponent,
        "num_sims": m.num_sims,
        "challenger_wins": m.challenger_wins,
        "challenger_losses": m.challenger_losses,
        "draws": m.draws,
        "challenger_win_rate": round(m.challenger_win_rate, 6),
        "challenger_mean_reward": round(m.challenger_mean_reward, 6),
        "opponent_mean_reward": round(m.opponent_mean_reward, 6),
    }


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

    bench_parser = subparsers.add_parser("benchmark", help="Evaluate a strategy against a reference pool")
    bench_parser.add_argument("--challenger", required=True, help="Strategy ID to evaluate")
    bench_parser.add_argument("--pool", nargs="+", default=None, help="Reference strategy IDs (default: all except challenger)")
    bench_scenarios = bench_parser.add_mutually_exclusive_group(required=True)
    bench_scenarios.add_argument("--scenario", help="Path to scenario JSON")
    bench_scenarios.add_argument("--scenario-set", help="Directory containing scenario JSON files")
    bench_parser.add_argument("--num-sims", type=int, default=100, help="Simulations per pool matchup")
    bench_parser.add_argument("--seed", type=int, default=0, help="Base seed for reproducibility")
    bench_parser.add_argument("--metric", choices=["win_rate", "reward", "elo"], default="win_rate")
    bench_parser.add_argument("--metric-only", action="store_true", help="Print only the metric float to stdout")
    bench_parser.add_argument("--stats", action="store_true", help="Print timing info")
    bench_parser.add_argument("--reward-config", help="Optional reward weights JSON")
    bench_parser.add_argument("--summary-out", help="Optional path to write summary JSON")

    tourn_parser = subparsers.add_parser("tournament", help="Round-robin tournament among N strategies")
    tourn_parser.add_argument("--strategies", nargs="+", required=True, metavar="ID", help="Strategy IDs to compete")
    tourn_scenarios = tourn_parser.add_mutually_exclusive_group(required=True)
    tourn_scenarios.add_argument("--scenario", help="Path to scenario JSON")
    tourn_scenarios.add_argument("--scenario-set", help="Directory containing scenario JSON files")
    tourn_parser.add_argument("--num-sims", type=int, default=100, help="Simulations per pair")
    tourn_parser.add_argument("--seed", type=int, default=0, help="Base seed for reproducibility")
    tourn_parser.add_argument("--stats", action="store_true", help="Print timing info")
    tourn_parser.add_argument("--ranks", action="store_true", help="Print plain-text rankings (winner first) instead of JSON")
    tourn_parser.add_argument("--reward-config", help="Optional reward weights JSON")
    tourn_parser.add_argument("--summary-out", help="Optional path to write summary JSON")

    return parser


def _add_common_simulation_args(parser: argparse.ArgumentParser) -> None:
    available = ", ".join(list_available_strategy_ids())
    parser.add_argument("--p1", required=True, help=f"Strategy id for side 1 ({available})")
    parser.add_argument("--p2", required=True, help=f"Strategy id for side 2 ({available})")
    parser.add_argument("--reward-config", help="Optional reward weights JSON")
    parser.add_argument("--summary-out", help="Optional path to write summary JSON")


def _create_simulator(
    *,
    scenario_path: str,
    owner_to_strategy_id: dict[int, str],
    owner_to_seed: dict[int, int] | None,
    reward_config_path: str | None,
    simulation_seed: int,
) -> BattleSimulator:
    state = load_scenario(scenario_path)
    return BattleSimulator(
        state=state,
        strategies={
            1: load_strategy(owner_to_strategy_id[1], seed_override=None if owner_to_seed is None else owner_to_seed[1]),
            2: load_strategy(owner_to_strategy_id[2], seed_override=None if owner_to_seed is None else owner_to_seed[2]),
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
        owner_to_strategy_id={1: args.p1, 2: args.p2},
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
        "strategy_a": args.p1,
        "strategy_b": args.p2,
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
            owner_to_strategy_id={
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
        "side_swap_policy": "alternate_sides_each_sim",
        "scenario_source": "scenario_set" if args.scenario_set else "single_scenario",
        "scenario_count": len(shuffled_scenarios),
        "scenario_ids": [path.name for path in shuffled_scenarios],
        "average_turns_per_sim": total_turns / args.num_sims,
        "strategies": {
            "strategy_a": _strategy_summary_to_dict(
                label=args.p1,
                stats=strategy_a_stats,
                owner1=strategy_a_owner1,
                owner2=strategy_a_owner2,
            ),
            "strategy_b": _strategy_summary_to_dict(
                label=args.p2,
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
        "strategy_id": label,
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


def cmd_benchmark(args: argparse.Namespace) -> int:
    started_at = perf_counter()
    challenger = args.challenger
    all_strategies = list_available_strategy_ids()
    if challenger not in all_strategies:
        print(f"error: unknown challenger strategy '{challenger}'. Available: {', '.join(all_strategies)}", file=sys.stderr)
        return 2

    pool: list[str] = args.pool if args.pool is not None else [s for s in all_strategies if s != challenger]
    if challenger in pool:
        print(f"WARNING: challenger '{challenger}' found in pool, removing it", file=sys.stderr)
        pool = [s for s in pool if s != challenger]
    unknown_pool = [s for s in pool if s not in all_strategies]
    if unknown_pool:
        print(f"error: unknown pool strategies: {', '.join(unknown_pool)}", file=sys.stderr)
        return 2
    if not pool:
        print("error: pool is empty after excluding the challenger", file=sys.stderr)
        return 2

    scenarios = _resolve_scenarios(args)
    elo = EloRatings([challenger] + pool)
    matchups: list[MatchupStats] = []

    for opp_idx, opponent in enumerate(pool):
        results = _run_matchup(
            challenger,
            opponent,
            scenarios,
            args.num_sims,
            args.seed,
            args.reward_config,
            sim_index_offset=opp_idx * args.num_sims,
        )
        for r in results:
            if r.winner_strategy == challenger:
                update_elo(elo, challenger, opponent)
            elif r.winner_strategy == opponent:
                update_elo(elo, opponent, challenger)
            else:
                update_elo(elo, challenger, opponent, draw=True)
        matchups.append(_build_matchup_stats(challenger, opponent, results))

    if args.metric == "win_rate":
        metric_value = sum(m.challenger_win_rate for m in matchups) / len(matchups)
    elif args.metric == "reward":
        metric_value = sum(m.challenger_mean_reward for m in matchups) / len(matchups)
    else:  # elo
        metric_value = elo.ratings[challenger]

    elapsed_seconds = perf_counter() - started_at

    if args.metric_only:
        print(metric_value)
        if args.stats:
            print(f"elapsed: {elapsed_seconds:.6f}s", file=sys.stderr)
        return 0

    payload: dict[str, object] = {
        "challenger": challenger,
        "pool": pool,
        "metric": args.metric,
        "metric_value": round(metric_value, 6),
        "matchups": [_matchup_stats_to_dict(m) for m in matchups],
        "elo_ratings": {k: round(v, 4) for k, v in elo.ratings.items()},
    }
    if args.stats:
        payload["elapsed"] = round(elapsed_seconds, 6)
    print(json.dumps(payload, indent=2, sort_keys=True))
    _write_summary_out(args.summary_out, payload)
    return 0


def cmd_tournament(args: argparse.Namespace) -> int:
    started_at = perf_counter()
    strategies: list[str] = args.strategies

    if len(strategies) < 2:
        print("error: tournament requires at least 2 strategies", file=sys.stderr)
        return 2
    if len(set(strategies)) != len(strategies):
        print("error: duplicate strategy IDs in --strategies", file=sys.stderr)
        return 2
    all_strategies = list_available_strategy_ids()
    unknown = [s for s in strategies if s not in all_strategies]
    if unknown:
        print(f"error: unknown strategies: {', '.join(unknown)}", file=sys.stderr)
        return 2

    scenarios = _resolve_scenarios(args)
    elo = EloRatings(strategies)
    pairs = [(strategies[i], strategies[j]) for i in range(len(strategies)) for j in range(i + 1, len(strategies))]
    win_matrix: dict[str, dict[str, MatchupStats]] = {s: {} for s in strategies}
    global_offset = 0

    for strat_a, strat_b in pairs:
        results = _run_matchup(
            strat_a,
            strat_b,
            scenarios,
            args.num_sims,
            args.seed,
            args.reward_config,
            sim_index_offset=global_offset,
        )
        global_offset += args.num_sims
        for r in results:
            if r.winner_strategy == strat_a:
                update_elo(elo, strat_a, strat_b)
            elif r.winner_strategy == strat_b:
                update_elo(elo, strat_b, strat_a)
            else:
                update_elo(elo, strat_a, strat_b, draw=True)
        win_matrix[strat_a][strat_b] = _build_matchup_stats(strat_a, strat_b, results)
        # Invert for strat_b's perspective
        m = win_matrix[strat_a][strat_b]
        win_matrix[strat_b][strat_a] = MatchupStats(
            challenger=strat_b,
            opponent=strat_a,
            num_sims=m.num_sims,
            challenger_wins=m.challenger_losses,
            challenger_losses=m.challenger_wins,
            draws=m.draws,
            challenger_win_rate=m.challenger_losses / m.num_sims if m.num_sims > 0 else 0.0,
            challenger_mean_reward=m.opponent_mean_reward,
            opponent_mean_reward=m.challenger_mean_reward,
        )

    standings: list[StrategyStandings] = []
    for sid in strategies:
        opponents = win_matrix[sid]
        total_wins = sum(m.challenger_wins for m in opponents.values())
        total_losses = sum(m.challenger_losses for m in opponents.values())
        total_draws = sum(m.draws for m in opponents.values())
        total_matches = total_wins + total_losses + total_draws
        win_rate = total_wins / total_matches if total_matches > 0 else 0.0
        mean_reward = sum(m.challenger_mean_reward for m in opponents.values()) / len(opponents) if opponents else 0.0
        standings.append(StrategyStandings(
            strategy_id=sid,
            total_wins=total_wins,
            total_losses=total_losses,
            total_draws=total_draws,
            win_rate=win_rate,
            mean_reward=mean_reward,
            elo=elo.ratings[sid],
        ))
    standings.sort(key=lambda s: s.elo, reverse=True)

    elapsed_seconds = perf_counter() - started_at

    payload: dict[str, object] = {
        "strategies": strategies,
        "num_sims_per_pair": args.num_sims,
        "win_matrix": {
            sid: {opp: _matchup_stats_to_dict(m) for opp, m in opponents.items()}
            for sid, opponents in win_matrix.items()
        },
        "standings": [
            {
                "strategy_id": s.strategy_id,
                "total_wins": s.total_wins,
                "total_losses": s.total_losses,
                "total_draws": s.total_draws,
                "win_rate": round(s.win_rate, 6),
                "mean_reward": round(s.mean_reward, 6),
                "elo": round(s.elo, 4),
            }
            for s in standings
        ],
        "elo_ratings": {k: round(v, 4) for k, v in elo.ratings.items()},
    }
    if args.stats:
        payload["elapsed"] = round(elapsed_seconds, 6)
    if getattr(args, "ranks", False):
        for s in standings:
            print(f"{s.strategy_id} {round(s.elo, 4)} {round(s.win_rate, 6)}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    _write_summary_out(args.summary_out, payload)
    return 0


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        if args.command == "run":
            return cmd_run(args)
        if args.command == "batch":
            return cmd_batch(args)
        if args.command == "benchmark":
            return cmd_benchmark(args)
        if args.command == "tournament":
            return cmd_tournament(args)
        parser.error(f"Unknown command: {args.command}")
        return 2
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
