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
        solver = pyo.SolverFactory(active.key, executable=active.executable) if active.executable \
            else pyo.SolverFactory(active.key)
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


def solve_network(nd: mb.NetworkData, penalty_base: float = None) -> dict:
    if penalty_base is None:
        penalty_base = nd.settings.get("unmet_demand_penalty_base", mb.DEFAULT_UNMET_PENALTY_BASE)
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
    contract_penalty_cost = sum(nd.sources[s]["take_or_pay_penalty_rate"] * val(m.shortfall[s])
                                 for s in getattr(m, "PS", [])) if hasattr(m, "shortfall") else 0.0

    result["objective_value"] = round(pyo.value(m.Obj), 4)
    result["cost_breakdown"] = {
        "infrastructure": round(fixed_cost, 4),
        "supply": round(supply_cost, 4),
        "transportation": round(sj_transport + jk_transport + kd_transport, 4),
        "shortage_penalty": round(shortage_cost, 4),
        "contract_penalties": round(contract_penalty_cost, 4),
    }
    if hasattr(m, "shortfall"):
        result["contract_shortfalls"] = [
            {"source": s, "contracted_quantity": nd.sources[s]["contracted_quantity"],
             "shortfall": val(m.shortfall[s]), "penalty_rate": nd.sources[s]["take_or_pay_penalty_rate"]}
            for s in m.PS if val(m.shortfall[s]) > 1e-6
        ]

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
                      penalty_base: float = None) -> dict:
    """Two-stage stochastic solve. Returns expected cost, worst-case cost,
    shared facility decisions, and a per-scenario cost/service breakdown."""
    if penalty_base is None:
        penalty_base = base_nd.settings.get("unmet_demand_penalty_base", mb.DEFAULT_UNMET_PENALTY_BASE)
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


