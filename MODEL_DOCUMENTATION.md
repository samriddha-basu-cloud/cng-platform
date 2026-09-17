# Model Documentation

This documents the actual optimization model implemented in
`app/optimization/model_builder.py` and `app/optimization/engine.py` —
not an aspirational spec. Every claim below can be checked against that
code, and against `tests/test_optimization.py::test_known_optimal_value`,
which is a hand-computed case the solver is asserted to match exactly.

## 1. Network structure

Four echelons, built dynamically from whatever rows exist in a project
(no fixed counts anywhere):

```
Sources (S) --SJ--> CGS (J) --JK--> CNG Stations (K) --KD--> Demand Zones (D)
```

- **SJ arcs** come from explicit `Corridor` rows (`origin_type=source`,
  `destination_type=cgs`).
- **JK arcs** (CGS → station) are dense: every active CGS can feed every
  active station. There's no dedicated "CGS-station corridor" entity in
  the schema, so this hop has no arc-level capacity constraint — only
  the node (facility) capacities apply. Cost is distance-based
  (haversine, ₹0.02/unit/km) when both ends have coordinates, otherwise
  a flat default (3.0/unit).
- **KD arcs** (station → demand) exist only where the demand zone falls
  within the station's configured `demand_service_radius_km`. Cost is
  distance-based (₹0.03/unit/km) or a flat default (2.0/unit) if
  coordinates are missing on either end.

## 2. Sets

| Symbol | Meaning |
|---|---|
| S | active sources |
| J | active CGS |
| K | active CNG stations |
| D | demand zones |
| SJ | source→CGS arcs (from Corridor rows) |
| JK | CGS→station arcs (dense product of J × K) |
| KD | station→demand arcs (gated by service radius) |

## 3. Decision variables

| Variable | Type | Meaning |
|---|---|---|
| y_j | binary | 1 if CGS j is open (fixed to 1 if `infra_status="existing"`) |
| z_k | binary | 1 if station k is open (fixed to 1 if `infra_status="existing"`) |
| x_sj | continuous ≥ 0 | flow from source s to CGS j |
| w_jk | continuous ≥ 0 | flow from CGS j to station k |
| v_kd | continuous ≥ 0 | flow from station k to demand zone d |
| u_d | continuous ≥ 0 | unmet demand at zone d |

## 4. Objective

```
minimize:
    Σ_j FixedCost_j · y_j
  + Σ_k FixedCost_k · z_k
  + Σ_(s,j) SupplyCost_s · x_sj
  + Σ_(s,j) TransportCost_sj · x_sj
  + Σ_(j,k) DistanceCost_jk · w_jk
  + Σ_(k,d) DistanceCost_kd · v_kd
  + Σ_d PenaltyBase · PriorityWeight_d · u_d
```

`PenaltyBase` defaults to 50 currency units per unit of unmet demand;
`PriorityWeight_d` comes from the demand zone's linked `PriorityClass`
(default 1.0 if unlinked). This is a modeling assumption, not a derived
figure — documented here so it isn't mistaken for real cost data.

## 5. Constraints

1. **Source capacity**: Σ_j x_sj ≤ availability_factor_s × max_capacity_s
2. **Corridor capacity**: x_sj ≤ corridor_capacity_sj
3. **CGS flow balance**: Σ_s x_sj = Σ_k w_jk
4. **CGS capacity**: Σ_s x_sj ≤ capacity_j × y_j
5. **Station flow balance**: Σ_j w_jk = Σ_d v_kd
6. **Station capacity**: Σ_j w_jk ≤ capacity_k × z_k
7. **Demand balance**: Σ_k v_kd + u_d = demand_d
8. **Service level**: u_d ≤ (1 − min_service_level_d) × demand_d
9. **Existing infrastructure**: y_j = 1 / z_k = 1 when `infra_status="existing"` (candidate facilities are free variables)

## 6. Scenario handling

`app/optimization/model_builder.apply_overrides()` takes a base
`NetworkData` snapshot and an overrides dict and returns a new snapshot —
the base model never mutates in place. Overrides supported:

