# strategy_q Parameter Tuning Log

Goal: beat `weighted_a` and `weighted_b` in direct head-to-head (>50% WR each).  
Method: edit `DEFAULT_PARAMS` in `strategy_q.py`, run benchmark across 5+ seeds × 100 sims, log results.

---

## Baseline

```
weighted_a 1428.48  WR 78.3%
weighted_b 1306.18  WR 74.0%
strategy_q  969.78  WR 47.2%   ← starting point
random      295.55  WR 0.5%
```

**Params (original):**
- w_melee_attack: 3.0, w_ranged_attack: 2.5, w_move: 0.5, w_wait: -1.0, w_defend: -0.3
- kill_steepness: 8.0, kill_midpoint: 0.7
- preserve_decay_rate: 3.0
- w_kill: 2.0, w_role: 1.0
- aggression_hp_threshold: 1.5, aggression_kill_multiplier: 1.4

Root cause: `preserve_decay_rate=3.0` collapses all melee attack scores to near-zero because
standing adjacent to an enemy means high threat at actor_pos, and exp(-3 × threat) ≈ 0.05.
Strategy could not effectively attack adjacent enemies.

---

## Run 1 — Lower preservation, boost kill/melee

Changed: preserve_decay_rate 3.0→0.8, w_kill 2→4, w_melee 3→4.5, w_ranged 2.5→3.5

```
weighted_a 1419.46  WR 76.7%
weighted_b 1258.08  WR 70.2%
strategy_q 1032.16  WR 52.8%   ← +5.6pp
```

Improvement confirmed; preservation was the primary blocker.

---

## Run 2 — Lower kill midpoint (reward partial damage)

Changed: kill_midpoint 0.7→0.3, kill_steepness 8→6, preserve_decay 0.8→0.5, w_kill 4→6

```
weighted_a 1366.92  WR 72.3%
weighted_b 1213.44  WR 65.7%
strategy_q 1062.64  WR 61.5%   ← +8.7pp
```

Kill midpoint at 0.7 only rewards near-wipes; lowering to 0.3 unlocks target discrimination.

---

## Run 3 — Max kill priority, more aggressive posture

Changed: kill_steepness 6→5, kill_midpoint 0.3→0.2, preserve 0.5→0.4, w_kill 6→8,
aggression_hp_threshold 1.5→1.1, aggression_kill_multiplier 1.4→1.8, kite_mult 1.5→1.2

```
weighted_a 1373.78  WR 72.0%
weighted_b 1206.51  WR 64.2%
strategy_q 1074.52  WR 63.5%
```

Closing gap to weighted_b. Diminishing returns on further lowering midpoint.

---

## Run 4 — Better move incentive + target discrimination

Changed: kill_midpoint 0.2→0.4, steepness 5→7, preserve 0.4→0.35, w_kill 8→9,
w_move 0.2→1.0, aggression_kill_mult 1.8→2.0, kite_mult 1.2→1.0

```
weighted_a 1372.14  WR 71.2%
weighted_b 1220.81  WR 64.3%
strategy_q 1054.36  WR 64.0%
```

strategy_q ≈ weighted_b. Move weight 0→1 didn't help much.

---

## Run 5 — Near-zero preservation, maximum kill weight

Changed: preserve_decay 0.35→0.08, w_kill 9→10, kill_midpoint 0.4→0.35,
w_role 0.3→0.0, kite/defensive multipliers all 1.0

Multi-seed benchmark (100 sims each):
```
seed=1:   55.0%
seed=7:   55.5%
seed=42:  57.0%
seed=123: 61.0%
seed=999: 58.5%
avg: 57.4%  min: 55.0%
```

**strategy_q now beats both weighted strategies in H2H (55.5% vs weighted_a, 55.0% vs weighted_b).**

---

## Broad sweep (Configs A–G) — exploring orthogonal axes

All tested at 5 seeds × 100 sims.

