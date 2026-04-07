# Strategy-Q Design

## 1. Overview

`strategy_q` is a tactical AI for `pheroes-sim` that augments the existing linear weighted-heuristic approach with three additional reasoning layers:

| Layer | What it does |
|-------|-------------|
| **Global posture** | Reads the whole-army HP ratio and ranged-unit fraction to decide whether to play aggressively, defensively, or as a kiting force. Applies runtime multipliers to scoring weights. |
| **Local role** | Classifies each unit as FLANKER, ARTILLERY, BARRIER, or GENERALIST based on its abilities and stats. Adds a role-fulfillment score rewarding tactically coherent behaviour. |
| **Ephemeral threat map** | Computes a danger score for every hex from all enemy units before each decision. Feeds a preservation curve that multiplicatively gates suicidal moves. |

It implements the existing `Strategy` protocol exactly — one `choose_action(state, actor_id, legal_actions) → StrategyDecision` call — so it is a drop-in replacement anywhere a strategy is accepted and is auto-discovered by the strategy loader.

All parameters (base action weights, curve shapes, posture thresholds, role scores) live in a single flat `dict[str, float]`. Nothing is hardcoded. An external optimizer can tune the entire behaviour space by editing one dict and calling `benchmark --metric-only`.

---

## 2. Parameter dictionary

### 2a. Action type base weights

| Key | Default | Description |
|-----|---------|-------------|
| `w_melee_attack` | 3.0 | Base preference for melee attack actions |
| `w_ranged_attack` | 2.5 | Base preference for ranged attack actions |
| `w_move` | 0.5 | Base preference for move actions |
| `w_wait` | −1.0 | Base preference for wait actions |
| `w_defend` | −0.3 | Base preference for defend actions |

These feed into the final score as the action-type component: if an action is a melee attack, `w_melee_attack` participates in the base before the kill/role curves are applied.

### 2b. Kill curve shape (logistic S-curve)

| Key | Default | Description |
|-----|---------|-------------|
| `kill_steepness` | 8.0 | Sharpness of the S-curve. Higher → more binary (wipe = great, partial = mediocre). Tuning range: 2–20. |
| `kill_midpoint` | 0.7 | Damage ratio at which kill score = 0.5. Higher → only reward near-wipes. Range: 0.3–1.2. |

### 2c. Preservation curve shape (exponential decay)

| Key | Default | Description |
|-----|---------|-------------|
| `preserve_decay_rate` | 3.0 | λ in `exp(−λ × threat)`. At threat = 1.0 (enemy can deal own HP in damage), score ≈ exp(−3) ≈ 0.05. Higher λ → more risk-averse. Range: 1–10. |

### 2d. Score composition weights

| Key | Default | Description |
|-----|---------|-------------|
| `w_kill` | 2.0 | Weight of kill curve in the additive sum before preservation gate. |
| `w_role` | 1.0 | Weight of role fulfillment in the additive sum. |

Final score: `(kill_score × w_kill + role_score × w_role) × preservation_score`

### 2e. Global posture thresholds

| Key | Default | Description |
|-----|---------|-------------|
| `aggression_hp_threshold` | 1.5 | `own_hp / enemy_hp` above this → AGGRESSIVE posture |
| `defensive_hp_threshold` | 0.7 | `own_hp / enemy_hp` below this → DEFENSIVE posture |
| `kite_ranged_fraction` | 0.5 | `own_ranged_hp / own_hp` above this → KITE posture (checked first) |

### 2f. Posture effect multipliers

| Key | Default | Description |
|-----|---------|-------------|
| `aggression_kill_multiplier` | 1.4 | Scales `w_kill` when posture is AGGRESSIVE. Push harder for kills. |
| `defensive_role_multiplier` | 1.5 | Scales `w_role` when posture is DEFENSIVE. Prioritise tactical positioning over raw killing. |
| `kite_preserve_multiplier` | 1.5 | Scales `preserve_decay_rate` when posture is KITE. Sharpens the safety gate. |

### 2g. Role classification thresholds

| Key | Default | Description |
|-----|---------|-------------|
| `tank_defense_above_mean_by` | 1.0 | If unit's `defense > army_mean_defense + this` → eligible for BARRIER role |
| `tank_health_pool_above_mean_by` | 0.3 | If unit's `total_health > army_mean_health_pool × (1 + this)` → eligible for BARRIER role |

### 2h. Role fulfillment scores

| Key | Default | Description |
|-----|---------|-------------|
| `flanker_priority_score` | 1.0 | FLANKER targeting highest-threat enemy |
| `flanker_nonpriority_score` | 0.5 | FLANKER targeting a non-priority enemy |
| `artillery_safe_score` | 1.0 | ARTILLERY with no adjacent enemies at destination |
| `artillery_exposed_score` | 0.0 | ARTILLERY with adjacent enemies (blocked from shooting freely) |
| `barrier_adjacent_friendly_score` | 1.0 | BARRIER adjacent to own ranged unit |
| `barrier_other_score` | 0.3 | BARRIER not adjacent to own ranged unit |
| `generalist_score` | 0.5 | GENERALIST (neutral — does not bias action ordering) |

