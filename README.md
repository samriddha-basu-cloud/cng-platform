# CNG Supply Chain Network Design & Scarcity Decision-Support Platform

A working decision-support platform: configure a CNG supply network of
any size, run real MILP optimization under supply/demand scenarios,
simulate scarcity shocks, compare alternative network designs, and get
management-ready analytics — backed by an actual Pyomo optimization
engine, not a mock-up.

## No database — everything is plain files

There is no SQL database anywhere in this app. All state lives under
one folder (`storage/` by default, configurable via the `DATA_DIR`
environment variable):

```
storage/
  projects/<id>.json      one JSON file per project (network + scenarios + assumptions)
  runs/<project_id>.jsonl one line per optimization run, appended (never rewritten)
  logs/usage_log.csv      human-readable audit log - one row per action
  counters.json           next project/run id
```

You can open any of these directly — `cat storage/logs/usage_log.csv`,
or `python -m json.tool storage/projects/1.json` — no ORM, no migrations,
no separate service to run. Delete the whole `storage/` folder to reset
the app completely.

This was a deliberate trade for simplicity: `app/data/entities.py` and
`app/data/repo.py` are the only two files that know about file I/O.
Everything else (the optimizer, analytics, validation, simulation) just
does plain attribute access like `project.sources` and has no idea
whether that came from a database or a JSON file — so swapping the
storage layer never touched the parts that actually do the modeling.

## Status: Phases 1–7 implemented, plus V2 Phase 1 (multi-period + Excel) and Phase 2 (investment, storage, expansion, control tower)

All phases from the original build plan have working code behind them,
verified with an automated test suite (62 tests, `pytest tests/`) and
manual end-to-end checks. See **"Honest limitations"** below for what's
simplified rather than fully built.

## What's actually in here

**Foundation**
- Flask app, file-based storage, dynamic network CRUD (any number of
  sources/corridors/CGS/stations/demand zones — nothing about network
  size is hard-coded)
- Leaflet network map, structural validation, illustrative demo dataset
- Light, larger-type UI aimed at people without a technical background —
  every editable field has a placeholder with realistic sample values,
  every entity tab has a one-line plain-English explanation, and actions
  confirm themselves with toast notifications rather than silent success

**Optimization engine**
- Real capacitated facility-location MILP (Pyomo, solved via HiGHS —
  bundled, no external solver install needed)
- Deterministic solve, cost breakdown, facility/flow results, KPIs
- Infeasibility diagnostics that explain *why*, not just that it failed
- A hand-computed known-optimal test case the solver is asserted to match
  exactly (`tests/test_optimization.py::test_known_optimal_value`)

**Realism modules (opt-in, Setup tab)**
- Gas pressure feasibility on CGS→station and station→demand legs (discharge
  pressure minus distance-based drop vs. required pressure)
- Household "silent hours" throughput throttle, take-or-pay contract
  penalty clauses, price/infrastructure escalation in the time-series
  simulation, household travel-distance limits, logistics cost variation
  and industrial demand variability presets
- Every module is off by default and reads its numbers from fields you set
  per source/CGS/station/demand zone - see `MODEL_DOCUMENTATION.md` section
  8b for exactly what each one enforces and where its numbers come from

**Scenario engine**
- Scenario CRUD with per-entity parameter overrides
- One-click experiment presets (20/40/60% shortage, demand surge,
  pipeline failure, combined crisis)
- Two-stage stochastic optimization (shared facility decisions, scenario-
  indexed recourse flows, expected cost + worst-case cost)
- Robust mode (conservative/balanced/aggressive)
- What-if analysis (before/after comparison)

**Analytics**
- Transparent, weighted resilience score (never a black-box number)
- Cost-vs-service-level Pareto frontier
- Sensitivity tornado analysis
- 2D scenario heatmap
- Rule-based recommendation engine — every recommendation carries the
  actual figures that produced it

**Multi-period MILP & Excel planning data (V2 Phase 1)**
- A genuinely time-indexed MILP (`x[s,j,t]`, `w[j,k,t]`, `v[k,d,t]`, `u[d,t]`
  for `t = 1..12`) — one model with monthly flows, not 12 independent
  single-period solves. See `MODEL_DOCUMENTATION.md` section 8c.