| Config | Key change | avg | min |
|--------|-----------|-----|-----|
| Baseline (pre-5) | original | 58.4% | 55.5% |
| A | sharp kill (mid=0.2, steep=12, w_kill=12) | 55.9% | 52% |
| B | high action bias (melee=8, ranged=6.5) | 58.4% | 54.5% |
| C | strong role (w_role=1.5, flanker_prio=2) | 54.2% | 52% |
| D | ultra-aggressive posture (threshold=0.8, mult=2.5) | 58.4% | 55.5% |
| E | zero preservation (decay=0.0) | 55.5% | 54% |
| F | D + sharper kill + preserve=0.15 | 58.4% | 55.5% |
| G | focus fire (mid=0.7, steep=14, w_kill=20) | 57.7% | 55% |

Observations:
- Disabling role (w_role=0) is neutral or slightly better — role signals are noisy in homogeneous armies
- Very sharp kill curve (A) hurts — kills saturate too fast, no target discrimination at mid-range
- Action bias bloat (B) adds noise without signal — all attacks equally inflated
- Zero preservation (E) removes the small safety signal, hurts vs aggressive opponents

---

## Config H — Guided special units

Key insight: role scoring helps for ARTILLERY (avoids exposure) and FLANKER (priority targeting),
but hurts if too strong (overwhelms kill signal) or disabled (loses per-role guidance).

Changed from Run 5 baseline:
- w_role: 0.0 → 2.0
- artillery_exposed_score: 0.0 → -1.5  (penalty for being adjacent to enemy)
- flanker_priority_score: 1.0 → 1.5, flanker_nonpriority: 0.5 → 0.1
- barrier_other_score: 0.3 → 0.1
- aggression_hp_threshold: 1.1 → 0.9, aggression_kill_multiplier: 2.0 → 2.5
- defensive_role_multiplier: 1.0 → 1.5
- kite_preserve_multiplier: 1.0 → 1.5

10-seed benchmark (seeds 1,7,42,123,999,17,55,200,333,500):
```
avg: 59.6%   min: 56.5%
```

---

## Config K — Best found (current)

Config H + w_kill 10→12, aggression_kill_multiplier 2.5→3.0

8-seed benchmark (seeds 1,7,42,123,999,17,55,200):
```
avg: 59.75%  min: 56.5%
```

Final tournament (200 sims, seed=42):
```
weighted_a 1362.53  WR 71.2%
weighted_b 1229.81  WR 63.5%
strategy_q 1063.74  WR 65.0%   ← beats weighted_b by 1.5pp WR
random      343.92  WR 0.3%
```

H2H benchmark (200 sims, seed=42):
```
vs weighted_a: 55.5% WR  (111W / 89L)
vs weighted_b: 55.0% WR  (110W / 90L)
```

**strategy_q beats both weighted strategies in direct head-to-head.**

---

## Code Inspection Findings

After parameter tuning converged, inspected strategy_q code against weighted strategy features.

### What weighted strategies have that strategy_q lacks

| Feature | weighted_a/b | strategy_q |
|---------|-------------|-----------|
| **distance_closed** | min dist to nearest enemy decreases by move | ✗ — moves undirected |
| **retaliation_risk** | target.avg_dmg / actor.total_hp for melee | ✗ — threat map is positional, not per-target |
| **move_cost** | actor.distance to attack_from (prefer no-move attacks) | ✗ |
| **estimated_kills** | units killed count = min(target.count, dmg/unit_hp) | approximated via kill_s logistic |
| **target_value** | attack+defense+initiative of target | ✗ |

**`distance_closed` is the most impactful missing feature.** When no attack is available, strategy_q
moves with near-random destination selection (all moves score ≈ 0.5 × preserve_s ≈ 0.5, with tiny
threat-based differentiation). The weighted strategy approaches the nearest enemy efficiently.

### Bug: threat map ignores ranged attacks

`_build_threat_map` uses `reachable_hexes(enemy.speed)` which models MOVEMENT reach only. A ranged
unit with speed=3 and range=8 generates threat only within 3 hexes (movement range), not 8 hexes
(shooting range). In shooter scenarios, positions far from ranged enemies look safe when they are not.

This explains why kite mode improvements had limited effect — the threat map can't see ranged danger.

**Fix:** Add a separate pass over ranged enemies that marks all battlefield hexes within shooting range
as threatened by that enemy's damage. Requires code change (not params-tunable).

### Math artifact: negative raw × preserve_s

