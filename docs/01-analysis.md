# Analysis: pheroes-sim

`pheroes-sim` is a deterministic hex-grid battle simulator inspired by Heroes of Might and Magic (HoMM) combat, designed for benchmarking AI strategies. This document analyses what the project does well, what is imperfect, and what could be improved — first from the game-modelling and AI-benchmarking perspective, then from the software-engineering perspective.

---

## Part 1: Game Modelling and AI Benchmarking

### What is done right

**Core combat mechanics are faithful to HoMM:**
- Axial hex coordinates with correct cubic-distance formula (`max(|dq|, |dr|, |ds|)`).
- Initiative-ordered turn queue with a wait mechanic that re-inserts the stack in initiative order — matching HoMM 3 behaviour exactly.
- Retaliation once per round per stack, correctly gated by `retaliated_round`.
- Defend action applies a 30% damage reduction for the rest of the round.
- Ranged units lose the ability to shoot freely when adjacent enemies are present (melee engagement penalty), and suffer a 50% penalty beyond distance 6.
- Flying units bypass blocked hexes for movement; BFS is only used for ground units.
- Special abilities (DOUBLE_STRIKE, NO_RETALIATION, FLYING, LIMITED_SHOTS) are correctly wired into the engine.
- Stack health model is correct: `current_hp` is the top-unit partial HP; full units below the top each carry `template.health`.

**Benchmarking infrastructure is thoughtful:**
- Alternating side assignment per simulation eliminates first-player-move bias — a common oversight in naive benchmarks.
- Separate RNG streams for engine randomness vs. strategy randomness via distinct seed derivation.
- Dense reward signal (per-turn damage/kill deltas + terminal win/loss) beyond binary W/L, useful for gradient-based approaches.
- Per-scenario win-rate breakdown allows diagnosing which map configurations favour each strategy.
- Scenario set with 10 maps covering balanced, asymmetric, flyer-heavy, and shooter-heavy compositions provides meaningful variance.
- Creature catalogue with an `extends` / override system enables low-noise variant testing without duplicating base definitions.
- JSONL decision logs record every legal action and candidate score per turn, enabling full post-hoc analysis.

---

### What is not perfect

**Damage formula has no upper cap.**
The modifier is `max(0.3, 1.0 + 0.05 * (attack - defense))`. HoMM 3 caps the upper end at 3× (attack - defense ≥ 40 gives 3×). Without an upper cap, extreme stat differentials produce unrealistic one-shot results and reduce scenario diversity.

**`LIMITED_SHOTS` ability is semantically redundant and partially broken.**
`CreatureTemplate.is_ranged` returns True if `shots > 0 OR LIMITED_SHOTS in abilities`. But `shots_remaining` is initialised from `template.shots`. A creature with `LIMITED_SHOTS` in abilities but `shots: 0` would be tagged as ranged yet unable to shoot. In the existing catalog the archer has both (`shots: 8, LIMITED_SHOTS`), which masks the bug. The ability adds no unique meaning on top of a non-zero `shots` value; either the field or the ability is redundant.

**Ranged distance threshold is a magic constant tied to nothing.**
`distance > 6` triggers the half-damage penalty. On an 8×6 board the max hex distance is ~9. On the 9×6 asymmetric scenarios the threshold is still 6. The right model is "beyond half the battlefield diagonal" or a scenario-configurable value, not a hardcoded literal.

**No terrain or obstacles.**
HoMM battlefields spawn random blocking hexes. Without them, all scenarios with similar army counts tend to converge on the same opening moves, reducing the scenario diversity the set tries to achieve.

**Battlefield is tiny and uniform.**
All scenarios use 8×6 or 9×6 grids. HoMM 3 uses 15×11. The small size means ranged units almost always operate within the half-damage threshold, making the range penalty rarely significant — which reduces the signal value of shooter-edge scenarios.

**No morale or luck.**
HoMM's morale (extra turn) and luck (double damage) are high-variance events that are an important part of the strategy space. Their absence is a reasonable simplification, but should be documented as a known gap rather than implicit.

**`estimated_average_damage` ignores the ATK/DEF differential.**
The heuristic feature `estimated_damage_ratio` divides `estimated_average_damage` (= `(min+max)/2 * count`) by target health. The estimate ignores the actual modifier `max(0.3, 1.0 + 0.05*(atk-def))`, making the ratio inaccurate for mismatched stat tiers. A melee attack against a high-defence target looks artificially attractive.