- Monthly supply/demand/corridor-capacity data on the existing entities
  (`monthly_availability`, `monthly_demand`, `monthly_capacity`), editable
  via a 12-column grid on the new Planning tab; falls back to the existing
  flat values for any month left blank, so every existing project keeps
  working unchanged.
- Self-generating Excel template + sample dataset + import pipeline (Upload
  → Validate → Preview → Import) — the app never requires an external Excel
  file. See `MODEL_DOCUMENTATION.md` section 8d.
- Monthly allocation (Node × Month) and supply-demand-balance (Month ×
  Supply/Demand/Shortage/Service Level) dashboards on the Planning tab.

**Expansion, storage, investment & control tower (V2 Phase 2)**
- Infrastructure expansion (`e_cgs`/`e_station`) is a real MILP decision,
  bounded per facility, correctly linearized (not a bilinear capacity ×
  open-decision term), with CAPEX in the objective.
- Opt-in CGS inventory/storage carryover between months
  (`Project.enable_storage`), backward-compatible off by default.
- Investment decision support: minimum CAPEX for a target service level,
  and maximum service level for a fixed budget — both real MILP solves,
  not a lookup table. See the Control Tower → Investment Analysis tab.
- Binding-constraint/bottleneck analysis with finite-difference marginal
  value estimates, explicitly **not** presented as LP dual/shadow prices
  (the model is a MILP — see `MODEL_DOCUMENTATION.md` section 8e).
- Lexicographic priority allocation (Mode B: fully protect each priority
  tier before the next, a genuinely sequential multi-stage solve) alongside
  the existing weighted-penalty policy (Mode A).
- Executive Control Tower: KPIs, per-tier service levels against their own
  configured floors, source-dependency concentration, and rule-based
  CRITICAL/WARNING/INFO alerts — all from a real solve.
- Run comparison (`GET /api/runs/compare`) and minimal dataset versioning
  (`Project.dataset_version`, stamped on every Excel import).
- Mode choice (spec section 24): the multi-period model indexes flow by
  corridor code, not `(origin, destination)`, so two corridors between the
  same source/CGS pair with different mode/cost/capacity are genuinely
  distinct arcs the optimizer chooses between — not a cosmetic label.
  **Not yet ported to the older single-period/stochastic models** (see
  `MODEL_DOCUMENTATION.md` section 9).
- Still out of scope (see limitations): storage beyond CGS nodes, phased/
  monthly expansion timing, GIS/Sankey visualization, a browsable
  dataset-version history.

**Rolling horizon, forecast vs actual, assumption register (V2 Phase 3)**
- Rolling-horizon re-optimization (`POST /api/optimize/<pid>/rolling-horizon`):
  genuinely distinct from the static 12-month plan — solves a look-ahead
  window at each month, commits only that month, and re-solves forward,
  with candidate facilities that open forced to stay open in later windows
  (irreversible commitments). Doesn't yet react to updated/actual data
  mid-run — see limitations.
- Forecast vs Actual (`GET /api/analytics/<pid>/forecast-vs-actual`):
  variance/MAPE/bias between each zone's planning forecast and a new
  `actual_demand` field, by node/customer-segment/overall. No Excel
  `Actuals` sheet yet — set via PATCH on the demand-zone entity.
- Assumption Register (`/api/assumptions/<pid>`, full CRUD) — the data
  model and demo-seed population existed since Phase 1 but had **no API
  route at all**; this closes that real gap.
- A latent bottleneck-analysis bug (flow matched by origin/destination
  instead of corridor code, which would double-count/misattribute flow
  between two corridors sharing an endpoint pair) was fixed as part of
  making mode choice real.

**Simulation**
- Multi-period timeline with per-zone compounding demand growth and
  schedulable shocks (see limitations — no inter-period inventory state)

**Reports**
- Executive and technical report payloads generated from a fresh solve
- Export to JSON, CSV, Excel (openpyxl), and PDF (reportlab)
- Industry mode / Academic mode toggle

