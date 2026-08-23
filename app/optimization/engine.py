"""
Solves a network model built by model_builder.build_model() and returns a
plain-dict result payload (JSON-serializable) with the objective broken
into its components, per-facility and per-arc results, and solver stats.

Never hard-codes a cost, facility decision, or KPI - everything here is
read back off the solved Pyomo variables.
"""
import time
import pyomo.environ as pyo
from app.optimization.solver_registry import get_active_solver
from app.optimization import model_builder as mb


class SolveError(Exception):
    pass


def _solve_with_active_solver(m: pyo.ConcreteModel):
    """Returns (status_str, runtime_seconds). status_str in
    {'optimal','infeasible','unbounded','error'}."""
    active = get_active_solver()
    start = time.time()

    if active.key == "highs":
        from pyomo.contrib.appsi.solvers import Highs
        solver = Highs()
        solver.highs_options = {"output_flag": False}
        solver.config.load_solution = False
        result = solver.solve(m)
        runtime = time.time() - start
        from pyomo.contrib.appsi.base import TerminationCondition as TC
        tc = result.termination_condition
        if tc == TC.optimal:
            result.solution_loader.load_vars()
            return "optimal", runtime
        if tc == TC.infeasible:
            return "infeasible", runtime
        if tc == TC.unbounded:
            return "unbounded", runtime
        return "error", runtime

    elif active.key in ("cbc", "gurobi", "cplex"):
        solver = pyo.SolverFactory(active.key)
        result = solver.solve(m, tee=False)
        runtime = time.time() - start
        tc = result.solver.termination_condition
        if tc == pyo.TerminationCondition.optimal:
            return "optimal", runtime
        if tc == pyo.TerminationCondition.infeasible:
            return "infeasible", runtime
        if tc == pyo.TerminationCondition.unbounded:
            return "unbounded", runtime
        return "error", runtime

    else:
        raise SolveError("No optimization solver is available. Install HiGHS (pip install highspy) or CBC.")


