# Tournament Mode

## What was added

Two new CLI subcommands extend the benchmarking infrastructure beyond simple head-to-head comparison:

| Command | Purpose |
|---------|---------|
| `tournament` | Round-robin among N strategies, ELO-ranked standings + full win matrix |
| `benchmark` | Challenger vs. reference pool, outputs a single scalar quality metric |

The `benchmark` command is designed as the feedback interface for external automatic strategy-tuning tools: edit a strategy source file, call `benchmark --metric-only`, parse one float from stdout.

---

## Design decisions

### ELO over raw win rate

Win rate is opponent-specific and non-transitive: A beats B 60%, B beats C 60% — but A vs C is unknown. ELO accumulates evidence across all matches and gives a single comparable number per strategy. Both commands compute ELO per-match (not from aggregated W/L counts), which gives the rating more sensitivity.

Parameters: initial rating 1000, K=32 (standard chess K for active players).

### `--metric-only` pipes to shell

When `--metric-only` is set, `benchmark` prints nothing to stdout except the bare float. Timing info from `--stats` goes to stderr. This means the shell pattern works cleanly without any parsing:

```bash
score=$(uv run pheroes-sim benchmark \
  --challenger my_strategy \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 --seed 42 --metric-only)
```

### Available metrics

| `--metric` | Definition |
|------------|-----------|
| `win_rate` | Mean win rate across all pool matchups (default) |
| `reward` | Mean per-simulation reward across all pool matchups |
| `elo` | Challenger's ELO after competing against the pool |

### Side-swapping and seed isolation

Both commands reuse the same alternating-side logic from `batch`: odd-indexed simulations swap which strategy plays owner 1. Seeds are derived non-colliding across matchup pairs by using a global simulation index offset that increments by `num_sims` per pair.

### `_run_matchup` helper

The per-simulation loop is extracted into `_run_matchup()` (private, in `cli.py`) so both commands share the same alternating-side and seed-derivation logic. It returns a `list[_SimResult]` (one entry per simulation) that callers use for per-match ELO updates and aggregate stats.

---

## New types in `batching.py`

```python
class EloRatings:
    ratings: dict[str, float]   # strategy_id -> current ELO

def expected_score(rating_a, rating_b) -> float   # standard ELO formula

def update_elo(ratings, winner_id, loser_id, k=32, draw=False) -> None  # mutates in place

@dataclass(frozen=True)
class MatchupStats:
    challenger: str
    opponent: str
    num_sims: int
    challenger_wins: int
    challenger_losses: int
    draws: int
    challenger_win_rate: float
    challenger_mean_reward: float
    opponent_mean_reward: float

@dataclass(frozen=True)
class StrategyStandings:
    strategy_id: str
    total_wins: int
    total_losses: int
    total_draws: int
    win_rate: float
    mean_reward: float
    elo: float
```

---

## Baseline results

Tournament run: `weighted_a`, `weighted_b`, `random` — 100 sims per pair, all 10 core scenarios, seed 42.

### Standings

| Rank | Strategy | ELO | Win rate | Mean reward |
|------|----------|-----|----------|-------------|
| 1 | weighted_a | 1311 | 0.79 | +89.0 |
| 2 | weighted_b | 1167 | 0.71 | +65.8 |
| 3 | random | 522 | 0.00 | −154.8 |

### Head-to-head (win rate from row's perspective)

|  | weighted_a | weighted_b | random |
|--|-----------|-----------|--------|
| **weighted_a** | — | 0.58 | 1.00 |
| **weighted_b** | 0.42 | — | 1.00 |
| **random** | 0.00 | 0.00 | — |

`weighted_a` vs `weighted_b` is the competitive matchup (58/42 split). Both dominate `random` 100%.

### Benchmark score for `weighted_a`

```
uv run pheroes-sim benchmark \
  --challenger weighted_a \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 --seed 42 --metric win_rate --metric-only
```

Output: `0.805` (averaged across both pool opponents: 1.00 vs random, 0.61 vs weighted_b).

---

## External tuning workflow

The intended pattern for an automated optimizer:

```bash
#!/usr/bin/env bash
# The optimizer edits src/pheroes_sim/strategies/my_strategy.py,
# then calls this script and reads the exit float.

score=$(uv run pheroes-sim benchmark \
  --challenger my_strategy \
  --pool weighted_a weighted_b \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 \
  --seed 42 \
  --metric win_rate \
  --metric-only)

echo "$score"   # e.g. 0.7234 — higher is better
```

**Considerations for tuning runs:**
- Use a fixed `--seed` so the metric is comparable across iterations.
- Use `--num-sims` ≥ 50 for a stable win-rate signal (CI ≈ ±7% at 50 sims, ±5% at 100).
- Use `--metric elo` instead of `win_rate` if comparing against multiple opponents matters more than absolute win rate — ELO penalises losing to weaker opponents more than raw averaging does.
- After tuning, verify the final strategy with a full `tournament` run to see rankings.
