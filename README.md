# pheroes-sim

`pheroes-sim` is a `uv`-managed Python library and CLI for deterministic, simulation-friendly tactical battles on a hex grid.

## Scope

- Battle-only simulator
- Army stacks with curated abilities
- Pluggable strategies
- Dense reward tracking
- Structured JSONL decision and action logs

## CLI

Strategies are selected by short ids from `src/pheroes_sim/strategies/`. The intended workflow is to copy a strategy module, tweak constants in the same file, save it under a new name, and compare it against a baseline from the CLI.

```bash
uv run pheroes-sim run \
  --scenario examples/scenario_basic.json \
  --p1 weighted_a \
  --p2 weighted_b \
  --log battle.jsonl \
  --stats \
  --board start \
  --board end
```

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

The project pins `uv`'s cache to `./.uv-cache` through [`[tool.uv]`](https://docs.astral.sh/uv/concepts/projects/config/).

Optional runtime flags:

- `--stats` prints human-readable elapsed seconds and turns-per-second to stdout.
- `--board start|turn|end` prints selectable ASCII board frames to stdout before the final summary JSON.

Batch runner:

```bash
uv run pheroes-sim batch \
  --scenario examples/scenario_basic.json \
  --p1 weighted_a \
  --p2 weighted_b \
  --num-sims 100 \
  --stats
```

Rotating scenario set:

```bash
uv run pheroes-sim batch \
  --scenario-set examples/scenario_sets/core \
  --p1 weighted_a \
  --p2 weighted_b \
  --num-sims 200 \
  --seed 123
```

Available built-in strategies currently include `weighted_a`, `weighted_b`, and `random`.

## Tournament

Run a round-robin among N strategies and get ELO-ranked standings:

```bash
uv run pheroes-sim tournament \
  --strategies weighted_a weighted_b random \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 \
  --seed 42 \
  --stats
```

Output is JSON with `standings` (sorted by ELO), `win_matrix` (all pairs), and `elo_ratings`.

## Benchmark

Evaluate a single strategy against a reference pool and get one quality metric — designed as the feedback signal for external automatic tuning tools:

```bash
# Full JSON report
uv run pheroes-sim benchmark \
  --challenger weighted_a \
  --pool weighted_b random \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 \
  --seed 42

# Single float for piping (--metric-only sends timing to stderr)
score=$(uv run pheroes-sim benchmark \
  --challenger my_strategy \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 --seed 42 --metric-only)
```

`--metric` accepts `win_rate` (default), `reward`, or `elo`. The `--pool` defaults to all discovered strategies except the challenger.

See `docs/tournament.md` for design notes, baseline results, and tuning workflow guidance.

## Creature Catalogs

Scenarios can reference a shared creature catalog instead of repeating the full roster inline:

```json
{
  "schema_version": 1,
  "battlefield": { "width": 8, "height": 6, "round_limit": 40 },
  "creature_catalog": "creatures/core.json",
  "creatures": {
    "heavy_harpies": {
      "extends": "harpy",
      "defense": "+2",
      "health": "125%"
    }
  }
}
```

Variant override rules:

- Numeric fields accept absolute integers such as `4`.
- Numeric fields accept deltas such as `"+2"` or `"-1"`.
- Numeric fields accept percentages such as `"50%"`, which sets the field to that percentage of the base value.
- `abilities` is a direct replacement list.