def solve_network(nd: mb.NetworkData, penalty_base: float = mb.DEFAULT_UNMET_PENALTY_BASE) -> dict:
    m = mb.build_model(nd, penalty_base=penalty_base)
    num_vars = sum(1 for _ in m.component_data_objects(pyo.Var))
    num_constraints = sum(1 for _ in m.component_data_objects(pyo.Constraint))

    active = get_active_solver()
    if not active.available:
        return {
            "status": "solver_unavailable",
            "solver_name": active.display_name,
            "num_variables": num_vars, "num_constraints": num_constraints,
            "runtime_seconds": 0, "objective_value": None,
        }

    status, runtime = _solve_with_active_solver(m)

    result = {
        "status": status,
        "solver_name": active.display_name,
        "num_variables": num_vars,
        "num_constraints": num_constraints,
        "runtime_seconds": round(runtime, 4),
        "objective_value": None,
        "cost_breakdown": None,
        "facilities": None,
        "flows": None,
        "demand_results": None,
        "utilization": None,
    }

    if status != "optimal":
        return result

    def val(v):
        x = pyo.value(v, exception=False)
        return round(x, 4) if x is not None else 0.0

    S, J, K, D = list(nd.sources), list(nd.cgs), list(nd.stations), list(nd.demand_zones)
    SJ, JK, KD = list(m.SJ), list(m.JK), list(m.KD)
    corridor_by_sj = {(c["origin"], c["destination"]): c for c in nd.corridors.values()}

    def penalty_weight(d):
        pc = nd.priority_by_zone.get(d)
        return pc["penalty_weight"] if pc else 1.0

    fixed_cost = sum(nd.cgs[j]["fixed_operating_cost"] * val(m.y[j]) for j in J) \
               + sum(nd.stations[k]["fixed_cost"] * val(m.z[k]) for k in K)
    supply_cost = sum(nd.sources[s]["supply_cost"] * val(m.x[s, j]) for (s, j) in SJ)
    sj_transport = sum(corridor_by_sj[(s, j)]["transport_cost"] * val(m.x[s, j]) for (s, j) in SJ)
    jk_transport = sum(nd.jk_cost[(j, k)] * val(m.w[j, k]) for (j, k) in JK)
    kd_transport = sum(nd.kd_cost[(k, d)] * val(m.v[k, d]) for (k, d) in KD)
    shortage_cost = sum(penalty_base * penalty_weight(d) * val(m.u[d]) for d in D)

    result["objective_value"] = round(pyo.value(m.Obj), 4)
    result["cost_breakdown"] = {
        "infrastructure": round(fixed_cost, 4),
        "supply": round(supply_cost, 4),
        "transportation": round(sj_transport + jk_transport + kd_transport, 4),
        "shortage_penalty": round(shortage_cost, 4),
    }

    result["facilities"] = {
        "cgs": [{"code": j, "open": bool(round(val(m.y[j]))), "infra_status": nd.cgs[j]["infra_status"],
                 "capacity": nd.cgs[j]["capacity"],
                 "inbound_flow": round(sum(val(m.x[s, jj]) for (s, jj) in SJ if jj == j), 4)}
                for j in J],
        "stations": [{"code": k, "open": bool(round(val(m.z[k]))), "infra_status": nd.stations[k]["infra_status"],
                      "capacity": nd.stations[k]["capacity"],
                      "inbound_flow": round(sum(val(m.w[j, kk]) for (j, kk) in JK if kk == k), 4)}
                     for k in K],
    }

    for f in result["facilities"]["cgs"]:
        f["utilization"] = round(f["inbound_flow"] / f["capacity"], 4) if f["capacity"] else 0.0
    for f in result["facilities"]["stations"]:
        f["utilization"] = round(f["inbound_flow"] / f["capacity"], 4) if f["capacity"] else 0.0

    result["flows"] = {
        "source_to_cgs": [{"from": s, "to": j, "flow": val(m.x[s, j])} for (s, j) in SJ if val(m.x[s, j]) > 1e-6],
        "cgs_to_station": [{"from": j, "to": k, "flow": val(m.w[j, k])} for (j, k) in JK if val(m.w[j, k]) > 1e-6],
        "station_to_demand": [{"from": k, "to": d, "flow": val(m.v[k, d])} for (k, d) in KD if val(m.v[k, d]) > 1e-6],
    }

    total_demand = sum(nd.demand_zones[d]["base_demand"] for d in D)
    total_unmet = sum(val(m.u[d]) for d in D)
    result["demand_results"] = [
        {"code": d, "demand": nd.demand_zones[d]["base_demand"], "unmet": val(m.u[d]),
         "fulfilment_pct": round(1 - (val(m.u[d]) / nd.demand_zones[d]["base_demand"]), 4) if nd.demand_zones[d]["base_demand"] else 1.0,
         "min_service_level": nd.demand_zones[d]["min_service_level"],
         "priority": (nd.priority_by_zone.get(d) or {}).get("name", "Unassigned")}
        for d in D
    ]

    total_source_supply_used = sum(val(m.x[s, j]) for (s, j) in SJ)
    total_source_capacity_avail = sum(nd.sources[s]["base_availability"] * nd.sources[s]["max_capacity"] for s in S)

    result["kpis"] = {
        "total_demand": round(total_demand, 4),
        "total_unmet_demand": round(total_unmet, 4),
        "demand_fulfilment_pct": round(1 - total_unmet / total_demand, 4) if total_demand else 1.0,
        "total_supply_available": round(total_source_capacity_avail, 4),
        "total_supply_used": round(total_source_supply_used, 4),
        "cgs_open_count": sum(1 for f in result["facilities"]["cgs"] if f["open"]),
        "cgs_total_count": len(J),
        "station_open_count": sum(1 for f in result["facilities"]["stations"] if f["open"]),
        "station_total_count": len(K),
        "avg_cgs_utilization": round(sum(f["utilization"] for f in result["facilities"]["cgs"] if f["open"]) /
                                      max(1, sum(1 for f in result["facilities"]["cgs"] if f["open"])), 4),
        "avg_station_utilization": round(sum(f["utilization"] for f in result["facilities"]["stations"] if f["open"]) /
                                          max(1, sum(1 for f in result["facilities"]["stations"] if f["open"])), 4),
    }

    return result


