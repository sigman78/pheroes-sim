# pheroes-sim

`pheroes-sim` is a `uv`-managed Python library and CLI for deterministic, simulation-friendly tactical battles on a hex grid.

## Scope

- Battle-only simulator
- Army stacks with curated abilities
- Pluggable player strategies
- Dense reward tracking
- Structured JSONL decision and action logs

## CLI

```bash
uv run pheroes-sim run \
  --scenario examples/scenario_basic.json \
  --player1-ai examples/player1_ai.json \
  --player2-ai examples/player2_ai.json \
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