**Testing & docs**
- 62 pytest tests, isolated per-test via a temp `DATA_DIR` so file
  storage never leaks between test runs
- This README + `MODEL_DOCUMENTATION.md` (full mathematical formulation
  and a stated-plainly limitations section)

## Honest limitations

Read `MODEL_DOCUMENTATION.md` section 9 for the full modeling-level list
(facility open/close isn't per-month, storage is CGS-only, expansion has
no phased timing, investment optimization's service constraint is
horizon-wide aggregate rather than per-zone, marginal value analysis is a
finite-difference re-solve rather than an LP dual, CGS→station arcs have
no explicit corridor entity, virtual pipeline is a label not a mode-choice
optimization, analytics re-solve rather than cache, infeasibility
diagnostics are heuristic not a formal IIS).

**On storage specifically:** JSON files are simpler and more inspectable
than a database, but they are still just files on whatever disk the app
runs on. If you deploy somewhere with an *ephemeral* filesystem (see
hosting section below), your projects and logs disappear on every
restart — same as SQLite would have. Moving off a database doesn't
change that; only a genuinely persistent disk does.

## Architecture

```
/app
  /routes        page_routes, project_routes, network_routes, meta_routes,
                 scenario_routes, optimize_routes, whatif_routes,
                 simulation_routes, analytics_routes, report_routes,
                 excel_routes (template/sample download, validate, import)
  /data          entities.py (plain dataclasses), repo.py (file I/O + CRUD),
                 demo_seed.py (illustrative dataset)
  /optimization  model_builder.py (dynamic Pyomo model + time-indexed
                 multi-period model), engine.py (solve + extract results,
                 single-period and multi-period), diagnostics.py
                 (infeasibility causes, single- and multi-period),
                 solver_registry.py (HiGHS/CBC/Gurobi/CPLEX detection)
  /services      scenario_service.py (scenario -> overrides, presets),
                 report_service.py (report payloads + export),
                 excel_service.py (template/sample generation, parsing,
                 validation, import - see MODEL_DOCUMENTATION.md section 8d)
  /simulation    timeline.py (multi-period simulation)
  /analytics     resilience.py, pareto.py, sensitivity.py, recommendations.py,
                 bottlenecks.py (binding-constraint + marginal value analysis),
                 control_tower.py (executive KPIs + rule-based alerts)
  /utils         validation.py (structural network checks), usage_logger.py
  /templates     index.html, workspace.html
  /static        css/js - vanilla JS, config-driven network builder
tests/           pytest suite (network, optimization, analytics)
MODEL_DOCUMENTATION.md   full mathematical formulation + limitations
```

## Running locally

Requires Python 3.10+.

```bash
cd cng-platform
pip install -r requirements.txt
python run.py
```

Open `http://localhost:5050`. The `storage/` folder is created
automatically on first run.

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Free hosting: Render

Since there's no database to provision, deployment is a single service.

