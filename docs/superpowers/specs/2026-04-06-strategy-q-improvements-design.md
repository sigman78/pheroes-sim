# strategy_q Improvements — Design Spec

**Date:** 2026-04-06  
**Status:** Implemented

## Problem

Strategy-q reached ~60% H2H win rate vs weighted strategies after parameter tuning (Config K). Code inspection identified five structural gaps vs `WeightedHeuristicStrategy` that prevent further improvement through params alone.

## Gaps Addressed

| # | Gap | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | Ranged threat missing | `_build_threat_map` uses only `reachable_hexes(speed)` | Add ranged pass marking all hexes within `ranged_effective_range` |
| 2 | No approach signal | All MOVE actions score ≈ identically | Add `approach_s = distance_before − distance_after` for MOVE |
| 3 | No retaliation risk | Melee vs dangerous enemies not penalized | Add `retl_s = target.dmg / actor.hp` for ATTACK_MELEE |
| 4 | No move cost | Long-approach attacks not discounted | Add `move_cost_s = distance(actor_pos, attack_from)` |
| 5 | Math artifact | `negative_raw × preserve_s` reverses sign | Apply preserve only when `raw >= 0` |

## Design (Option A — Flat raw score extension)

No new classes. New signals are added as additive terms to `raw` in `_score_action`.

### New helper: `_find_best_target_pos`

Returns position of the enemy with highest kill potential (`actor.dmg / target.hp`). Used to anchor approach signal without requiring a full target scan per action.

### Extended `_build_threat_map`

Second pass after the movement-range loop: for each ranged enemy with shots remaining, mark all battlefield hexes within `ranged_effective_range` with `enemy.dmg × ranged_threat_scale`. This corrects the blind spot for ranged enemies beyond their movement range.

### Updated score formula

```
raw = action_bias
    + kill_s      × effective_w_kill
    + role_s      × effective_w_role
    + approach_s  × w_approach        # MOVE only
    - retl_s      × w_retaliation     # ATTACK_MELEE only
    - move_cost_s × w_move_cost       # when attack_from set

score = raw × preserve_s   if raw >= 0
        raw                otherwise
```

### New DEFAULT_PARAMS

| Key | Default | Purpose |
|-----|---------|---------|
| `w_approach` | 1.0 | Weight for distance-closed signal on MOVE |
| `w_retaliation` | 1.5 | Penalty weight for expected enemy retaliation |
| `w_move_cost` | 0.3 | Penalty per hex of approach to attack_from |
| `ranged_threat_scale` | 0.7 | Fraction of enemy damage applied as ranged threat |
| `ranged_effective_range` | 8.0 | Max hex distance for ranged threat spread |

## Files Changed

- `src/pheroes_sim/strategies/strategy_q.py` — added `_find_best_target_pos`, extended `_build_threat_map`, updated `_score_action` formula, added 5 params to `DEFAULT_PARAMS`
- `tests/test_strategy_q.py` — added 5 behavioral tests covering each new signal

## Verification

```bash
uv run python -m unittest discover -s tests -v   # 85 tests, all pass
```

Post-implementation: re-tune the 5 new params via `benchmark --metric-only` to find optimal values.