def solve_multiperiod(nd: mb.NetworkData, months: list = None, penalty_base: float = None,
                       objective_mode: str = "standard", min_aggregate_service_level: float = None,
                       max_capex: float = None, objective_zone_subset: list = None,
                       zone_shortage_caps: dict = None) -> dict:
    """Solves the genuinely time-indexed multi-period MILP (mb.build_time_indexed_model)
    and returns a month-by-month breakdown - never a re-solved single-period snapshot
    dressed up as "multi-period" (see app/simulation/timeline.py for that older,
    explicitly-labeled simplification, which this supersedes for real planning use).

    objective_mode/min_aggregate_service_level/max_capex are passed straight through to
    build_time_indexed_model (spec section 22/84 investment analysis - see its docstring).
    result["total_cost"] is ALWAYS the real total cost (fixed+capex+supply+transport+
    shortage+storage), reconstructed from the solved flow values regardless of which
    objective the solver actually minimized - result["objective_value"] is the raw solved
    objective (capex-only or shortage-only for the investment modes, so read total_cost
    instead when comparing cost across modes)."""
    if months is None:
        months = nd.months or list(range(1, 13))
    if penalty_base is None:
        penalty_base = nd.settings.get("unmet_demand_penalty_base", mb.DEFAULT_UNMET_PENALTY_BASE)
    m = mb.build_time_indexed_model(nd, months, penalty_base=penalty_base, objective_mode=objective_mode,
                                     min_aggregate_service_level=min_aggregate_service_level, max_capex=max_capex,
                                     objective_zone_subset=objective_zone_subset, zone_shortage_caps=zone_shortage_caps)
    num_vars = sum(1 for _ in m.component_data_objects(pyo.Var))
    num_constraints = sum(1 for _ in m.component_data_objects(pyo.Constraint))

    active = get_active_solver()
    if not active.available:
        return {
            "status": "solver_unavailable", "solver_name": active.display_name,
            "num_variables": num_vars, "num_constraints": num_constraints,
            "runtime_seconds": 0, "objective_value": None,
        }

    status, runtime = _solve_with_active_solver(m)
    result = {
        "status": status, "solver_name": active.display_name,
        "num_variables": num_vars, "num_constraints": num_constraints,
        "runtime_seconds": round(runtime, 4), "objective_value": None,
        "months": list(months), "objective_mode": objective_mode,
    }
    if status != "optimal":
        return result

    def val(v):
        x = pyo.value(v, exception=False)
        return round(x, 4) if x is not None else 0.0

    S, J, K, D = list(nd.sources), list(nd.cgs), list(nd.stations), list(nd.demand_zones)
    C, JK, KD = list(m.C), list(m.JK), list(m.KD)

    def penalty_weight(d):
        pc = nd.priority_by_zone.get(d)
        return pc["penalty_weight"] if pc else 1.0

    fixed_cost_total = len(months) * (
        sum(nd.cgs[j]["fixed_operating_cost"] * val(m.y[j]) for j in J)
        + sum(nd.stations[k]["fixed_cost"] * val(m.z[k]) for k in K)
    )

    storage_on = nd.settings.get("enable_storage", False)
    total_expansion_capex = (sum(nd.cgs[j]["expansion_cost"] * val(m.e_cgs[j]) for j in J)
                              + sum(nd.stations[k]["expansion_cost"] * val(m.e_station[k]) for k in K))

    result["objective_value"] = round(pyo.value(m.Obj), 4)
    result["facilities"] = {
        "cgs": [{"code": j, "open": bool(round(val(m.y[j]))), "base_capacity": nd.cgs[j]["capacity"],
                 "expansion": val(m.e_cgs[j]),
                 "effective_capacity": round(nd.cgs[j]["capacity"] + val(m.e_cgs[j]), 4)} for j in J],
        "stations": [{"code": k, "open": bool(round(val(m.z[k]))), "base_capacity": nd.stations[k]["capacity"],
                      "expansion": val(m.e_station[k]),
                      "effective_capacity": round(nd.stations[k]["capacity"] + val(m.e_station[k]), 4)} for k in K],
    }
    result["expansion_capex"] = round(total_expansion_capex, 4)

    if storage_on:
        result["inventory_by_month"] = {
            j: {t: val(m.I[j, t]) for t in months} for j in J
        }

    monthly_breakdown = []
    flows_by_month = {}
    demand_by_month_node = []
    total_supply_cost = total_transport_cost = total_shortage_cost = total_storage_cost = 0.0

    for t in months:
        supply_used = sum(val(m.x[c, t]) for c in C)
        supply_cost = sum(nd.sources[nd.corridors[c]["origin"]]["supply_cost"] * val(m.x[c, t]) for c in C)
        sj_transport = sum(nd.corridors[c]["monthly_transport_cost"][t] * val(m.x[c, t]) for c in C)
        jk_transport = sum(nd.jk_cost[(j, k)] * val(m.w[j, k, t]) for (j, k) in JK)
        kd_transport = sum(nd.kd_cost[(k, d)] * val(m.v[k, d, t]) for (k, d) in KD)
        shortage_cost = sum(penalty_base * penalty_weight(d) * val(m.u[d, t]) for d in D)
        storage_cost_t = sum(nd.cgs[j]["storage_cost"] * val(m.I[j, t]) for j in J) if storage_on else 0.0
        month_demand = sum(nd.demand_zones[d]["monthly_demand"][t] for d in D)
        month_unmet = sum(val(m.u[d, t]) for d in D)
        month_allocated = month_demand - month_unmet
        month_supply_avail = sum(nd.sources[s]["monthly_availability"][t] for s in S)
        month_cost = supply_cost + sj_transport + jk_transport + kd_transport + shortage_cost + storage_cost_t

        total_supply_cost += supply_cost
        total_transport_cost += sj_transport + jk_transport + kd_transport
        total_shortage_cost += shortage_cost
        total_storage_cost += storage_cost_t

        monthly_breakdown.append({
            "month": t,
            "supply_available": round(month_supply_avail, 4),
            "supply_used": round(supply_used, 4),
            "demand": round(month_demand, 4),
            "allocated": round(month_allocated, 4),
            "shortage": round(month_unmet, 4),
            "service_level": round(month_allocated / month_demand, 4) if month_demand else 1.0,
            "cost": round(month_cost, 4),
            "surplus_deficit": round(month_supply_avail - month_demand, 4),
        })

        flows_by_month[t] = {
            "source_to_cgs": [{"from": nd.corridors[c]["origin"], "to": nd.corridors[c]["destination"],
                                "corridor": c, "flow": val(m.x[c, t])} for c in C if val(m.x[c, t]) > 1e-6],
            "cgs_to_station": [{"from": j, "to": k, "flow": val(m.w[j, k, t])} for (j, k) in JK if val(m.w[j, k, t]) > 1e-6],
            "station_to_demand": [{"from": k, "to": d, "flow": val(m.v[k, d, t])} for (k, d) in KD if val(m.v[k, d, t]) > 1e-6],
        }

        for d in D:
            dem = nd.demand_zones[d]["monthly_demand"][t]
            unmet = val(m.u[d, t])
            demand_by_month_node.append({
                "node": d, "month": t, "demand": round(dem, 4), "shortage": round(unmet, 4),
                "allocated": round(dem - unmet, 4),
                "service_level": round(1 - unmet / dem, 4) if dem else 1.0,
                "target_service_level": nd.demand_zones[d]["min_service_level"],
                "priority": (nd.priority_by_zone.get(d) or {}).get("name", "Unassigned"),
            })

    result["monthly_breakdown"] = monthly_breakdown
    result["flows_by_month"] = flows_by_month
    result["monthly_allocation"] = demand_by_month_node
    result["cost_breakdown"] = {
        "infrastructure": round(fixed_cost_total, 4),
        "expansion_capex": round(total_expansion_capex, 4),
        "supply": round(total_supply_cost, 4),
        "transportation": round(total_transport_cost, 4),
        "shortage_penalty": round(total_shortage_cost, 4),
        "storage": round(total_storage_cost, 4),
    }
    # always the real total cost, reconstructed from solved flows - accurate regardless
    # of objective_mode (which may have optimized for capex or shortage instead of cost)
    result["total_cost"] = round(fixed_cost_total + total_expansion_capex + total_supply_cost
                                  + total_transport_cost + total_shortage_cost + total_storage_cost, 4)

    total_demand = sum(row["demand"] for row in monthly_breakdown)
    total_shortage = sum(row["shortage"] for row in monthly_breakdown)
    result["kpis"] = {
        "total_demand": round(total_demand, 4),
        "total_shortage": round(total_shortage, 4),
        "overall_service_level": round(1 - total_shortage / total_demand, 4) if total_demand else 1.0,
        "months_with_shortage": sum(1 for row in monthly_breakdown if row["shortage"] > 1e-6),
        "horizon_months": len(months),
        "cgs_open_count": sum(1 for f in result["facilities"]["cgs"] if f["open"]),
        "station_open_count": sum(1 for f in result["facilities"]["stations"] if f["open"]),
        "total_expansion_capex": round(total_expansion_capex, 4),
    }

    return result