---

## 3. Component specifications

### 3a. Ephemeral threat map

**Purpose:** Estimate, for each hex, how much damage the enemy could deal to a unit standing there on the next turn.

**Algorithm** (computed once per `choose_action()` call):
```
for each enemy stack e (alive, has position):
    enemy_reach = reachable_hexes(e.position, battlefield.width, battlefield.height,
                                  e.template.speed, occupied_hexes,
                                  flying=FLYING in e.template.abilities)
    for each hex h in enemy_reach ∪ {adjacent hexes of e.position}:
        threat_raw[h] += e.estimated_average_damage()

threat_fraction[h] = threat_raw[h] / max(1, actor.total_health())
```

The result is a `dict[HexCoord, float]` mapping each threatened hex to a fraction of the actor's HP. A value of 1.0 means standing there could cost the actor its entire stack.

**Threat lookup per action:**
- `ATTACK_MELEE` with `attack_from`: threat at `attack_from`
- `ATTACK_MELEE` without `attack_from` (already adjacent): threat at actor's current position
- `ATTACK_RANGED`: threat at actor's current position
- `MOVE`: threat at `target_pos`
- `WAIT`, `DEFEND`: threat at actor's current position

### 3b. Global posture

**Purpose:** Read the macro battle state and adjust scoring weights for the whole turn.

**Computation:**
```
own_hp         = Σ stack.total_health()  for own stacks
enemy_hp       = Σ stack.total_health()  for enemy stacks
hp_ratio       = own_hp / max(1, enemy_hp)
own_ranged_hp  = Σ stack.total_health()  for own stacks where template.is_ranged
ranged_fraction = own_ranged_hp / max(1, own_hp)

posture:
  KITE       if ranged_fraction > kite_ranged_fraction   (checked first)
  AGGRESSIVE if hp_ratio > aggression_hp_threshold
  DEFENSIVE  if hp_ratio < defensive_hp_threshold
  NEUTRAL    otherwise
```

**Effect on weights (applied at runtime, does not mutate params dict):**
```
AGGRESSIVE → effective_w_kill = w_kill × aggression_kill_multiplier
DEFENSIVE  → effective_w_role = w_role × defensive_role_multiplier
KITE       → effective_decay  = preserve_decay_rate × kite_preserve_multiplier
NEUTRAL    → no change
```

### 3c. Local role

**Purpose:** Classify each acting unit so it can be scored for tactically appropriate behaviour.

**Classification** (evaluated in priority order):
```
FLANKER   if FLYING in actor.template.abilities
ARTILLERY if actor.template.is_ranged
BARRIER   if actor.template.defense > army_mean_defense + tank_defense_above_mean_by
           OR actor.total_health() > army_mean_health_pool × (1 + tank_health_pool_above_mean_by)
GENERALIST otherwise
```

`army_mean_defense` and `army_mean_health_pool` are computed from all alive own stacks at decision time.

### 3d. Response curves

**Kill curve (logistic S-curve):**
```
x = min(actor.estimated_average_damage() / max(1, target.total_health()), 2.0)
kill_score = 1 / (1 + exp(−kill_steepness × (x − kill_midpoint)))
```

With defaults (steepness=8, midpoint=0.7):

| x (damage/target HP) | kill_score |
|---------------------|-----------|
| 0.0 (no damage) | ≈ 0.00 |
| 0.3 | ≈ 0.02 |
| 0.5 | ≈ 0.10 |
| 0.7 (midpoint) | 0.50 |
| 1.0 (full wipe) | ≈ 0.95 |
| 1.5+ (overkill) | ≈ 1.00 |

The S-shape means: doing 50% damage is mediocre, but wiping a stack is excellent — matching the actual game value (a dead stack loses its next turn).

**Preservation curve (exponential decay):**
```
preservation_score = exp(−effective_decay × threat_fraction[destination])
```

With default decay=3.0:

| threat_fraction | preservation_score |
|----------------|-------------------|
| 0.0 | 1.00 |
| 0.2 | 0.55 |
| 0.5 | 0.22 |
| 1.0 (full kill threat) | 0.05 |
| 2.0 (2× overkill) | 0.002 |

Multiplied into the final score, this makes the strategy physically unable to score a suicidal move highly, regardless of kill value.

**Role fulfillment score:** Discrete values 0.0–1.0 per role (see §2h). This is a bounded, interpretable signal: 1.0 = unit is playing its ideal role, 0.0 = unit is actively misplaying it.

### 3e. Final score composition

```
# Apply posture multipliers
effective_w_kill = w_kill × (aggression_kill_multiplier if AGGRESSIVE else 1.0)
effective_w_role = w_role × (defensive_role_multiplier  if DEFENSIVE  else 1.0)
effective_decay  = preserve_decay_rate × (kite_preserve_multiplier if KITE else 1.0)

# Compute components
action_type_bias = w_melee_attack | w_ranged_attack | w_move | w_wait | w_defend
kill_s     = kill_curve(estimated_damage / target_hp)   # 0 if no target
role_s     = role_score(role, action, state)
preserve_s = exp_decay(threat_fraction[dest], effective_decay)

# Compose
score = (action_type_bias + kill_s × effective_w_kill + role_s × effective_w_role)
        × preserve_s
```

