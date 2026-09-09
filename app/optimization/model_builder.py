"""
Builds a Pyomo ConcreteModel from a Project's network entities.

Nothing here assumes a fixed number of sources/CGS/stations/demand
zones - the Sets are built from whatever rows exist. This module is
deliberately separate from solving (engine.py) and from scenario
resolution (services/scenario_service.py) so each stays testable on
its own.

Arc conventions:
  SJ (source -> CGS):    from explicit Corridor rows (origin_type=source, destination_type=cgs)
  JK (CGS -> station):   dense - every active CGS can feed every active station.
                         There is no dedicated "CGS-station corridor" entity in the
                         Phase 1 schema, so capacity on this hop is governed only by
                         facility capacities, and cost is distance-based (haversine)
                         when both ends have coordinates, else a flat default.
  KD (station -> demand): a station can serve a demand zone only if the zone falls
                         within the station's configured service radius.
"""
import math
from dataclasses import dataclass, field
import pyomo.environ as pyo

DEFAULT_JK_COST_PER_KM = 0.02      # currency / gas_unit / km, used when no Corridor entity exists for this hop
DEFAULT_JK_FLAT_COST = 3.0         # fallback when coordinates are missing
DEFAULT_KD_COST_PER_KM = 0.03
DEFAULT_KD_FLAT_COST = 2.0
DEFAULT_UNMET_PENALTY_BASE = 50.0  # currency / unit unmet demand, scaled by priority weight


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def silent_hours_fraction(start, end):
    """Returns the fraction of a 24h day left available for delivery once a
    [start, end) 'silent hours' window is excluded (wraps past midnight if
    end < start), or None if no window is configured. Used to throttle how
    much of a household demand zone's daily volume a station can push
    through, since compressing the same volume into fewer hours needs more
    instantaneous capacity, not the capacity itself."""
    if start is None or end is None:
        return None
    duration = (end - start) % 24
    if duration == 0:
        duration = 24  # start==end is treated as "silent all day"
    available = max(24 - duration, 0.5)  # keep a sliver open so this throttles rather than fully zeroes the arc
    return available / 24.0


@dataclass
class NetworkData:
    """Plain-python snapshot of a project's network, with scenario overrides
    already applied. Kept separate from the SQLAlchemy objects so the
    optimizer never touches the DB session mid-solve."""
    sources: dict = field(default_factory=dict)      # code -> dict
    cgs: dict = field(default_factory=dict)
    stations: dict = field(default_factory=dict)
    demand_zones: dict = field(default_factory=dict)
    corridors: dict = field(default_factory=dict)     # code -> dict (SJ arcs)
    priority_by_zone: dict = field(default_factory=dict)  # zone_code -> PriorityClass dict or None

    jk_arcs: list = field(default_factory=list)   # list of (j, k)
    kd_arcs: list = field(default_factory=list)   # list of (k, d)
    jk_cost: dict = field(default_factory=dict)
    kd_cost: dict = field(default_factory=dict)
    kd_capacity_cap: dict = field(default_factory=dict)  # (k, d) -> extra cap, only set under the silent-hours module

    # project-level toggles + dynamic global rates (see Project dataclass for docs).
    # Always populated by snapshot_network(); defaults here only cover NetworkData
    # built by hand (e.g. tests), and reproduce the platform's original behavior.
    settings: dict = field(default_factory=lambda: {
        "enable_pressure_model": False, "enable_silent_hours": False,
        "enable_penalty_clauses": False, "enable_travel_distance_limit": False,
        "unmet_demand_penalty_base": DEFAULT_UNMET_PENALTY_BASE,
        "jk_cost_per_km": DEFAULT_JK_COST_PER_KM, "jk_flat_cost": DEFAULT_JK_FLAT_COST,
        "kd_cost_per_km": DEFAULT_KD_COST_PER_KM, "kd_flat_cost": DEFAULT_KD_FLAT_COST,
        "pressure_drop_rate_bar_per_km": 0.15,
    })