def solve_lexicographic(nd: mb.NetworkData, months: list = None, penalty_base: float = None) -> dict:
    """Lexicographic priority allocation (spec section 14, Mode B) - genuinely
    sequential, not just rank=1,2,3 weighting dressed up as lexicographic
    (the spec explicitly warns against that). Priority tiers are grouped by
    PriorityClass.rank (ascending = higher priority); one MILP solve per
    tier, in rank order:

      Stage 1: minimize Tier-1's total shortage alone.
      Stage 2: minimize Tier-2's total shortage, with Tier-1's shortage
               LOCKED at its stage-1 optimum (zone_shortage_caps) - stage 2
               can never claw back capacity from tier 1 to do better for itself.
      ...and so on through every tier, then a FINAL stage that minimizes
      total cost (the standard objective) with every tier's shortage locked,
      so flows/facility choices among otherwise-equivalent options are the
      genuinely cheapest ones rather than arbitrary.

    Demand zones with no priority_class assigned are treated as their own
    lowest-priority tier, optimized last, after every configured tier.
    """
    if months is None:
        months = nd.months or list(range(1, 13))

    tiers = {}  # rank -> {"name": ..., "zones": [...]}
    unassigned_zones = []
    for d, pc in nd.priority_by_zone.items():
        if pc:
            tiers.setdefault(pc["rank"], {"name": pc["name"], "zones": []})["zones"].append(d)
        else:
            unassigned_zones.append(d)

    ordered_ranks = sorted(tiers.keys())
    stages = [{"rank": r, "name": tiers[r]["name"], "zones": tiers[r]["zones"]} for r in ordered_ranks]
    if unassigned_zones:
        stages.append({"rank": None, "name": "Unassigned", "zones": unassigned_zones})

    zone_shortage_caps = {}
    stage_results = []
    last_result = None
    for stage in stages:
        result = solve_multiperiod(nd, months=months, penalty_base=penalty_base,
                                    objective_mode="zone_shortage_min", objective_zone_subset=stage["zones"],
                                    zone_shortage_caps=dict(zone_shortage_caps) if zone_shortage_caps else None)
        last_result = result
        if result["status"] != "optimal":
            return {"status": result["status"], "failed_stage": stage["name"], "diagnostics": result.get("diagnostics"),
                    "stages": stage_results}

        tier_shortage = sum(row["shortage"] for row in result["monthly_allocation"] if row["node"] in stage["zones"])
        # lock this tier's total horizon shortage at its optimum (a hair of slack for solver tolerance)
        per_zone_totals = {}
        for row in result["monthly_allocation"]:
            if row["node"] in stage["zones"]:
                per_zone_totals[row["node"]] = per_zone_totals.get(row["node"], 0.0) + row["shortage"]
        for zcode, total in per_zone_totals.items():
            zone_shortage_caps[zcode] = round(total + 1e-4, 6)

        stage_results.append({
            "tier": stage["name"], "rank": stage["rank"], "zones": stage["zones"],
            "total_shortage": round(tier_shortage, 4),
        })

    # final stage: minimize real total cost with every tier's shortage locked in
    final = solve_multiperiod(nd, months=months, penalty_base=penalty_base, objective_mode="standard",
                               zone_shortage_caps=zone_shortage_caps)
    if final["status"] != "optimal":
        return {"status": final["status"], "failed_stage": "final cost minimization",
                "diagnostics": final.get("diagnostics"), "stages": stage_results}

    final["lexicographic_stages"] = stage_results
    final["policy"] = "lexicographic"
    return final