def solve_stochastic(base_nd: mb.NetworkData, scenario_nds: dict, probabilities: dict,
                      penalty_base: float = mb.DEFAULT_UNMET_PENALTY_BASE) -> dict:
    """Two-stage stochastic solve. Returns expected cost, worst-case cost,
    shared facility decisions, and a per-scenario cost/service breakdown."""
    m = mb.build_stochastic_model(base_nd, scenario_nds, probabilities, penalty_base)
    num_vars = sum(1 for _ in m.component_data_objects(pyo.Var))
    num_constraints = sum(1 for _ in m.component_data_objects(pyo.Constraint))

    active = get_active_solver()
    if not active.available:
        return {"status": "solver_unavailable", "solver_name": active.display_name}

    status, runtime = _solve_with_active_solver(m)
    result = {
        "status": status, "solver_name": active.display_name,
        "num_variables": num_vars, "num_constraints": num_constraints,
        "runtime_seconds": round(runtime, 4),
    }
    if status != "optimal":
        return result

    def val(v):
        x = pyo.value(v, exception=False)
        return round(x, 4) if x is not None else 0.0

    J, K = list(base_nd.cgs), list(base_nd.stations)
    SJ = list(m.SJ)
    JK = list(m.JK)
    KD = list(m.KD)
    D = list(base_nd.demand_zones)
    T = list(scenario_nds.keys())

    fixed_cost = sum(base_nd.cgs[j]["fixed_operating_cost"] * val(m.y[j]) for j in J) \
               + sum(base_nd.stations[k]["fixed_cost"] * val(m.z[k]) for k in K)

    result["expected_cost"] = round(pyo.value(m.Obj), 4)
    result["facilities"] = {
        "cgs": [{"code": j, "open": bool(round(val(m.y[j])))} for j in J],
        "stations": [{"code": k, "open": bool(round(val(m.z[k])))} for k in K],
    }

    def penalty_weight(nd, d):
        pc = nd.priority_by_zone.get(d)
        return pc["penalty_weight"] if pc else 1.0

    scenario_results = []
    worst_case_cost = fixed_cost
    for t in T:
        nd = scenario_nds[t]
        corridor_by_sj = {(c["origin"], c["destination"]): c for c in nd.corridors.values()}
        supply_cost = sum(nd.sources[s]["supply_cost"] * val(m.x[s, j, t]) for (s, j) in SJ)
        sj_transport = sum(corridor_by_sj[(s, j)]["transport_cost"] * val(m.x[s, j, t]) for (s, j) in SJ)
        jk_transport = sum(nd.jk_cost[(j, k)] * val(m.w[j, k, t]) for (j, k) in JK)
        kd_transport = sum(nd.kd_cost[(k, d)] * val(m.v[k, d, t]) for (k, d) in KD)
        total_unmet = sum(val(m.u[d, t]) for d in D)
        shortage_cost = sum(penalty_base * penalty_weight(nd, d) * val(m.u[d, t]) for d in D)
        scenario_total_cost = fixed_cost + supply_cost + sj_transport + jk_transport + kd_transport + shortage_cost
        total_demand = sum(nd.demand_zones[d]["base_demand"] for d in D)
        worst_case_cost = max(worst_case_cost, scenario_total_cost)
        scenario_results.append({
            "scenario": t,
            "probability": probabilities[t],
            "total_cost": round(scenario_total_cost, 4),
            "total_demand": round(total_demand, 4),
            "total_unmet": round(total_unmet, 4),
            "fulfilment_pct": round(1 - total_unmet / total_demand, 4) if total_demand else 1.0,
        })

    result["worst_case_cost"] = round(worst_case_cost, 4)
    result["scenario_results"] = scenario_results
    return result