def snapshot_network(project) -> NetworkData:
    nd = NetworkData()
    nd.settings = {
        "enable_pressure_model": bool(getattr(project, "enable_pressure_model", False)),
        "enable_silent_hours": bool(getattr(project, "enable_silent_hours", False)),
        "enable_penalty_clauses": bool(getattr(project, "enable_penalty_clauses", False)),
        "enable_travel_distance_limit": bool(getattr(project, "enable_travel_distance_limit", False)),
        "unmet_demand_penalty_base": getattr(project, "unmet_demand_penalty_base", DEFAULT_UNMET_PENALTY_BASE) or DEFAULT_UNMET_PENALTY_BASE,
        "jk_cost_per_km": getattr(project, "jk_cost_per_km", DEFAULT_JK_COST_PER_KM) or DEFAULT_JK_COST_PER_KM,
        "jk_flat_cost": getattr(project, "jk_flat_cost", DEFAULT_JK_FLAT_COST) or DEFAULT_JK_FLAT_COST,
        "kd_cost_per_km": getattr(project, "kd_cost_per_km", DEFAULT_KD_COST_PER_KM) or DEFAULT_KD_COST_PER_KM,
        "kd_flat_cost": getattr(project, "kd_flat_cost", DEFAULT_KD_FLAT_COST) or DEFAULT_KD_FLAT_COST,
        "pressure_drop_rate_bar_per_km": getattr(project, "pressure_drop_rate_bar_per_km", 0.15) or 0.0,
    }

    for s in project.sources:
        if s.is_active:
            nd.sources[s.code] = {
                "max_capacity": s.max_capacity or 0,
                "base_availability": s.base_availability if s.base_availability is not None else 1.0,
                "min_operational_qty": s.min_operational_qty or 0,
                "supply_cost": s.supply_cost or 0,
                "reliability": s.reliability if s.reliability is not None else 1.0,
                "contracted_quantity": getattr(s, "contracted_quantity", 0) or 0,
                "is_upstream_gail": getattr(s, "is_upstream_gail", False),
                "interruption_probability": getattr(s, "interruption_probability", 0.0) or 0.0,
                "price_escalation_pct": getattr(s, "price_escalation_pct", 0.0) or 0.0,
                "take_or_pay_penalty_rate": getattr(s, "take_or_pay_penalty_rate", 0.0) or 0.0,
                "delivery_pressure_bar": getattr(s, "delivery_pressure_bar", None),
            }
    for c in project.cgs_list:
        if c.is_active:
            nd.cgs[c.code] = {
                "capacity": c.capacity or 0,
                "fixed_operating_cost": c.fixed_operating_cost or 0,
                "expansion_cost": c.expansion_cost or 0,
                "max_expansion": c.max_expansion or 0,
                "infra_status": c.infra_status,
                "latitude": c.latitude, "longitude": c.longitude,
                "discharge_pressure_bar": getattr(c, "discharge_pressure_bar", None),
                "infrastructure_escalation_pct": getattr(c, "infrastructure_escalation_pct", 0.0) or 0.0,
            }
    for st in project.stations:
        if st.is_active:
            nd.stations[st.code] = {
                "capacity": st.capacity or 0,
                "fixed_cost": st.fixed_cost or 0,
                "expansion_cost": st.expansion_cost or 0,
                "infra_status": st.infra_status,
                "latitude": st.latitude, "longitude": st.longitude,
                "service_radius_km": st.demand_service_radius_km or 0,
                "min_inlet_pressure_bar": getattr(st, "min_inlet_pressure_bar", None),
                "dispensing_pressure_bar": getattr(st, "dispensing_pressure_bar", None),
                "infrastructure_escalation_pct": getattr(st, "infrastructure_escalation_pct", 0.0) or 0.0,
            }
    for d in project.demand_zones:
        nd.demand_zones[d.code] = {
            "base_demand": d.base_demand or 0,
            "growth_rate": d.growth_rate or 0,
            "min_service_level": d.min_service_level if d.min_service_level is not None else 0.7,
            "max_service_level": d.max_service_level if d.max_service_level is not None else 1.0,
            "latitude": d.latitude, "longitude": d.longitude,
            "demand_type": getattr(d, "demand_type", "Mixed"),
            "min_required_pressure_bar": getattr(d, "min_required_pressure_bar", 0.0) or 0.0,
            "max_travel_distance_km": getattr(d, "max_travel_distance_km", None),
            "silent_hours_start": getattr(d, "silent_hours_start", None),
            "silent_hours_end": getattr(d, "silent_hours_end", None),
            "demand_variability_pct": getattr(d, "demand_variability_pct", 0.0) or 0.0,
        }
        nd.priority_by_zone[d.code] = d.priority_class.to_dict() if d.priority_class else None

    for cor in project.corridors:
        if cor.is_active and cor.origin_type == "source" and cor.destination_type == "cgs":
            if cor.origin_code in nd.sources and cor.destination_code in nd.cgs:
                nd.corridors[cor.code] = {
                    "origin": cor.origin_code, "destination": cor.destination_code,
                    "capacity": cor.capacity or 0, "transport_cost": cor.transport_cost or 0,
                    "loss_pct": cor.loss_pct or 0, "pipeline_type": cor.pipeline_type,
                    "cost_variation_pct": getattr(cor, "cost_variation_pct", 0.0) or 0.0,
                }

    jk_cost_per_km = nd.settings["jk_cost_per_km"]
    jk_flat_cost = nd.settings["jk_flat_cost"]
    kd_cost_per_km = nd.settings["kd_cost_per_km"]
    kd_flat_cost = nd.settings["kd_flat_cost"]
    pressure_model_on = nd.settings["enable_pressure_model"]
    drop_rate = nd.settings["pressure_drop_rate_bar_per_km"]

    # dense CGS -> station arcs - gated by pressure feasibility when the
    # pressure module is enabled (a station can't be fed if the CGS's
    # discharge pressure, net of distance-based drop, falls below what the
    # station needs to operate its compressors)
    for j, jinfo in nd.cgs.items():
        for k, kinfo in nd.stations.items():
            dist = haversine(jinfo.get("latitude"), jinfo.get("longitude"), kinfo.get("latitude"), kinfo.get("longitude"))
            cost = dist * jk_cost_per_km if dist is not None else jk_flat_cost
            if pressure_model_on and dist is not None:
                discharge = jinfo.get("discharge_pressure_bar")
                min_inlet = kinfo.get("min_inlet_pressure_bar")
                if discharge is not None and min_inlet is not None:
                    delivered = discharge - drop_rate * dist
                    if delivered < min_inlet:
                        continue  # pressure would arrive too low - this CGS cannot feed this station
            nd.jk_arcs.append((j, k))
            nd.jk_cost[(j, k)] = cost

    # station -> demand arcs, gated by service radius (and, when enabled,
    # the zone's own travel-distance tolerance and minimum required pressure)
    for k, kinfo in nd.stations.items():
        for d, dinfo in nd.demand_zones.items():
            dist = haversine(kinfo.get("latitude"), kinfo.get("longitude"), dinfo.get("latitude"), dinfo.get("longitude"))
            radius = kinfo.get("service_radius_km") or 0
            if nd.settings["enable_travel_distance_limit"] and dinfo.get("max_travel_distance_km") is not None:
                radius = min(radius, dinfo["max_travel_distance_km"])
            if dist is None:
                # no coordinates on one side - allow the arc (can't geofence it) but flag via flat cost
                nd.kd_arcs.append((k, d))
                nd.kd_cost[(k, d)] = kd_flat_cost
            elif dist <= radius:
                if pressure_model_on:
                    dispensing = kinfo.get("dispensing_pressure_bar")
                    required = dinfo.get("min_required_pressure_bar") or 0
                    if dispensing is not None and required > 0:
                        delivered = dispensing - drop_rate * dist
                        if delivered < required:
                            continue  # can't guarantee this zone's required pressure from this station
                nd.kd_arcs.append((k, d))
                nd.kd_cost[(k, d)] = dist * kd_cost_per_km

            if (k, d) in nd.kd_cost and nd.settings["enable_silent_hours"]:
                frac = silent_hours_fraction(dinfo.get("silent_hours_start"), dinfo.get("silent_hours_end"))
                if frac is not None:
                    nd.kd_capacity_cap[(k, d)] = kinfo["capacity"] * frac

    return nd