def solve_rolling_horizon(nd: mb.NetworkData, months: list = None, window_size: int = 3,
                           penalty_base: float = None) -> dict:
    """Rolling horizon re-optimization (spec section 25) - genuinely distinct
    from the static 12-month plan (solve_multiperiod), not the same solve
    relabeled. At each month t0, solves the time-indexed MILP over a
    `window_size`-month look-ahead window [t0 .. t0+window_size-1] (forecast),
    but only COMMITS the first month's decision (execute), then advances to
    t0+1 and re-solves from there - so a later month's plan can always
    react to what the earlier month actually committed to, the way a real
    rolling-horizon planner works.

    Facility open/close decisions are irreversible in reality (you don't
    un-build a CGS) - once a candidate facility opens in an earlier window's
    solve, it's forced to stay open ("existing") in every later window.

    This implementation does not yet support genuinely different forecast-
    vs-actual data per window (spec section 31's Forecast/Actual concept is
    separate - see engine.forecast_vs_actual) - every window re-solves
    against the SAME nd.monthly_availability/monthly_demand a static plan
    would use. The rolling mechanism itself (partial horizon visibility +
    irreversible facility commitments + sequential re-solve) is real; what's
    not yet wired in is a way to feed it updated/actual data mid-run.
    """
    import copy
    if months is None:
        months = nd.months or list(range(1, 13))

    opened_cgs, opened_stations = set(), set()
    committed_months = []
    window_solver_stats = []

    for i, t0 in enumerate(months):
        window = months[i:i + window_size]
        nd_window = copy.deepcopy(nd)
        for j in opened_cgs:
            nd_window.cgs[j]["infra_status"] = "existing"
        for k in opened_stations:
            nd_window.stations[k]["infra_status"] = "existing"

        result = solve_multiperiod(nd_window, months=window, penalty_base=penalty_base)
        window_solver_stats.append({"window_start": t0, "window": window, "status": result["status"]})
        if result["status"] != "optimal":
            return {
                "status": result["status"], "policy": "rolling_horizon", "window_size": window_size,
                "failed_at_month": t0, "committed_months": committed_months,
                "diagnostics": result.get("diagnostics"),
            }

        committed_row = next(r for r in result["monthly_breakdown"] if r["month"] == t0)
        committed_months.append(committed_row)
        opened_cgs |= {f["code"] for f in result["facilities"]["cgs"] if f["open"]}
        opened_stations |= {f["code"] for f in result["facilities"]["stations"] if f["open"]}

    total_demand = sum(r["demand"] for r in committed_months)
    total_shortage = sum(r["shortage"] for r in committed_months)
    total_cost = sum(r["cost"] for r in committed_months)
    return {
        "status": "optimal", "policy": "rolling_horizon", "window_size": window_size,
        "months": list(months), "monthly_breakdown": committed_months,
        "opened_cgs": sorted(opened_cgs), "opened_stations": sorted(opened_stations),
        "total_cost": round(total_cost, 4),
        "kpis": {
            "total_demand": round(total_demand, 4), "total_shortage": round(total_shortage, 4),
            "overall_service_level": round(1 - total_shortage / total_demand, 4) if total_demand else 1.0,
            "months_with_shortage": sum(1 for r in committed_months if r["shortage"] > 1e-6),
            "horizon_months": len(committed_months),
            "cgs_open_count": len(opened_cgs), "station_open_count": len(opened_stations),
        },
        "window_solves": window_solver_stats,
    }


def solve_min_investment_for_service(nd: mb.NetworkData, months: list = None, target_service_level: float = 0.95,
                                      penalty_base: float = None) -> dict:
    """Investment decision support (spec section 22/84): "what is the minimum
    CAPEX needed to hit a target service level?" - minimizes expansion CAPEX
    subject to a horizon-wide aggregate service-level floor. If infeasible,
    no combination of expansion up to each facility's own max_expansion can
    reach the target - the caller should raise max_expansion or check for a
    structural bottleneck (disconnected zone, unfed CGS) instead."""
    return solve_multiperiod(nd, months=months, penalty_base=penalty_base, objective_mode="capex_min",
                              min_aggregate_service_level=target_service_level)


def solve_max_service_for_budget(nd: mb.NetworkData, months: list = None, budget: float = 0.0,
                                  penalty_base: float = None) -> dict:
    """Investment decision support (spec section 22/84): "what's the best
    service level I can reach for a fixed budget?" - minimizes total unmet
    demand subject to a CAPEX cap. budget=0 (the default) correctly answers
    "with no investment at all", not an error case."""
    return solve_multiperiod(nd, months=months, penalty_base=penalty_base, objective_mode="shortage_min",
                              max_capex=budget)
