# Battlefield Obstacles — Feature Results

**Date:** 2026-04-07  
**Scope:** Engine-level walls and rocks; no strategy awareness (strategy_q follow-on)

---

## Feature Summary

Two obstacle types added to the hex-grid battlefield:

| Type | Movement | Ranged LoS | Flying |
|------|----------|------------|--------|
| **Wall** (`WW`) | Blocked | Blocked | Blocked |
| **Rock** (`##`) | Blocked | Clear (shoot over) | Clear (fly over) |

### Implementation

- `Battlefield.walls` / `Battlefield.rocks` — `frozenset[HexCoord]`, default empty (fully backwards-compatible)
- `hex_line_of_sight(origin, target, walls, width, height)` — cube-coordinate lerp ray-cast in `hexgrid.py`
- Engine movement: obstacles merged into `blocked` set passed to `reachable_hexes`; flying units additionally filtered by LoS path through walls
- Engine ranged: `ATTACK_RANGED` only generated when `hex_line_of_sight` is clear
- JSON: `"walls": [[q,r], ...]` and `"rocks": [[q,r], ...]` arrays in the `"battlefield"` object
- Rendering: `WW` and `##` cells in ASCII board output

---

## New Scenarios

### scenario_11_wall_corridor (9×6)

Vertical wall column at q=4, rows 1–4. Forces ground (and flying) units through the open
top and bottom hexes, creating a chokepoint. Pure melee (pikemen only), symmetric armies.

```
Wall layout:        ....WW....
                    ....WW....
                    ....WW....
                    ....WW....
```

### scenario_12_rocks_shooters (9×6)

Four rock hexes clustered in the centre (q=3–5, r=2–3). Archers on both sides with pikemen
escort. Rocks block ground movement and push units around the centre, but archers can still
shoot over them freely.

### scenario_13_wall_los (9×7)

Horizontal wall at r=3, q=2–6. Archers deployed on opposite sides cannot shoot through the
wall; melee must navigate around the ends. Tests LoS blocking with asymmetric starting
positions.

---

## Tournament Results (all 13 scenarios, 200 sims, seed=42)

```
Strategy    ELO      WR vs others
---------   ------   ------------
weighted_a  1338.2   63.3%
weighted_b  1204.2   67.3%
strategy_q  1065.3   68.5%
random       392.3    0.7%
```

*ELO ranking reflects quality of play across all pairings; WR is each strategy's win rate
in all matches played.*

---

## Head-to-Head: strategy_q vs weighted_a (200 sims, 13 scenarios)

Overall: **strategy_q 48.5% / weighted_a 51.5%** (97 vs 103 wins, CI 95%: 41.6–55.4% — statistical tie)

### Per-scenario breakdown

| Scenario | strategy_q WR | weighted_a WR |
|----------|:---:|:---:|
| 01 balanced_line | 60.0% | 40.0% |
| 02 balanced_wide | 53.3% | 46.7% |
| 03 balanced_compact | 25.0% | 75.0% |
| 04 balanced_shooters | 33.3% | 66.7% |
| 05 balanced_flyers | 66.7% | 33.3% |
| 06 balanced_slow_clash | 33.3% | 66.7% |
| 07 balanced_mixed | 56.3% | 43.8% |
| 08 balanced_close_range | 56.3% | 43.8% |
| 09 asymmetric_shooter_edge | 46.7% | 53.3% |
| 10 asymmetric_flyer_edge | 43.8% | 56.3% |
| **11 wall_corridor** | **53.3%** | **46.7%** |
| **12 rocks_shooters** | **46.7%** | **53.3%** |
| **13 wall_los** | **56.3%** | **43.8%** |

Obstacle scenarios marked in bold.

---

## Observations

**Obstacle scenarios are competitive.** All three new scenarios produce balanced outcomes
(46–56% WR range). Neither strategy has a systematic advantage on obstacle maps, which
suggests the terrain creates interesting decisions without breaking the balance.

**Wall corridor (scenario_11):** strategy_q edges ahead (+6.6pp). The bottleneck at the
corridor openings rewards patient positioning — strategy_q's preservation and approach
signals may help avoid committing to unfavourable corridor approaches.

**Rocks shooters (scenario_12):** weighted_a slightly ahead (+6.6pp). Rocks redirect melee
traffic but don't affect ranged LoS. weighted_a's direct ranged scoring may give it a
slight edge when the shooting lanes are unobstructed.

**Wall LoS (scenario_13):** strategy_q ahead (+12.5pp). The wall forces units to flank
around the ends. strategy_q's approach and role signals (flanker priority) appear to
exploit the flanking geometry more effectively.

**Existing scenarios unaffected.** No regressions in scenarios 01–10. All 105 tests pass.

---

## Known Limitations / Follow-ons

- **Strategy obstacle-awareness:** strategies currently treat all legal actions equally
  regardless of obstacle context. A follow-on task would add obstacle signals to
  `strategy_q` (e.g., chokepoint scoring, cover bonus behind rocks).
- **No diagonal wall edge cases tested** beyond the unit tests. Complex wall shapes (e.g.
  L-shaped walls, partial corridors) may reveal LoS corner cases.
- **Scenario count hardcoded in tests:** `test_cli.py` now expects 13 scenarios; adding
  more will require updating that assertion.