def apply_overrides(nd: NetworkData, overrides: dict) -> NetworkData:
    """Returns a NEW NetworkData with scenario/what-if overrides applied.
    `overrides` keys (all optional):
      source_availability: {code: factor}            replaces base_availability
      demand_multiplier: float                        applied to every zone's demand
      demand_zone_multiplier: {code: factor}           on top of demand_multiplier
      corridor_capacity_multiplier: float              applied to every SJ corridor
      transport_cost_multiplier: float                 applied to SJ transport cost
      facility_cost_multiplier: float                  applied to fixed costs (CGS+station)
      service_level_override: float                    replaces every zone's min_service_level
      inactive_corridors: [codes]                       zero-capacity (pipeline outage)
      inactive_cgs: [codes]                             force closed
      inactive_stations: [codes]                        force closed
    """
    import copy
    nd2 = copy.deepcopy(nd)
    ov = overrides or {}

    src_avail = ov.get("source_availability", {})
    for code, s in nd2.sources.items():
        if code in src_avail:
            s["base_availability"] = src_avail[code]

    dm = ov.get("demand_multiplier", 1.0)
    zone_mult = ov.get("demand_zone_multiplier", {})
    for code, d in nd2.demand_zones.items():
        mult = dm * zone_mult.get(code, 1.0)
        d["base_demand"] = d["base_demand"] * mult

    if "service_level_override" in ov and ov["service_level_override"] is not None:
        for d in nd2.demand_zones.values():
            d["min_service_level"] = ov["service_level_override"]

    cap_mult = ov.get("corridor_capacity_multiplier", 1.0)
    cost_mult = ov.get("transport_cost_multiplier", 1.0)
    for c in nd2.corridors.values():
        c["capacity"] = c["capacity"] * cap_mult
        c["transport_cost"] = c["transport_cost"] * cost_mult

    fac_mult = ov.get("facility_cost_multiplier", 1.0)
    for c in nd2.cgs.values():
        c["fixed_operating_cost"] = c["fixed_operating_cost"] * fac_mult
    for s in nd2.stations.values():
        s["fixed_cost"] = s["fixed_cost"] * fac_mult

    for code in ov.get("inactive_corridors", []):
        if code in nd2.corridors:
            nd2.corridors[code]["capacity"] = 0

    for code in ov.get("inactive_cgs", []):
        nd2.cgs.pop(code, None)
        nd2.jk_arcs = [(j, k) for (j, k) in nd2.jk_arcs if j != code]

    for code in ov.get("inactive_stations", []):
        nd2.stations.pop(code, None)
        nd2.jk_arcs = [(j, k) for (j, k) in nd2.jk_arcs if k != code]
        nd2.kd_arcs = [(k, d) for (k, d) in nd2.kd_arcs if k != code]

    return nd2