For WAIT (raw ≈ -1.0) and DEFEND (raw ≈ 0.0), score = raw × preserve_s.
When raw is negative and threat increases (preserve_s < 1):
- WAIT at safe hex: -1.0 × 1.0 = -1.0
- WAIT at threatened hex: -1.0 × 0.9 = -0.9 (slightly better!)

The preservation gate REVERSES for passive actions — high-threat positions make WAIT/DEFEND look
relatively better. With decay=0.1, this effect is tiny (< 10% difference) but is a latent bug at
higher decay values.

**Fix:** Apply preservation additively for negative-raw actions, or floor preserve_s effect at 1.0
for actions with negative raw. Requires code change.

### Artillery melee always flagged as exposed

In `_role_score(ARTILLERY)`, the exposed check looks at whether any enemy is adjacent to `attack_from`.
For ATTACK_MELEE, the target is necessarily adjacent to `attack_from`, so `exposed=True` always fires
for artillery melee attacks. Artillery melee is thus always penalized by `artillery_exposed_score`.

This is actually **correct behavior** (discourages artillery from meleeing), but the semantic is misleading.
The score still favors ranged attack (safe: 4.5+kill*12+2.4) over artillery melee (5.0+kill*12-3.0)
for equal kill chances, so target selection is correct.

### Tuning ceiling

Given the missing `distance_closed` feature, strategy_q's move selection is inherently undirected in
the opening phase. The ~60% H2H win rate is likely close to the achievable ceiling with current architecture.
Improvements above this level require code changes:
1. Add enemy ranged threat to threat map
2. Add move-toward-target signal (distance_closed equivalent) to score formula
3. Fix negative-raw × preserve_s math

---

## New Params Sweep (partial — 2 seeds × 20 sims per matchup)

After implementing 5 code improvements (ranged threat, approach signal, retaliation risk, move cost,
math fix), swept new params independently against the DEFAULT_PARAMS baseline.

| Param | Values tested | Best | Note |
|-------|--------------|------|------|
| w_approach | 0.0, 0.5, 1.0, 2.0, 3.0, 5.0 | **0.5** | High values (3+) collapse WR; 0.5 marginally better than 1.0 |
| w_retaliation | 0.0, 0.5, 1.0, 1.5, 2.5, 4.0 | **0.5** | Default 1.5 is too high; lower penalty is better |
| w_move_cost | 0.0, 0.1, 0.3, 0.5, 1.0, 2.0 | **0.0** | Move cost penalty hurts — disable it |
| ranged_threat_scale | 0.0–1.5 | **0.0** | Flat 0.5131 across all values — ranged threat is neutral in core scenarios |
| ranged_effective_range | 4.0, 6.0, 8.0 (partial) | 6.0 (tentative) | Sweep incomplete |