- `source_availability: {code: factor}` — replaces `base_availability`
- `demand_multiplier` / `demand_zone_multiplier` — scales demand
- `corridor_capacity_multiplier` / `transport_cost_multiplier`
- `facility_cost_multiplier`
- `service_level_override` — replaces every zone's minimum service level
- `inactive_corridors` / `inactive_cgs` / `inactive_stations` — outages

**Deterministic**: one override set, one solve
(`POST /api/optimize/<id>`).

**Scenario comparison**: solves each of a project's default scenarios
independently (`POST /api/optimize/<id>/compare-scenarios`).

**Two-stage stochastic** (`POST /api/optimize/<id>/stochastic`,
`model_builder.build_stochastic_model`): y_j/z_k are shared
"here-and-now" first-stage variables across all scenarios; flows and
unmet demand are scenario-indexed recourse variables. The objective is
fixed cost + Σ_t π_t × (scenario t's variable cost). **Facility/arc
topology is assumed identical across scenarios** — only capacities,
costs, availability, and demand vary. This is the reference project's
"Option 2" formulation. Expected cost and worst-case cost (the max
scenario total, using the shared facility decisions) are both reported.

**Robust mode** (`POST /api/optimize/<id>/robust`): rather than
probability-weighting scenarios, solves a single deterministic model
against one availability factor drawn from a configurable
`[low, high]` range — `conservative` uses the low end, `aggressive` the
high end, `balanced` the midpoint. Simpler and more conservative than a
true worst-case-over-uncertainty-set robust formulation, but transparent
about what it's doing.

## 7. Infeasibility diagnostics

`app/optimization/diagnostics.py` runs a small set of cheap, explainable
checks on the same `NetworkData` the optimizer used (total supply vs.
demand, unreachable demand zones, unfed CGS, aggregate minimum-service-level
feasibility, total CGS/station capacity vs. demand) and returns
human-readable causes and suggestions. **This is a heuristic screen, not
a formal IIS/conflict refiner** — it catches the common cases, not every
possible cause of infeasibility.

## 8. Solver

Solved via Pyomo. Preference order, open-source first: **HiGHS** (bundled
via the `highspy` package, used through Pyomo's `appsi` interface, no
external install) → CBC → Gurobi → CPLEX. `app/optimization/solver_registry.py`
detects what's actually available at runtime; no commercial solver is
required. See `/api/meta/solvers`.

## 8b. Optional realism modules (all off by default, all user-driven)

Seven switches on the Setup tab (`Project.enable_*`, all default `False`)
turn on extra constraints/cost terms built from fields you set per entity
on the Network tab. None of them supply a hidden value — flipping a switch
only starts *enforcing* numbers already sitting in your network. With every
switch off, the model is byte-for-byte the one described in sections 1-8.

| Module | What it does | Reads from |
|---|---|---|
| Gas pressure model | Gates CGS→station and station→demand arcs: an arc only exists if delivered pressure (discharge/dispensing pressure minus `pressure_drop_rate_bar_per_km × distance`) still meets the receiving station's/zone's minimum. Purely a feasibility gate on `snapshot_network()` - no new decision variable. | `CGS.discharge_pressure_bar`, `CNGStation.min_inlet_pressure_bar` / `dispensing_pressure_bar`, `DemandZone.min_required_pressure_bar`, `Project.pressure_drop_rate_bar_per_km` |
| Household silent hours | Caps `v[k,d]` at `station.capacity × (available_hours/24)` for a zone with a configured no-delivery window - the same daily volume has to fit into fewer hours, so it competes harder for the station's throughput. | `DemandZone.silent_hours_start/end` |
| Take-or-pay penalty clauses | Adds `shortfall[s] >= contracted_quantity_s - offtake_s` (≥0) and `+ take_or_pay_penalty_rate_s × shortfall[s]` to the objective - a real contract term where under-lifting still costs money. | `Source.contracted_quantity`, `Source.take_or_pay_penalty_rate` |
| Price / infrastructure escalation | In the Time-Series Simulation only (`app/simulation/timeline.py`): compounds `supply_cost × (1+rate)^t` and CGS/station fixed cost × `(1+rate)^t` per period. Does not touch the single-period objective. | `Source.price_escalation_pct`, `CGS`/`CNGStation.infrastructure_escalation_pct` |
| Household travel-distance limit | Effective KD-arc radius becomes `min(station.demand_service_radius_km, zone.max_travel_distance_km)`. | `DemandZone.max_travel_distance_km` |
| Logistics cost variation | Feeds the `logistics_cost_spike` scenario preset (uses the average `Corridor.cost_variation_pct` when solving `transport_cost_multiplier`) and sensitivity what-if runs. | `Corridor.cost_variation_pct` |
| Industrial demand variability | Feeds the `industry_demand_variability` scenario preset, which scales only `demand_type="Industrial"` zones by their own `demand_variability_pct` (defaults to +15% if unset). | `DemandZone.demand_variability_pct` |

Two more presets ride on the same fields without needing a toggle:
`gail_upstream_interruption` (cuts availability only on sources flagged
`Source.is_upstream_gail`, by each source's own `interruption_probability`)
models a national-grid-style upstream disruption distinct from a uniform
shortage shock.

`Project.unmet_demand_penalty_base`, `jk_cost_per_km`, `jk_flat_cost`,
`kd_cost_per_km`, `kd_flat_cost` make the previously hard-coded defaults
(`DEFAULT_UNMET_PENALTY_BASE` etc. in `model_builder.py`) per-project and
user-editable from the Setup tab, defaulting to the same values as before.

## 8c. Multi-period (time-indexed) MILP

`app/optimization/model_builder.py::build_time_indexed_model`, reached via
`POST /api/optimize/<pid>/multiperiod`, is a genuinely time-indexed model —
**one** Pyomo model with flows indexed by month, not a loop of independent
single-period solves (that older, explicitly-labeled-as-a-simplification
approach is `app/simulation/timeline.py`, which is unchanged and still
available as the "quick sequential" mode).

**Sets:** everything from section 2, plus `T = {1, ..., H}` where `H =
Project.monthly_horizon` (default 12).

**Decision variables:** `x[s,j,t]`, `w[j,k,t]`, `v[k,d,t]`, `u[d,t]` — every
flow and shortage variable from section 3 gains a `t` index. Facility
open/close decisions `y[j]`, `z[k]` stay **not** time-indexed — the network
topology is fixed across the horizon; only flows, allocation, and shortage
vary month to month. This is a deliberate scope boundary (see limitations
below), not an oversight.

**Per-month parameters:** `Source.monthly_availability`, `DemandZone.monthly_demand`,
`Corridor.monthly_capacity`/`monthly_transport_cost` are `{month: value}`
dicts (month as `"1".."12"`). `snapshot_network()` resolves these once per
solve into `nd.sources[s]["monthly_availability"][t]` etc., falling back to
the flat single-period scalar (`base_availability × max_capacity`,
`base_demand`, `capacity`, `transport_cost`) for any month with no explicit
override — so a project with no monthly data behaves **identically** to the
single-period model, run 12 times, values-wise.

**Objective:** supply/transport/shortage costs are summed over every month.
Fixed/operating cost is a convention worth stating explicitly: `CGS.fixed_operating_cost`
and `CNGStation.fixed_cost` are treated as a **monthly** opex rate, so a
facility open across the whole horizon contributes `fixed_cost × H` to the
objective, not a one-time capex charge.

**Constraints:** `SourceCap[s,t]`, `CorridorCap[s,j,t]`, `CGSBalance[j,t]`,
`CGSCap[j,t]`, `StationBalance[k,t]`, `StationCap[k,t]`, `Demand[d,t]`,
`ServiceLevel[d,t]` — the same rules from section 5, each evaluated against
month `t`'s resolved parameter values.

**Result payload** (`engine.solve_multiperiod`) adds `monthly_breakdown`
(one row per month: supply available/used, demand, allocated, shortage,
service level, cost, surplus/deficit — the Month × {Supply, Demand,
Allocation, Shortage, Service Level} table) and `monthly_allocation` (one
row per node × month — the Node × Month table), plus `flows_by_month`.
Infeasibility diagnostics (`diagnostics.diagnose_multiperiod`) run per
month and report which month is tightest, rather than one flat aggregate
diagnosis that can't say *when* the network fails.

## 8d. Excel planning-data import/export

`app/services/excel_service.py`, reached via the `/api/data/<pid>/...`
routes, generates its own template and sample workbook — **the app never
requires an external Excel file.** Master-data sheets (Sources, CGS,
CNG_Stations, Demand_Zones, Corridors, Priority_Tiers) are generated
straight from the entity dataclasses (`dataclasses.fields()`), so a new
field added to `entities.py` shows up in the template automatically — there
is no separate schema file to keep in sync. Planning-data sheets
(Monthly_Supply, Monthly_Demand, Monthly_Capacity, Costs) are one row per
`(entity code, month)`, matching exactly what the time-indexed model
consumes.

Import is: parse (`openpyxl`) → validate (schema → data types → referential
integrity → business rules → duplicate-month checks, returned in the same
`{level, message}` shape `app/utils/validation.py::validate_network` uses,
extended with `sheet`/`row`/`column`) → preview (added/updated counts,
data-quality score) → only on zero validation errors, apply (upsert
master data by `code`, replace monthly dicts for touched entities). Nothing
is written to a project until validation passes and the caller explicitly
confirms.

## 8e. Infrastructure expansion, storage, investment optimization, bottleneck/marginal analysis, lexicographic priority, mode choice (V2 Phase 2)

**Mode choice (spec section 24).** `build_time_indexed_model` indexes the
source→CGS flow variable `x` by **corridor code** (`m.C`), not by
`(origin, destination)`. Two corridors sharing an origin/destination pair
but tagged with a different `pipeline_type` (e.g. "pipeline" vs. "virtual")
and their own cost/capacity/loss/reliability are therefore genuinely
distinct arcs — the optimizer allocates flow between them on cost and
capacity, exactly like any other mode-choice formulation, not a cosmetic
label. See the "Known limitations" note below on the two older models that
don't yet share this fix.

**Expansion (spec section 21).** `e_cgs[j]`/`e_station[k]` are real
non-negative decision variables in `build_time_indexed_model`, bounded by
each facility's own `max_expansion` (default 0 → pinned to 0, so existing
projects are unaffected). Linearized as `e <= max_expansion * y` (constant ×
binary) plus `inflow <= capacity * y + e` — **not** `(capacity + e) * y`,
which would be a bilinear (non-MILP) term. Expansion CAPEX
(`expansion_cost * e`, summed once, not per month) is a real objective term.

**Storage (spec section 23).** Opt-in via `Project.enable_storage`
(off by default). When on, each CGS gets an inventory variable `I[j,t]`
bounded by `storage_capacity` (default 0 → pinned to 0) with balance
`I[j,t-1] + inflow == outflow + I[j,t]` (replacing the plain
`inflow == outflow` rule), `opening_inventory` seeding month 1, and
`storage_cost * I[j,t]` in the objective. Storage is modeled only at CGS
nodes (the natural city-gate buffer point), not at sources or stations —
a deliberate scope boundary, not an oversight.

**Investment optimization (spec section 22/84).**
`build_time_indexed_model(objective_mode=...)` supports three additional
objectives on top of the default `"standard"` (unchanged, minimize total
cost): `"capex_min"` (minimize expansion CAPEX, paired with
`min_aggregate_service_level` — a single horizon-wide, not per-zone,
service floor) and `"shortage_min"` (minimize total unmet demand, paired
with `max_capex`). `engine.solve_min_investment_for_service`/
`solve_max_service_for_budget` wrap these. Every mode still reports
`result["total_cost"]` reconstructed from the actually-solved flows,
regardless of what the objective itself minimized.

**Binding-constraint / bottleneck analysis (spec section 19)**
(`app/analytics/bottlenecks.py::analyze_bottlenecks`) computes per-asset,
per-month utilization (source availability, corridor capacity, CGS/station
effective capacity vs. their solved flows) from a multi-period result,
classifies BINDING (≥99.9%) / NEAR_BINDING (≥85%) / NON_BINDING, and
aggregates into a ranked "critical bottlenecks" list.

**Marginal value analysis (spec section 20)** — explicitly **not** an LP
dual/shadow price, since the model is a MILP. `marginal_value_analysis`
re-solves the whole model once per top bottleneck with its capacity bumped
by a small increment at its worst month, and reports
`(baseline objective - resolved objective) / increment`. Slower than
reading a dual (one extra full MILP solve per asset, capped at the top 5
bottlenecks) but every number is real re-solve output.

**Lexicographic priority (spec section 14, Mode B)**
(`engine.solve_lexicographic`) is a genuinely sequential multi-stage solve
— NOT rank=1,2,3 weighting relabeled. One `objective_mode="zone_shortage_min"`
solve per `PriorityClass.rank`, in ascending order; each stage's resulting
per-zone shortage total is locked in via `zone_shortage_caps` before the
next (lower-priority) tier is optimized, so a later stage can never claw
capacity back from an earlier one. A final stage minimizes real total cost
with every tier's shortage locked. This is Mode B, distinct from the
default weighted-penalty Mode A (`PriorityClass.penalty_weight` in the
standard objective) — both are real, selectable policies.

**Control Tower (spec sections 34-36, 63, 85)**
(`app/analytics/control_tower.py`) assembles KPIs, per-tier service levels
(compared against each tier's own configured `min_fulfilment_pct`, not an
assumed 95/90/80 split), source-dependency concentration, and rule-based
CRITICAL/WARNING/INFO alerts — all read off a real multi-period solve plus
the bottleneck analysis above, never a static threshold applied to a
number that was never computed.

**Run comparison (spec section 60)** (`GET /api/runs/compare`) diffs two
stored runs' result payloads (cost, service level, shortage, CAPEX,
facility counts) regardless of run type.