def build_model(nd: NetworkData, penalty_base: float = None) -> pyo.ConcreteModel:
    if penalty_base is None:
        penalty_base = nd.settings.get("unmet_demand_penalty_base", DEFAULT_UNMET_PENALTY_BASE)
    m = pyo.ConcreteModel(name="CNG_Network_Design")

    S = list(nd.sources.keys())
    J = list(nd.cgs.keys())
    K = list(nd.stations.keys())
    D = list(nd.demand_zones.keys())
    SJ = [(c["origin"], c["destination"]) for c in nd.corridors.values()]
    JK = nd.jk_arcs
    KD = nd.kd_arcs

    m.S, m.J, m.K, m.D = pyo.Set(initialize=S), pyo.Set(initialize=J), pyo.Set(initialize=K), pyo.Set(initialize=D)
    m.SJ = pyo.Set(initialize=SJ, dimen=2)
    m.JK = pyo.Set(initialize=JK, dimen=2)
    m.KD = pyo.Set(initialize=KD, dimen=2)

    m.y = pyo.Var(m.J, domain=pyo.Binary)
    m.z = pyo.Var(m.K, domain=pyo.Binary)
    m.x = pyo.Var(m.SJ, domain=pyo.NonNegativeReals)
    m.w = pyo.Var(m.JK, domain=pyo.NonNegativeReals)
    m.v = pyo.Var(m.KD, domain=pyo.NonNegativeReals)
    m.u = pyo.Var(m.D, domain=pyo.NonNegativeReals)

    # force existing facilities open, forbid arcs at absent facilities
    for j in J:
        if nd.cgs[j]["infra_status"] == "existing":
            m.y[j].fix(1)
    for k in K:
        if nd.stations[k]["infra_status"] == "existing":
            m.z[k].fix(1)

    corridor_by_sj = {(c["origin"], c["destination"]): c for c in nd.corridors.values()}

    def penalty_weight(d):
        pc = nd.priority_by_zone.get(d)
        return pc["penalty_weight"] if pc else 1.0

    # take-or-pay contract penalty clauses (opt-in): sources with both the
    # project's penalty-clause module enabled and their own
    # take_or_pay_penalty_rate > 0 get a shortfall variable measuring how far
    # actual offtake falls below their contracted_quantity, penalized in the
    # objective - the contractual reality that under-lifting a take-or-pay
    # contract still costs money even though less gas was actually taken.
    penalty_clauses_on = nd.settings.get("enable_penalty_clauses", False)
    penalized_sources = [s for s in S if penalty_clauses_on and nd.sources[s].get("take_or_pay_penalty_rate", 0) > 0
                          and nd.sources[s].get("contracted_quantity", 0) > 0]
    if penalized_sources:
        m.PS = pyo.Set(initialize=penalized_sources)
        m.shortfall = pyo.Var(m.PS, domain=pyo.NonNegativeReals)

        def shortfall_rule(m, s):
            offtake = sum(m.x[ss, j] for (ss, j) in SJ if ss == s)
            return m.shortfall[s] >= nd.sources[s]["contracted_quantity"] - offtake
        m.ShortfallDef = pyo.Constraint(m.PS, rule=shortfall_rule)

    # silent-hours throughput throttle (opt-in): for household/private-vehicle
    # zones with a configured no-delivery window, a station can push at most
    # capacity * (available_hours/24) through that one arc - the same daily
    # volume has to fit into fewer hours, so it competes harder for capacity.
    silent_hours_on = nd.settings.get("enable_silent_hours", False)
    silent_arcs = [(k, d) for (k, d) in KD if silent_hours_on and (k, d) in nd.kd_capacity_cap]

    def obj_rule(m):
        fixed = sum(nd.cgs[j]["fixed_operating_cost"] * m.y[j] for j in J) \
              + sum(nd.stations[k]["fixed_cost"] * m.z[k] for k in K)
        supply_cost = sum(nd.sources[s]["supply_cost"] * m.x[s, j] for (s, j) in SJ)
        sj_transport = sum(corridor_by_sj[(s, j)]["transport_cost"] * m.x[s, j] for (s, j) in SJ)
        jk_transport = sum(nd.jk_cost[(j, k)] * m.w[j, k] for (j, k) in JK)
        kd_transport = sum(nd.kd_cost[(k, d)] * m.v[k, d] for (k, d) in KD)
        shortage = sum(penalty_base * penalty_weight(d) * m.u[d] for d in D)
        contract_penalty = sum(nd.sources[s]["take_or_pay_penalty_rate"] * m.shortfall[s] for s in penalized_sources)
        return fixed + supply_cost + sj_transport + jk_transport + kd_transport + shortage + contract_penalty

    m.Obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    def source_cap_rule(m, s):
        outgoing = [(ss, j) for (ss, j) in SJ if ss == s]
        if not outgoing:
            return pyo.Constraint.Skip
        avail = nd.sources[s]["base_availability"] * nd.sources[s]["max_capacity"]
        return sum(m.x[s, j] for (ss, j) in outgoing for s in [ss]) <= avail
    m.SourceCap = pyo.Constraint(m.S, rule=source_cap_rule)

    def corridor_cap_rule(m, s, j):
        return m.x[s, j] <= corridor_by_sj[(s, j)]["capacity"]
    m.CorridorCap = pyo.Constraint(m.SJ, rule=corridor_cap_rule)

    if silent_arcs:
        m.SilentArcs = pyo.Set(initialize=silent_arcs, dimen=2)

        def silent_hours_cap_rule(m, k, d):
            return m.v[k, d] <= nd.kd_capacity_cap[(k, d)]
        m.SilentHoursCap = pyo.Constraint(m.SilentArcs, rule=silent_hours_cap_rule)

    def cgs_balance_rule(m, j):
        inflow = sum(m.x[s, jj] for (s, jj) in SJ if jj == j)
        outflow = sum(m.w[jj, k] for (jj, k) in JK if jj == j)
        return inflow == outflow
    m.CGSBalance = pyo.Constraint(m.J, rule=cgs_balance_rule)

    def cgs_cap_rule(m, j):
        inflow = sum(m.x[s, jj] for (s, jj) in SJ if jj == j)
        return inflow <= nd.cgs[j]["capacity"] * m.y[j]
    m.CGSCap = pyo.Constraint(m.J, rule=cgs_cap_rule)

    def station_balance_rule(m, k):
        inflow = sum(m.w[j, kk] for (j, kk) in JK if kk == k)
        outflow = sum(m.v[kk, d] for (kk, d) in KD if kk == k)
        return inflow == outflow
    m.StationBalance = pyo.Constraint(m.K, rule=station_balance_rule)

    def station_cap_rule(m, k):
        inflow = sum(m.w[j, kk] for (j, kk) in JK if kk == k)
        return inflow <= nd.stations[k]["capacity"] * m.z[k]
    m.StationCap = pyo.Constraint(m.K, rule=station_cap_rule)

    def demand_rule(m, d):
        served = sum(m.v[k, dd] for (k, dd) in KD if dd == d)
        return served + m.u[d] == nd.demand_zones[d]["base_demand"]
    m.Demand = pyo.Constraint(m.D, rule=demand_rule)

    def service_level_rule(m, d):
        beta = nd.demand_zones[d]["min_service_level"]
        return m.u[d] <= (1 - beta) * nd.demand_zones[d]["base_demand"]
    m.ServiceLevel = pyo.Constraint(m.D, rule=service_level_rule)

    return m