Action type bias shifts the baseline before curves are applied, so a melee attack starts higher than a wait. Curves then re-rank within action types based on quality of the specific action.

---

## 4. Default parameters (full table)

```python
DEFAULT_PARAMS = {
    "w_melee_attack":                    3.0,
    "w_ranged_attack":                   2.5,
    "w_move":                            0.5,
    "w_wait":                           -1.0,
    "w_defend":                         -0.3,
    "kill_steepness":                    8.0,
    "kill_midpoint":                     0.7,
    "preserve_decay_rate":               3.0,
    "w_kill":                            2.0,
    "w_role":                            1.0,
    "aggression_hp_threshold":           1.5,
    "defensive_hp_threshold":            0.7,
    "kite_ranged_fraction":              0.5,
    "aggression_kill_multiplier":        1.4,
    "defensive_role_multiplier":         1.5,
    "kite_preserve_multiplier":          1.5,
    "tank_defense_above_mean_by":        1.0,
    "tank_health_pool_above_mean_by":    0.3,
    "flanker_priority_score":            1.0,
    "flanker_nonpriority_score":         0.5,
    "artillery_safe_score":              1.0,
    "artillery_exposed_score":           0.0,
    "barrier_adjacent_friendly_score":   1.0,
    "barrier_other_score":               0.3,
    "generalist_score":                  0.5,
}
```

---

## 5. Implementation checklist

- [ ] Add `src/pheroes_sim/strategies/strategy_q.py`
  - [ ] `GlobalPosture` StrEnum
  - [ ] `LocalRole` StrEnum
  - [ ] `_logistic(x, k, x0) -> float`
  - [ ] `_exp_decay(threat, lam) -> float`
  - [ ] `_build_threat_map(state, actor_id, p) -> dict[HexCoord, float]`
  - [ ] `_compute_posture(state, actor_id, p) -> GlobalPosture`
  - [ ] `_compute_role(stack, own_stacks, p) -> LocalRole`
  - [ ] `_role_score(role, action, state, actor_id, p) -> float`
  - [ ] `QStrategy.choose_action()` — assembles all components, scores, picks best
  - [ ] `DEFAULT_PARAMS` dict
  - [ ] `build_strategy(*, seed=None) -> Strategy`
- [ ] Add `tests/test_strategy_q.py` — see §6
- [ ] Run `uv run python -m unittest discover -s tests -v` — all pass

---

## 6. Verification plan

```bash
# Unit tests
uv run python -m unittest tests/test_strategy_q.py -v

# Full test suite (must remain green)
uv run python -m unittest discover -s tests -v

# Single battle smoke test
uv run pheroes-sim run \
  --scenario examples/scenario_basic.json \
  --p1 strategy_q --p2 weighted_a \
  --log /tmp/sq.jsonl --stats

# Benchmark against reference pool
uv run pheroes-sim benchmark \
  --challenger strategy_q \
  --pool weighted_a weighted_b random \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 --seed 42 --metric win_rate

# Full tournament
uv run pheroes-sim tournament \
  --strategies weighted_a weighted_b strategy_q random \
  --scenario-set examples/scenario_sets/core \
  --num-sims 100 --seed 42 --stats

# Tuning interface sanity check (output must be a single parseable float)
uv run pheroes-sim benchmark \
  --challenger strategy_q \
  --scenario-set examples/scenario_sets/core \
  --num-sims 50 --seed 42 --metric-only
```

**Expected outcomes:**
- strategy_q beats `random` reliably (>80% win rate vs random)
- strategy_q is competitive with `weighted_a` and `weighted_b` (win rate 40–65% range against either)
- tournament ELO for strategy_q > 900 (above random baseline of ~500)
- `--metric-only` outputs one bare float per run

**If strategy_q scores below random:** the preservation curve is likely too aggressive — lower `preserve_decay_rate` and check that `w_role` × `generalist_score` isn't dominating over attack scores.

---

## 7. Tuning guidance for external optimizers

The flat `DEFAULT_PARAMS` dict is the complete tuning surface. All 25 keys are continuous floats. Recommended tuning approach:

1. Fix `--seed` and `--num-sims ≥ 50` for stable signal
2. Use `benchmark --metric win_rate --metric-only` as the fitness function
3. Start by tuning the 5 most impactful params: `kill_steepness`, `kill_midpoint`, `preserve_decay_rate`, `w_kill`, `w_role`
4. Add posture multipliers and role scores in a second pass once curve shape is stable
5. Validate final params with `tournament` against the full strategy pool

Future extension: expose `DEFAULT_PARAMS` override via a JSON file flag on the strategy module, similar to `--reward-config`.