**Dataset versioning (spec section 55, minimal)** — every successful Excel
import stamps `Project.dataset_version` (`IMPORT_<timestamp>`),
`dataset_imported_at`, and `dataset_source` (the uploaded filename). Full
version history / rollback is not implemented — only the current version
is tracked.

## 8f. Rolling horizon, forecast vs actual, assumption register (V2 Phase 3)

**Rolling horizon re-optimization (spec section 25)**
(`engine.solve_rolling_horizon`) is genuinely distinct from the static
12-month plan, not the same solve relabeled: at each month `t0` it solves
the time-indexed MILP over only a `window_size`-month look-ahead
`[t0..t0+window_size-1]`, commits **just** month `t0`'s decision, then
advances and re-solves. Facility open/close decisions are treated as
irreversible — once a candidate CGS/station opens in an earlier window, it
is forced `infra_status="existing"` in every later window's model, so the
rolling process can't "un-build" something already committed. **What this
does not yet do**: feed genuinely different forecast-vs-actual data into
each window — every window still solves against the same
`monthly_availability`/`monthly_demand` a static plan would use. The
rolling *mechanism* (partial visibility, irreversible commitments,
sequential re-solve) is real; wiring in updated/actual data mid-run is not.

**Forecast vs Actual (spec section 31)**
(`app/analytics/forecast_actual.py`) compares each demand zone's planning
forecast (`monthly_demand`, the number the optimizer actually used)
against a new `DemandZone.actual_demand` field (sparse, observational,
set via `PATCH /api/network/<pid>/demand/<id>` — no Excel `Actuals` sheet
yet), computing variance/absolute error/percentage error per (node, month)
and MAPE/bias aggregated by node, customer segment, and overall. Read-only
— it does not feed back into the optimizer or the rolling-horizon solve
above on its own.