def build_stochastic_model(base_nd: NetworkData, scenario_nds: dict, probabilities: dict,
                            penalty_base: float = None) -> pyo.ConcreteModel:
    """Two-stage stochastic model: facility decisions (y, z) are shared
    "here-and-now" first-stage variables; flows and unmet demand are
    scenario-indexed recourse variables. Facility/arc topology (S, J, K,
    D, SJ, JK, KD) is assumed identical across scenarios - only
    capacities, costs, availability, and demand vary per scenario. This
    mirrors the reference project's two-stage formulation.

    scenario_nds: {scenario_key: NetworkData}  (already overridden per scenario)
    probabilities: {scenario_key: float}, should sum to ~1
    """
    if penalty_base is None:
        penalty_base = base_nd.settings.get("unmet_demand_penalty_base", DEFAULT_UNMET_PENALTY_BASE)
    m = pyo.ConcreteModel(name="CNG_Network_Design_Stochastic")

    S = list(base_nd.sources.keys())
    J = list(base_nd.cgs.keys())
    K = list(base_nd.stations.keys())
    D = list(base_nd.demand_zones.keys())
    SJ = [(c["origin"], c["destination"]) for c in base_nd.corridors.values()]
    JK = base_nd.jk_arcs
    KD = base_nd.kd_arcs
    T = list(scenario_nds.keys())

    m.S, m.J, m.K, m.D, m.T = (pyo.Set(initialize=x) for x in (S, J, K, D, T))
    m.SJ = pyo.Set(initialize=SJ, dimen=2)
    m.JK = pyo.Set(initialize=JK, dimen=2)
    m.KD = pyo.Set(initialize=KD, dimen=2)

    m.y = pyo.Var(m.J, domain=pyo.Binary)
    m.z = pyo.Var(m.K, domain=pyo.Binary)
    for j in J:
        if base_nd.cgs[j]["infra_status"] == "existing":
            m.y[j].fix(1)
    for k in K:
        if base_nd.stations[k]["infra_status"] == "existing":
            m.z[k].fix(1)

    m.x = pyo.Var(m.SJ, m.T, domain=pyo.NonNegativeReals)
    m.w = pyo.Var(m.JK, m.T, domain=pyo.NonNegativeReals)
    m.v = pyo.Var(m.KD, m.T, domain=pyo.NonNegativeReals)
    m.u = pyo.Var(m.D, m.T, domain=pyo.NonNegativeReals)

    corridor_by_sj_t = {t: {(c["origin"], c["destination"]): c for c in nd.corridors.values()}
                         for t, nd in scenario_nds.items()}

    def penalty_weight(nd, d):
        pc = nd.priority_by_zone.get(d)
        return pc["penalty_weight"] if pc else 1.0

    # take-or-pay penalty clauses, scenario-indexed (a source's contracted
    # quantity and penalty rate don't change across scenarios, but its
    # actual offtake does) - same opt-in module as the deterministic model.
    penalty_clauses_on = base_nd.settings.get("enable_penalty_clauses", False)
    penalized_sources = [s for s in S if penalty_clauses_on and base_nd.sources[s].get("take_or_pay_penalty_rate", 0) > 0
                          and base_nd.sources[s].get("contracted_quantity", 0) > 0]
    if penalized_sources:
        m.PS = pyo.Set(initialize=penalized_sources)
        m.shortfall = pyo.Var(m.PS, m.T, domain=pyo.NonNegativeReals)

        def shortfall_rule(m, s, t):
            offtake = sum(m.x[ss, j, t] for (ss, j) in SJ if ss == s)
            return m.shortfall[s, t] >= base_nd.sources[s]["contracted_quantity"] - offtake
        m.ShortfallDef = pyo.Constraint(m.PS, m.T, rule=shortfall_rule)

    # silent-hours throughput throttle, scenario-indexed
    silent_hours_on = base_nd.settings.get("enable_silent_hours", False)
    silent_arcs = [(k, d) for (k, d) in KD if silent_hours_on and (k, d) in base_nd.kd_capacity_cap]

    def obj_rule(m):
        fixed = sum(base_nd.cgs[j]["fixed_operating_cost"] * m.y[j] for j in J) \
              + sum(base_nd.stations[k]["fixed_cost"] * m.z[k] for k in K)
        expected_variable = 0
        for t in T:
            nd = scenario_nds[t]
            pi = probabilities[t]
            supply_cost = sum(nd.sources[s]["supply_cost"] * m.x[s, j, t] for (s, j) in SJ)
            sj_transport = sum(corridor_by_sj_t[t][(s, j)]["transport_cost"] * m.x[s, j, t] for (s, j) in SJ)
            jk_transport = sum(nd.jk_cost[(j, k)] * m.w[j, k, t] for (j, k) in JK)
            kd_transport = sum(nd.kd_cost[(k, d)] * m.v[k, d, t] for (k, d) in KD)
            shortage = sum(penalty_base * penalty_weight(nd, d) * m.u[d, t] for d in D)
            contract_penalty = sum(base_nd.sources[s]["take_or_pay_penalty_rate"] * m.shortfall[s, t] for s in penalized_sources)
            expected_variable += pi * (supply_cost + sj_transport + jk_transport + kd_transport + shortage + contract_penalty)
        return fixed + expected_variable
    m.Obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    def source_cap_rule(m, s, t):
        nd = scenario_nds[t]
        outgoing = [(ss, j) for (ss, j) in SJ if ss == s]
        if not outgoing:
            return pyo.Constraint.Skip
        avail = nd.sources[s]["base_availability"] * nd.sources[s]["max_capacity"]
        return sum(m.x[s, j, t] for (ss, j) in outgoing for s in [ss]) <= avail
    m.SourceCap = pyo.Constraint(m.S, m.T, rule=source_cap_rule)

    def corridor_cap_rule(m, s, j, t):
        return m.x[s, j, t] <= corridor_by_sj_t[t][(s, j)]["capacity"]
    m.CorridorCap = pyo.Constraint(m.SJ, m.T, rule=corridor_cap_rule)

    def cgs_balance_rule(m, j, t):
        inflow = sum(m.x[s, jj, t] for (s, jj) in SJ if jj == j)
        outflow = sum(m.w[jj, k, t] for (jj, k) in JK if jj == j)
        return inflow == outflow
    m.CGSBalance = pyo.Constraint(m.J, m.T, rule=cgs_balance_rule)

    def cgs_cap_rule(m, j, t):
        inflow = sum(m.x[s, jj, t] for (s, jj) in SJ if jj == j)
        return inflow <= base_nd.cgs[j]["capacity"] * m.y[j]
    m.CGSCap = pyo.Constraint(m.J, m.T, rule=cgs_cap_rule)

    def station_balance_rule(m, k, t):
        inflow = sum(m.w[j, kk, t] for (j, kk) in JK if kk == k)
        outflow = sum(m.v[kk, d, t] for (kk, d) in KD if kk == k)
        return inflow == outflow
    m.StationBalance = pyo.Constraint(m.K, m.T, rule=station_balance_rule)

    def station_cap_rule(m, k, t):
        inflow = sum(m.w[j, kk, t] for (j, kk) in JK if kk == k)
        return inflow <= base_nd.stations[k]["capacity"] * m.z[k]
    m.StationCap = pyo.Constraint(m.K, m.T, rule=station_cap_rule)

    def demand_rule(m, d, t):
        nd = scenario_nds[t]
        served = sum(m.v[k, dd, t] for (k, dd) in KD if dd == d)
        return served + m.u[d, t] == nd.demand_zones[d]["base_demand"]
    m.Demand = pyo.Constraint(m.D, m.T, rule=demand_rule)

    def service_level_rule(m, d, t):
        nd = scenario_nds[t]
        beta = nd.demand_zones[d]["min_service_level"]
        return m.u[d, t] <= (1 - beta) * nd.demand_zones[d]["base_demand"]
    m.ServiceLevel = pyo.Constraint(m.D, m.T, rule=service_level_rule)

    if silent_arcs:
        m.SilentArcs = pyo.Set(initialize=silent_arcs, dimen=2)

        def silent_hours_cap_rule(m, k, d, t):
            return m.v[k, d, t] <= base_nd.kd_capacity_cap[(k, d)]
        m.SilentHoursCap = pyo.Constraint(m.SilentArcs, m.T, rule=silent_hours_cap_rule)

    return m