**Key insight:** Move cost penalty is actively harmful. Ranged threat has no effect in core scenarios
(likely because the scenarios don't feature ranged-dominant compositions).

## New Params Sweep — Phase 2 (5 seeds × 50 sims per matchup)

Comprehensive re-sweep after confirming dead params. Baseline comparison:

```
Config K (no new signals):  52.3% H2H WR
Current params (pre-sweep): 55.4% H2H WR  (+3.1pp from new signals)
Config L (sweep winners):   56.5% H2H WR  (+4.2pp from Config K)
```

Phase B results (new signals, independent sweep):
```
w_approach:    best=1.0 (monotone increase 0.0→1.0, drops at 1.5+)
w_retaliation: best=2.0 (monotone increase 0.0→2.0, plateau at 2.5, drops at 3.0)
```

Phase C results (core params — no changes needed):
```
w_kill=12:           still optimal
w_role=2:            still optimal
kill_midpoint=0.3:   still optimal
preserve_decay_rate: 0.0 is best (+0.95pp vs 0.1)!
```

2D grid (w_approach × w_retaliation):
```
                 retl=0.00  retl=0.50  retl=1.00  retl=2.00  retl=2.50
appr=0.0:        0.5245     0.5260     0.5280     0.5340     0.5355
appr=0.5:        0.5405     0.5420     0.5485     0.5535     0.5530
appr=1.0:        0.5435     0.5465     0.5505     0.5605     0.5605   <- best
appr=1.5:        0.5425     0.5425     0.5455     0.5520     0.5490
```
Best: w_approach=1.0, w_retaliation=2.0 (current 2.5 is effectively tied, lowered for clarity)

H2H benchmark (Config L, 200 sims, seed=42):
```
vs weighted_a: 50.0% WR  (100W/99L/1D)  <- statistically tied
vs weighted_b: 51.0% WR  (102W/98L)
```

Weak scenarios:
- scenario_06_balanced_slow_clash: 10% WR (slow units, long approach — move selection dominant)
- scenario_10_asymmetric_flyer_edge: 10% WR (flying units — FLANKER targeting suboptimal)
- scenario_05_balanced_flyers: 30% WR

These three scenarios pull the average down; the remaining 7 show 45-75% WR.

---

## Config L — Current Best (superseded by M)

Changes from Config K:
- preserve_decay_rate: 0.1 → **0.0** (biggest gain: +0.95pp)
- w_retaliation: added at **2.0** 
- w_approach: added at **1.0**
- w_move_cost, ranged_threat_scale, ranged_effective_range: **removed** (confirmed dead weight)

5-seed H2H WR: **56.5%** (up from 52.3% Config K, +4.2pp)

---

## Bug Fix: Retaliation for NO_RETALIATION targets

Discovered: `retl_s` was computed for all melee targets including harpies (ability: `no_retaliation`).
Harpy attacks cannot trigger retaliation, so penalizing them was wrong and caused strategy_q to
prefer attacking non-harpy targets instead of the more dangerous flying units.

Fix: skip retaliation penalty when `Ability.NO_RETALIATION in target.template.abilities`.

Impact: scenario_10_asymmetric_flyer_edge: **10% → 48.5% WR** vs weighted_a (+38.5pp!).

---

## target_value Signal — sweep results

5-seed sweep for w_target_value (5 seeds × 25 sims per matchup):
```
w_target_value=0.0:  52.96%
w_target_value=0.1:  53.30%
w_target_value=0.5:  53.88%
w_target_value=0.7:  54.66%
w_target_value=1.0:  54.82%  <- best
w_target_value=1.5:  54.80%
```

Best: **w_target_value=1.0** (+1.86pp over 0.0). Plateau at 1.0-1.5.

---

## Config M — Final (current)

Changes from Config L:
- `w_target_value`: 0.0 → **1.0** (new signal: prioritize high-stat targets)
- Retaliation bug fix: skip `retl_s` for `NO_RETALIATION` targets

H2H benchmark (200 sims, seed=42):
```
vs weighted_a: 52.5% WR  (105W/95L)
vs weighted_b: 50.0% WR  (100W/100L)
```

Per-scenario vs weighted_a (200 dedicated sims each):
```
scenario_10_asymmetric_flyer_edge: 48.5% (was 10% in Config K!)
scenario_06_balanced_slow_clash:   47.0% (was 10% in Config K!)
```

Tournament (200 sims, seed=42):
```
weighted_a 1373.76  WR 70.3%
weighted_b 1222.07  WR 62.3%
strategy_q 1080.07  WR 67.0%   <- beats weighted_b by 4.7pp WR
random      324.10  WR 0.3%
```

---

## Final Parameters (Config K)

```python
DEFAULT_PARAMS = {
    "w_melee_attack": 5.0,
    "w_ranged_attack": 4.5,
    "w_move": 0.5,
    "w_wait": -2.0,
    "w_defend": -1.0,
    "kill_steepness": 8.0,
    "kill_midpoint": 0.3,
    "preserve_decay_rate": 0.1,
    "w_kill": 12.0,
    "w_role": 2.0,
    "aggression_hp_threshold": 0.9,
    "defensive_hp_threshold": 0.4,
    "kite_ranged_fraction": 0.35,
    "aggression_kill_multiplier": 3.0,
    "defensive_role_multiplier": 1.5,
    "kite_preserve_multiplier": 1.5,
    "tank_defense_above_mean_by": 1.0,
    "tank_health_pool_above_mean_by": 0.3,
    "flanker_priority_score": 1.5,
    "flanker_nonpriority_score": 0.1,
    "artillery_safe_score": 1.2,
    "artillery_exposed_score": -1.5,
    "barrier_adjacent_friendly_score": 1.0,
    "barrier_other_score": 0.1,
    "generalist_score": 0.5,
}
```