**`target_value` feature is a crude threat proxy.**
`attack + defense + initiative` is used as a priority heuristic for target selection. A griffin with count=1 scores the same as one with count=10. Count × stat-sum would better model actual threat.

**No tournament infrastructure.**
The CLI only compares two strategies head-to-head. For a benchmark with N strategies, no round-robin mode exists. Win-rate is only interpretable relative to a specific opponent, not as an absolute strength measure.

**Normal approximation CI is mislabelled.**
`normal_approximation_ci` implements the Wald interval (`p ± z√(p(1-p)/n)`), not the Wilson score interval. The difference is significant at low sample counts (< 30) or extreme win rates (< 0.1, > 0.9). The naming suggests more statistical rigour than is actually present.

---

### What could be improved

- **Add a configurable range penalty distance** (e.g., `"ranged_penalty_distance"` in the scenario's `battlefield` block) instead of the magic constant 6.
- **Cap the damage modifier** at 3.0× to match HoMM 3 and prevent degenerate results.
- **Resolve the `LIMITED_SHOTS` / `shots` redundancy**: remove the ability and rely solely on a non-zero `shots` field, or redefine `LIMITED_SHOTS` to mean "can shoot, but shots field caps ammo" with a separate unlimited-ammo behaviour.
- **Add obstacle hexes** to scenario JSON and block them in BFS reachability.
- **Scale up the default battlefield** to at least 11×9 to make range mechanics and positioning more consequential.
- **Implement Wilson CI** in `batching.py` and rename the function accordingly.
- **Add a round-robin batch mode** that accepts N strategy IDs and emits a full win-matrix.
- **Improve `estimated_average_damage`** to incorporate the attack/defense modifier so heuristic features are grounded in the actual damage model.
- **Make `target_value` count-aware**: replace `atk+def+init` with `(atk+def+init) * count` or `total_health * atk` as a proxy for threat-adjusted priority.

---

## Part 2: Software Engineering

### What is done right

**Data model is clean and appropriately typed.**
`CreatureTemplate` and `BattleAction` are `frozen=True` with `__slots__`; `ArmyStack` and `BattleState` are mutable with `__slots__`. The distinction is deliberate and correct: templates never change, state does. `StackSnapshot` provides a safe immutable copy for logging.

**`Strategy` is a structural `Protocol`.**
Any object with a conforming `choose_action` signature is a valid strategy without subclassing. This is the right abstraction for plug-in AI components and enables the `StaticStrategy` in tests without any test infrastructure boilerplate.

**Auto-discovery of strategy modules.**
`pkgutil.iter_modules` scans the `strategies/` package and builds the available-ID list from filesystem names. Adding a new strategy requires no registration step — just drop a file with `build_strategy()` in it.

**`stable_key()` on `BattleAction` for deterministic ordering and deduplication.**
Deduplication via `{action.stable_key(): action for action in actions}` is correct and reproducible regardless of insertion order. Combined with `sorted(deduped.values(), key=...)`, the legal-action list is fully deterministic given the same state.

**Scenario inheritance system is well-implemented.**
The `extends` / delta-override / percentage-override resolver in `io.py` handles cycles, missing definitions, unknown fields, and type coercion with specific error messages. This is a non-trivial piece of code done right.

**JSONL logging is append-safe and streamable.**
Each event is a self-contained JSON object. The log can be partially consumed, streamed, or cut off without corruption.

**Test suite is functional and covers meaningful paths.**
Tests exercise the engine directly (damage, double-strike, retaliation), the IO layer (catalog loading, extends resolution), the CLI (batch/run integration), and strategy loader (unknown ID, seed override). The `StaticStrategy` helper in `test_engine.py` is a clean testing pattern.

**`uv`-managed, zero-dependency project.**
No runtime dependencies. Python ≥ 3.13 is required and enforced in `pyproject.toml`. The local cache at `.uv-cache` makes the project self-contained.

---

### What is not perfect

**`pending_order.pop(0)` is O(n) per turn.**
`BattleState.pending_order` is a `list`. `_next_actor_id` calls `self.state.pending_order.pop(0)` every turn, which shifts all remaining elements. At 6 stacks this is negligible, but this is the hot path for batch runs. Should be a `collections.deque` with `popleft()`.

**`living_stack_ids` sorts on every call.**
`living_stack_ids()` returns a freshly sorted list each invocation. It is called multiple times per turn (legal action generation, winner check, occupied hexes). With small armies this is fast, but the sort is wasted work when the ordering hasn't changed.

**`occupied_hexes` rebuilds a set on every call.**
Similarly called multiple times inside `legal_actions()`. The occupied set is stable for the duration of a single legal-action computation; it could be computed once and reused.

**`JsonlLogger` opens and closes the file per event.**
```python
def write(self, event):
    with self.path.open("a", ...) as handle:
        ...
```
Every `logger.write(...)` call opens, writes, and closes the file. In a single-battle run this is ~10–30 events — negligible. In batch mode the logger is not used (no `--log` flag), so this is not a hot path. Still, a persistent file handle with `flush()` after each write would be cleaner.

**`waiting_order` is re-sorted on every WAIT action.**
```python
self.state.waiting_order.sort(...)
```
In practice there are few WAIT actions per round, but a sorted insertion (`bisect`) would be more correct in intent.

**`cmd_batch` is too long and uses untyped nested dicts.**
The `cmd_batch` function is ~170 lines with all accumulation logic inline. The `totals` dict has an ad-hoc schema: `dict[str, dict[str, int | float | dict]]`. The nested `owner1`/`owner2` sub-dicts make it hard to follow. This should be extracted into a dedicated `BatchAccumulator` dataclass with typed fields and accumulation methods.

**Strategy modules are re-imported on every simulation in batch mode.**
`load_strategy` calls `importlib.import_module` unconditionally. In a 1000-sim batch run the same module is imported 1000 times. Python caches modules in `sys.modules`, so this is not actually slow — the module is loaded once. But calling `build_strategy()` on each call re-creates the strategy object and its internal `random.Random`. This is intentional (fresh seed per sim) but the comment is missing, making the intent unclear.

**Seed derivation formula is undocumented magic.**
```python
def _derive_simulation_seed(batch_seed: int, index: int) -> int:
    return batch_seed * 1_000_003 + index * 9_176 + 97
```
This is a linear formula, not a hash. Two seeds that differ by 1 produce sim-seeds that differ by exactly 1,000,003 — their derived strategy seeds (`sim_seed + 11`, `sim_seed + 29`) are also a fixed distance apart. For most uses this is fine, but a proper hash (e.g., `hash((batch_seed, index)) & 0xFFFFFFFF`) would give better statistical independence.

**Strategy receives mutable `BattleState`.**
`Strategy.choose_action(state, actor_id, legal_actions)` receives the live mutable state. A poorly written strategy could accidentally modify it. The interface should either pass a read-only snapshot or document that the state must not be mutated.

**`CandidateScore` is `frozen=True` but contains a mutable `dict`.**
```python
@dataclass(frozen=True, slots=True)
class CandidateScore:
    features: dict[str, float]
```
The dataclass is frozen (no attribute reassignment), but `features` itself is mutable. This is misleading. Either use `types.MappingProxyType` for true immutability or document that frozen here only means the reference is stable.

**`_score_features` always sets `distance_closed` twice under certain branches.**
When `action.target_pos is not None`, `distance_closed` is computed correctly. When it is None (attack/wait/defend), it falls to the `else: features["distance_closed"] = 0.0` block. Then separately, `move_cost` is conditionally set. These two branches interact in a way that requires reading both carefully. Structuring by action type would be clearer.

**`here.json` is an untracked, undescribed file in the repo root.**
It appears in `git status` as untracked. Its purpose is unclear and it should either be committed with documentation or added to `.gitignore`.

**Commented-out build backend code left in `pyproject.toml`.**
```toml
#[tool.hatch.build.targets.wheel]
#packages = ["src/sim_matter"]
#[build-system]
#requires = []
#build-backend = "backend"
```
Dead configuration from an earlier project name (`sim_matter`) should be removed.

---

### What could be improved

- Replace `list.pop(0)` with `deque.popleft()` in `_next_actor_id`.
- Cache `living_stack_ids()` and `occupied_hexes()` within a single turn's action-generation pass.
- Extract `cmd_batch` accounting into a `BatchAccumulator` class with typed fields.
- Replace the linear seed derivation with a hash-based derivation.
- Mark `BattleState` as must-not-be-mutated in the `Strategy` protocol docstring, or pass a frozen snapshot.
- Replace `CandidateScore.features: dict` with `Mapping[str, float]` or `MappingProxyType`.
- Delete the commented `pyproject.toml` remnants and `.gitignore` or commit `here.json`.
- Add a `__repr__` or display helper to `BattleSummary` for interactive use.
- Consider moving `_build_side_split_stats` / `_build_player_batch_stats` into `batching.py` alongside the data classes they populate, rather than scattering them in `cli.py`.