**Assumption Register (spec section 62)** — the data model
(`app/data/entities.py::Assumption`) and demo-seed population have existed
since Phase 1, but had **no API route at all** until now (`/api/assumptions/<pid>`,
full CRUD) — a real gap this phase closes rather than a new feature.

**Mode choice correctness note**: the corridor-code indexing fix in section
8e (needed for mode choice) also fixed a latent bug in bottleneck analysis
— corridor flow used to be matched by `(origin, destination)`, which would
have double-counted or misattributed flow between two corridors sharing an
endpoint pair. Bottleneck records now match by corridor code.

## 9. Known limitations (stated plainly, not hidden)

- **The time-indexed model does not make facility open/close a per-month
  decision** — topology is fixed across the horizon; only flows/allocation
  (and, as of Phase 2, expansion/storage) vary monthly. Modeling phased
  facility openings (open CGS-B starting month 7, say) is not yet supported.
- **Storage is CGS-only** and **expansion has no phased/monthly timing** —
  both are horizon-wide, one-time decisions (see section 8e).
- **Investment optimization's service constraint is horizon-wide
  aggregate, not per-zone or per-month** — `min_aggregate_service_level`
  guarantees a total-allocation fraction across the whole network and
  horizon, not "every zone hits 95% every month". Per-zone `ServiceLevel`
  constraints still apply underneath it, but the investment objective
  itself doesn't target them individually.
