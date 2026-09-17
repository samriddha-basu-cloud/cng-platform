"""
File-based storage repository. No SQL database anywhere - every project
is one JSON file, every optimization run is one line appended to a
per-project JSONL log, and everything lives under a single configurable
DATA_DIR so the whole app's state is just files in a folder (easy to
inspect, back up, or wipe by hand).

Layout (relative to app.config["DATA_DIR"]):
    projects/<id>.json        - one project + all its network entities
    runs/<project_id>.jsonl   - append-only optimization run history
    counters.json             - next project id, next run id
    logs/usage_log.csv        - human-readable usage/audit log
"""
import os
import json
import glob
import dataclasses
from flask import current_app
from werkzeug.exceptions import NotFound

from app.data import entities as E

ENTITY_LIST_ATTR = {
    "sources": "sources", "corridors": "corridors", "cgs": "cgs_list",
    "stations": "stations", "demand": "demand_zones", "priorities": "priority_classes",
}
ENTITY_CLASS = {
    "sources": E.Source, "corridors": E.Corridor, "cgs": E.CGS,
    "stations": E.CNGStation, "demand": E.DemandZone, "priorities": E.PriorityClass,
}


# ---------------------------------------------------------------- paths ----
def _data_dir():
    d = current_app.config["DATA_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def _projects_dir():
    d = os.path.join(_data_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def _project_path(pid):
    return os.path.join(_projects_dir(), f"{pid}.json")


def _runs_dir():
    d = os.path.join(_data_dir(), "runs")
    os.makedirs(d, exist_ok=True)
    return d


def _runs_path(pid):
    return os.path.join(_runs_dir(), f"{pid}.jsonl")


def _counters_path():
    return os.path.join(_data_dir(), "counters.json")


def _load_counters():
    path = _counters_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_counters(counters):
    with open(_counters_path(), "w") as f:
        json.dump(counters, f)


def _next_counter(key):
    counters = _load_counters()
    counters[key] = counters.get(key, 0) + 1
    _save_counters(counters)
    return counters[key]


# ------------------------------------------------------- (de)serialize ----
def _serialize_project(project: E.Project) -> dict:
    return dataclasses.asdict(project)


def _deserialize_project(data: dict) -> E.Project:
    scalar_fields = {f.name for f in dataclasses.fields(E.Project)
                      if f.name not in ("sources", "corridors", "cgs_list", "stations",
                                        "demand_zones", "priority_classes", "scenarios", "assumptions")}
    kwargs = {k: v for k, v in data.items() if k in scalar_fields}
    project = E.Project(**kwargs)

    project.sources = [E.Source(**s) for s in data.get("sources", [])]
    project.corridors = [E.Corridor(**c) for c in data.get("corridors", [])]
    project.cgs_list = [E.CGS(**c) for c in data.get("cgs_list", [])]
    project.stations = [E.CNGStation(**s) for s in data.get("stations", [])]
    project.demand_zones = [E.DemandZone(**d) for d in data.get("demand_zones", [])]
    project.priority_classes = [E.PriorityClass(**pc) for pc in data.get("priority_classes", [])]
    project.assumptions = [E.Assumption(**a) for a in data.get("assumptions", [])]

    scenarios = []
    for sc in data.get("scenarios", []):
        sc = dict(sc)
        params = [E.ScenarioParameter(**p) for p in sc.pop("parameters", [])]
        scenarios.append(E.Scenario(**sc, parameters=params))
    project.scenarios = scenarios

    _link_relationships(project)
    return project


def _link_relationships(project: E.Project):
    """Attaches live object references that mirror the old SQLAlchemy
    relationships (e.g. demand_zone.priority_class) without storing them
    in the JSON file itself."""
    pc_by_id = {pc.id: pc for pc in project.priority_classes}
    for d in project.demand_zones:
        d.priority_class = pc_by_id.get(d.priority_class_id)


# ------------------------------------------------------------ projects ----
def list_projects() -> list:
    projects = []
    for path in glob.glob(os.path.join(_projects_dir(), "*.json")):
        with open(path) as f:
            projects.append(_deserialize_project(json.load(f)))
    projects.sort(key=lambda p: p.created_at, reverse=True)
    return projects


def get_project(pid) -> E.Project:
    path = _project_path(pid)
    if not os.path.exists(path):
        raise NotFound(f"Project {pid} not found")
    with open(path) as f:
        return _deserialize_project(json.load(f))


def save_project(project: E.Project) -> E.Project:
    project.updated_at = E.now_iso()
    with open(_project_path(project.id), "w") as f:
        json.dump(_serialize_project(project), f, indent=2, default=str)
    return project


def create_project(data: dict) -> E.Project:
    pid = _next_counter("project")
    project = E.Project(
        id=pid, name=data["name"], description=data.get("description", ""),
        region=data.get("region", ""), currency=data.get("currency", "INR"),
        gas_unit=data.get("gas_unit", "SCMD"), demand_unit=data.get("demand_unit", "SCMD"),
        time_granularity=data.get("time_granularity", "monthly"),
        planning_horizon_years=int(data.get("planning_horizon_years", 5)),
        num_periods=int(data.get("num_periods", 1)),
        num_scenarios=int(data.get("num_scenarios", 1)),
        status="Draft", is_demo=bool(data.get("is_demo", False)),
    )
    save_project(project)
    return project


def update_project(project: E.Project, data: dict, editable_fields: list) -> E.Project:
    for f in editable_fields:
        if f in data:
            setattr(project, f, data[f])
    return save_project(project)


def delete_project(pid):
    path = _project_path(pid)
    if not os.path.exists(path):
        raise NotFound(f"Project {pid} not found")
    os.remove(path)
    runs_path = _runs_path(pid)
    if os.path.exists(runs_path):
        os.remove(runs_path)


# ------------------------------------------------------- network CRUD -----
def list_entities(project: E.Project, entity_key: str) -> list:
    return getattr(project, ENTITY_LIST_ATTR[entity_key])


def add_entity(project: E.Project, entity_key: str, data: dict):
    cls = ENTITY_CLASS[entity_key]
    valid_fields = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in valid_fields and k not in ("id", "project_id")}
    kwargs["id"] = project.next_id()
    kwargs["project_id"] = project.id
    item = cls(**kwargs)
    list_entities(project, entity_key).append(item)
    save_project(project)
    return item


def update_entity(project: E.Project, entity_key: str, item_id: int, data: dict):
    cls = ENTITY_CLASS[entity_key]
    valid_fields = {f.name for f in dataclasses.fields(cls)}
    items = list_entities(project, entity_key)
    item = next((i for i in items if i.id == item_id), None)
    if item is None:
        raise NotFound(f"{entity_key} item {item_id} not found in project {project.id}")
    for k, v in data.items():
        if k in valid_fields and k not in ("id", "project_id"):
            setattr(item, k, v)
    save_project(project)
    return item


def delete_entity(project: E.Project, entity_key: str, item_id: int):
    items = list_entities(project, entity_key)
    idx = next((i for i, x in enumerate(items) if x.id == item_id), None)
    if idx is None:
        raise NotFound(f"{entity_key} item {item_id} not found in project {project.id}")
    items.pop(idx)
    save_project(project)


# ------------------------------------------------------- scenario CRUD ----
def add_scenario(project: E.Project, data: dict) -> E.Scenario:
    sc_id = project.next_id()
    parameters = []
    for p in data.get("parameters", []):
        parameters.append(E.ScenarioParameter(
            id=project.next_id(), scenario_id=sc_id, entity_type=p["entity_type"],
            entity_code=p["entity_code"], parameter=p["parameter"], value=p["value"],
        ))
    sc = E.Scenario(
        id=sc_id, project_id=project.id, name=data["name"], description=data.get("description", ""),
        probability=data.get("probability", 1.0), is_default=data.get("is_default", False),
        demand_multiplier=data.get("demand_multiplier", 1.0),
        pipeline_capacity_multiplier=data.get("pipeline_capacity_multiplier", 1.0),
        transport_cost_multiplier=data.get("transport_cost_multiplier", 1.0),
        storage_restriction_multiplier=data.get("storage_restriction_multiplier", 1.0),
        parameters=parameters,
    )
    project.scenarios.append(sc)
    save_project(project)
    return sc


def update_scenario(project: E.Project, scenario_id: int, data: dict) -> E.Scenario:
    sc = next((s for s in project.scenarios if s.id == scenario_id), None)
    if sc is None:
        raise NotFound(f"Scenario {scenario_id} not found in project {project.id}")
    editable = ["name", "description", "probability", "is_default", "demand_multiplier",
                "pipeline_capacity_multiplier", "transport_cost_multiplier", "storage_restriction_multiplier"]
    for f in editable:
        if f in data:
            setattr(sc, f, data[f])
    save_project(project)
    return sc


def delete_scenario(project: E.Project, scenario_id: int):
    idx = next((i for i, s in enumerate(project.scenarios) if s.id == scenario_id), None)
    if idx is None:
        raise NotFound(f"Scenario {scenario_id} not found in project {project.id}")
    project.scenarios.pop(idx)
    save_project(project)


# -------------------------------------------------------- assumptions -----
# The Assumption Register (spec section 62): Parameter/Value/Unit/Source/Owner/
# Date/Confidence/Type for every planning number that isn't verified fact.
def add_assumption(project: E.Project, save: bool = True, **kwargs) -> E.Assumption:
    a = E.Assumption(id=project.next_id(), project_id=project.id, **kwargs)
    project.assumptions.append(a)
    if save:
        save_project(project)
    return a


def list_assumptions(project: E.Project) -> list:
    return project.assumptions


def update_assumption(project: E.Project, assumption_id: int, data: dict) -> E.Assumption:
    a = next((x for x in project.assumptions if x.id == assumption_id), None)
    if a is None:
        raise NotFound(f"Assumption {assumption_id} not found in project {project.id}")
    editable = ["entity_type", "entity_code", "parameter", "value", "unit", "source", "status", "confidence", "notes"]
    for f in editable:
        if f in data:
            setattr(a, f, data[f])
    save_project(project)
    return a


def delete_assumption(project: E.Project, assumption_id: int):
    idx = next((i for i, x in enumerate(project.assumptions) if x.id == assumption_id), None)
    if idx is None:
        raise NotFound(f"Assumption {assumption_id} not found in project {project.id}")
    project.assumptions.pop(idx)
    save_project(project)


# --------------------------------------------------------- run history ----
def save_run(project_id, scenario_id, run_type, solver_name, result) -> dict:
    run_id = _next_counter("run")
    run = {
        "id": run_id, "project_id": project_id, "scenario_id": scenario_id,
        "run_type": run_type, "solver_name": solver_name,
        "status": result.get("status"),
        "objective_value": result.get("objective_value") if result.get("objective_value") is not None else result.get("expected_cost"),
        "runtime_seconds": result.get("runtime_seconds"),
        "num_variables": result.get("num_variables"), "num_constraints": result.get("num_constraints"),
        "created_at": E.now_iso(),
        "result": result,
    }
    with open(_runs_path(project_id), "a") as f:
        f.write(json.dumps(run, default=str) + "\n")
    return run


def list_runs(project_id) -> list:
    path = _runs_path(project_id)
    if not os.path.exists(path):
        return []
    runs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    runs.sort(key=lambda r: r["created_at"], reverse=True)
    return runs


def get_run(run_id) -> dict:
    for path in glob.glob(os.path.join(_runs_dir(), "*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                run = json.loads(line)
                if run["id"] == run_id:
                    return run
    raise NotFound(f"Run {run_id} not found")
