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

## 9. Known limitations (stated plainly, not hidden)

- **No inventory/storage state carried between periods.** The time-series
  simulation (`app/simulation/timeline.py`) runs one independent
  deterministic solve per period with compounded demand growth — it does
  not implement the full I_t inventory-balance MILP from the original
  spec. Each period's numbers are real optimizer output; what's missing
  is inter-period storage dynamics.
- **CGS→station arcs have no arc-level capacity or an explicit corridor
  entity** — only node (facility) capacities constrain that hop, and its
  cost is a distance-based or flat default rather than a user-entered
  transport cost, because Phase 1's schema didn't add a corridor-like
  entity for that leg.
- **Virtual pipeline / M-D-O mode choice is not a separate optimization
  decision.** Corridors can be tagged `pipeline_type="virtual"`, which
  affects nothing in the solve yet — a real mode-choice model (comparing
  pipeline vs. virtual pipeline economics per the reference project's
  section 16) hasn't been built.
- **Budget-constrained investment optimization** (spec section 38: "what
  network can I get for ₹500 Cr" / "minimum investment for 95% service")
  is not implemented as a separate mode — you can approximate it manually
  via the Pareto frontier (cost at each service level) but there's no
  direct budget-constraint solve yet.
- **Resilience score, Pareto frontier, sensitivity analysis, and the
  dashboard summary each re-solve the model multiple times** (per
  scenario / per perturbation / per service level). This is fine at demo
  scale (sub-second solves) but will get slow on large networks (the
  spec's "20 sources × 50 CGS × 100 stations × 100 demand zones" case) —
  no caching or Benders decomposition has been added yet.
- **Academic-mode formulation panel is generated from the same static
  description used in this document**, not dynamically derived from the
  live Pyomo model object — if the model changes, both this file and
  `report_service.build_technical_payload()` need updating together.