1. Push this folder to GitHub (you've likely already done this).
2. Go to [render.com](https://render.com), sign in with GitHub, no card required for the free tier.
3. **New → Web Service** → connect your repo. Render auto-detects Python.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
     (already in the included `Procfile`, so Render should pick it up automatically)
   - Instance type: **Free**
4. In **Environment**, add `SECRET_KEY` set to any random string.
5. Deploy. Render gives you a `*.onrender.com` URL when it's done.

**Two honest caveats:**
- Render's free tier spins the app down after 15 minutes idle — the
  first request after a quiet period takes 30–50 seconds to wake up.
  Normal for free hosting.
- Render's free tier filesystem is **ephemeral** — your `storage/`
  folder (projects, run logs, usage log) resets whenever the service
  restarts or redeploys. Fine for a demo, portfolio piece, or trying the
  app out. If you need data to actually persist between restarts, Render
  offers a small paid Disk add-on (a few dollars/month) you can mount at
  `/opt/render/project/src/storage` — set `DATA_DIR` to that same path
  as an environment variable and nothing else changes. Alternatively,
  **PythonAnywhere**'s free tier has a genuinely persistent home
  directory (no auto-sleep wiping files), at the cost of a more manual,
  console-based deploy instead of git-push.

## Using it

1. Create an empty project or load the demo network from the homepage.
2. **Setup** → project metadata. **Network** → add/edit/delete any number
   of sources, corridors, CGS, stations, demand zones, priority classes —
   every field shows a sample value so you know what's expected.
   **Map** → see it laid out geographically. **Dashboard** → validation
   status + a "Run full analysis" button.
3. **Scenarios** → define scarcity/demand scenarios, compare them.
4. **Optimize** → deterministic / stochastic / robust, with solver stats
   and — if infeasible — the diagnosed cause.
5. **Simulate** → one-click crisis presets with before/after comparison,
   or a multi-period growth timeline.
6. **Analyze** → resilience breakdown, Pareto frontier, sensitivity
   tornado chart, scenario heatmap, recommendations.
7. **Report** → Industry/Academic mode, export to JSON/CSV/Excel/PDF.

## API surface

```
GET    /api/meta/health
GET    /api/meta/solvers

GET/POST/PATCH/DELETE  /api/projects[/<id>]
POST   /api/projects/demo

GET/POST/PATCH/DELETE  /api/network/<pid>/{sources|corridors|cgs|stations|demand|priorities}[/<id>]
GET    /api/network/<pid>/graph
GET    /api/network/<pid>/validate

GET/POST/PATCH/DELETE  /api/scenarios/<pid>[/<id>]
GET    /api/scenarios/<pid>/presets
GET    /api/scenarios/<pid>/presets/<key>

POST   /api/optimize/<pid>                      deterministic
POST   /api/optimize/<pid>/multiperiod          time-indexed 12-month MILP
POST   /api/optimize/<pid>/multiperiod/lexicographic   Mode B: sequential per-tier priority solve
POST   /api/optimize/<pid>/investment/min-capex        min CAPEX for a target service level
POST   /api/optimize/<pid>/investment/max-service      max service level for a fixed CAPEX budget
POST   /api/optimize/<pid>/rolling-horizon             rolling-horizon re-optimization
POST   /api/optimize/<pid>/compare-scenarios
POST   /api/optimize/<pid>/stochastic
POST   /api/optimize/<pid>/robust
GET    /api/runs/<pid>
GET    /api/runs/detail/<run_id>
GET    /api/runs/compare?run_a=<id>&run_b=<id>         run A vs run B diff

GET    /api/data/<pid>/template                 download blank Excel template
GET    /api/data/<pid>/sample                    download sample dataset (always passes validation)
POST   /api/data/<pid>/validate                 dry-run validate an uploaded workbook (multipart 'file')
POST   /api/data/<pid>/import                   validate + import (multipart 'file', form 'mode')

POST   /api/whatif/<pid>
POST   /api/simulate/<pid>

GET    /api/analytics/<pid>/resilience
GET    /api/analytics/<pid>/pareto
GET    /api/analytics/<pid>/tornado
GET    /api/analytics/<pid>/heatmap
GET    /api/analytics/<pid>/recommendations
GET    /api/analytics/<pid>/summary
GET    /api/analytics/<pid>/bottlenecks         binding-constraint analysis + finite-difference marginal values
GET    /api/analytics/<pid>/control-tower       executive KPIs, tier service levels, alerts
GET    /api/analytics/<pid>/forecast-vs-actual  variance/MAPE/bias vs recorded actual_demand

GET/POST/PATCH/DELETE  /api/assumptions/<pid>[/<id>]   Assumption Register (spec section 62)

GET    /api/report/<pid>/executive
GET    /api/report/<pid>/technical
GET    /api/report/<pid>/export/{json|csv|excel|pdf}
```

## Data principle

Every demo/illustrative value is stored with `status="Illustrative"` in
the project's assumptions list, the demo project is flagged
`is_demo=True`, and every report/export carries a data-quality note.
Illustrative demo numbers are never presented as real GAIL/IGL/MGL/PPAC
figures.