- **Marginal value analysis is a finite-difference MILP re-solve, not an
  LP dual** — capped at the top 5 bottlenecks per request since each one
  costs a full extra solve; not run automatically on every optimize call.
- **Excel import supports "create new" and "replace" modes only** — no
  append/merge mode, and priority tiers must be imported before/with the
  demand zones that reference them by name (a single workbook handles this
  correctly; splitting priorities and demand across separate uploads to the
  same project does not). Dataset versioning tracks only the current
  version, not a browsable history.
- **CGS→station arcs have no arc-level capacity or an explicit corridor
  entity** — only node (facility) capacities constrain that hop, and its
  cost is a distance-based or flat default rather than a user-entered
  transport cost, because the schema didn't add a corridor-like entity for
  that leg.
- **Mode choice (pipeline vs. virtual pipeline, spec section 24) is now a
  real decision in the multi-period model only** (`build_time_indexed_model`
  indexes flow by corridor CODE, not `(origin, destination)`, so two
  corridors between the same source/CGS pair with different
  `pipeline_type`/cost/capacity are genuinely distinct arcs the optimizer
  allocates between — see section 8e). **The single-period model
  (`build_model`) and the stochastic model (`build_stochastic_model`) still
  key flow by `(origin, destination)`** and will silently collapse two
  corridors sharing an endpoint pair into one (only the last-inserted
  corridor's cost/capacity is used) — this is a real gap in those two
  older models, not yet ported over. Avoid configuring parallel corridors
  between the same pair for scenario/stochastic/robust runs until this is fixed.
- **Resilience score, Pareto frontier, sensitivity analysis, and the
  dashboard summary each re-solve the model multiple times** (per
  scenario / per perturbation / per service level), and still use the
  single-period solver, not the multi-period one. This is fine at demo
  scale (sub-second solves) but will get slow on large networks — no
  caching or Benders decomposition has been added yet.
- **Rolling horizon doesn't yet accept updated/actual data mid-run** —
  every window solves against the same forecast a static plan would (see
  section 8f); genuinely reacting to `actual_demand` deviations mid-horizon
  isn't wired in yet.
- **Forecast vs Actual has no Excel `Actuals` sheet** — actuals are set one
  zone/month at a time via `PATCH /api/network/<pid>/demand/<id>`, not
  bulk-imported.
- **GIS/Sankey visualization, and a browsable run-comparison UI beyond the
  two-run diff endpoint** are not implemented — deferred to a future phase.
- **Academic-mode formulation panel is generated from the same static
  description used in this document**, not dynamically derived from the
  live Pyomo model object — if the model changes, both this file and
  `report_service.build_technical_payload()` need updating together.
