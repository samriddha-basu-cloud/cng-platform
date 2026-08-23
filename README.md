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

## Status: Phases 1–7 implemented

All phases from the original build plan have working code behind them,
verified with an automated test suite (26 tests, `pytest tests/`) and
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

**Simulation**
- Multi-period timeline with per-zone compounding demand growth and
  schedulable shocks (see limitations — no inter-period inventory state)

**Reports**
- Executive and technical report payloads generated from a fresh solve
- Export to JSON, CSV, Excel (openpyxl), and PDF (reportlab)
- Industry mode / Academic mode toggle

**Testing & docs**
- 26 pytest tests, isolated per-test via a temp `DATA_DIR` so file
  storage never leaks between test runs
- This README + `MODEL_DOCUMENTATION.md` (full mathematical formulation
  and a stated-plainly limitations section)

## Honest limitations

Read `MODEL_DOCUMENTATION.md` section 9 for the full modeling-level list
(no inter-period inventory MILP, CGS→station arcs have no explicit
corridor entity, virtual pipeline is a label not a mode-choice
optimization, no direct budget-constrained investment mode, analytics
re-solve rather than cache, infeasibility diagnostics are heuristic not
a formal IIS).

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
                 simulation_routes, analytics_routes, report_routes
  /data          entities.py (plain dataclasses), repo.py (file I/O + CRUD),
                 demo_seed.py (illustrative dataset)
  /optimization  model_builder.py (dynamic Pyomo model), engine.py (solve +
                 extract results), diagnostics.py (infeasibility causes),
                 solver_registry.py (HiGHS/CBC/Gurobi/CPLEX detection)
  /services      scenario_service.py (scenario -> overrides, presets),
                 report_service.py (report payloads + export)
  /simulation    timeline.py (multi-period simulation)
  /analytics     resilience.py, pareto.py, sensitivity.py, recommendations.py
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
POST   /api/optimize/<pid>/compare-scenarios
POST   /api/optimize/<pid>/stochastic
POST   /api/optimize/<pid>/robust
GET    /api/runs/<pid>
GET    /api/runs/detail/<run_id>

POST   /api/whatif/<pid>
POST   /api/simulate/<pid>

GET    /api/analytics/<pid>/resilience
GET    /api/analytics/<pid>/pareto
GET    /api/analytics/<pid>/tornado
GET    /api/analytics/<pid>/heatmap
GET    /api/analytics/<pid>/recommendations
GET    /api/analytics/<pid>/summary

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
