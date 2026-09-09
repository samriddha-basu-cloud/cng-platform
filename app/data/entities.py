"""
Plain-Python entity classes backing JSON file storage. These deliberately
mirror the attribute names and to_dict() shapes of the old SQLAlchemy
models (app/models/models.py, now retired) so that model_builder.py,
validation.py, engine.py, and everything under app/analytics,
app/services, app/simulation - all of which only ever touch a project via
plain attribute access like `project.sources`, `s.code`, `s.is_active` -
needed zero changes when the storage layer moved from SQLite to flat
JSON files.
"""
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from typing import Optional, List


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Source:
    id: int
    project_id: int
    code: str
    name: str
    source_type: str = "Domestic"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    max_capacity: float = 0
    base_availability: float = 1.0
    min_operational_qty: float = 0
    supply_cost: float = 0
    contracted_quantity: float = 0
    reliability: float = 1.0
    is_active: bool = True
    infra_status: str = "existing"
    # --- realism extensions (all optional, all off/neutral by default) ---
    is_upstream_gail: bool = False        # flags this as a GAIL/national-grid-style upstream source,
                                           # so it can be targeted by the "GAIL upstream interruption" preset
    interruption_probability: float = 0.0  # 0-1, informational + drives that preset's default severity
    price_escalation_pct: float = 0.0     # annual % escalation applied to supply_cost across simulation periods
    take_or_pay_penalty_rate: float = 0.0  # currency/unit charged on (contracted_quantity - actual offtake), if positive
    delivery_pressure_bar: float = 25.0   # pressure this source injects gas into the network at

    def to_dict(self):
        return asdict(self)


@dataclass
class Corridor:
    id: int
    project_id: int
    code: str
    name: str
    origin_type: str = "source"
    origin_code: str = ""
    destination_type: str = "cgs"
    destination_code: str = ""
    capacity: float = 0
    distance_km: float = 0
    transport_cost: float = 0
    fixed_cost: float = 0
    loss_pct: float = 0
    reliability: float = 1.0
    pipeline_type: str = "pipeline"
    is_active: bool = True
    cost_variation_pct: float = 0.0  # +/- logistics cost variability band (fuel price, route/traffic risk);
                                      # used by the logistics-variation preset and sensitivity runs, not the base solve

    def to_dict(self):
        return asdict(self)


@dataclass
class CGS:
    id: int
    project_id: int
    code: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capacity: float = 0
    fixed_operating_cost: float = 0
    expansion_cost: float = 0
    max_expansion: float = 0
    infra_status: str = "existing"
    is_active: bool = True
    discharge_pressure_bar: float = 19.0        # pressure at which this CGS feeds stations
    infrastructure_escalation_pct: float = 0.0  # annual capex/opex escalation applied across simulation periods

    def to_dict(self):
        return asdict(self)


@dataclass
class CNGStation:
    id: int
    project_id: int
    code: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capacity: float = 0
    fixed_cost: float = 0
    expansion_cost: float = 0
    infra_status: str = "existing"
    demand_service_radius_km: float = 50
    is_active: bool = True
    min_inlet_pressure_bar: float = 16.0        # minimum CGS discharge pressure this station needs to compress/operate
    dispensing_pressure_bar: float = 200.0      # pressure gas is dispensed at (industrial users often need a guaranteed minimum)
    infrastructure_escalation_pct: float = 0.0  # annual capex/opex escalation applied across simulation periods

    def to_dict(self):
        return asdict(self)


@dataclass
class DemandZone:
    id: int
    project_id: int
    code: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    base_demand: float = 0
    growth_rate: float = 0
    demand_type: str = "Mixed"
    priority_class_id: Optional[int] = None
    min_service_level: float = 0.7
    max_service_level: float = 1.0
    min_required_pressure_bar: float = 0.0        # 0 = no requirement; industrial/process customers often need a guaranteed minimum
    max_travel_distance_km: Optional[float] = None  # rider/household tolerance for distance to a station; None = unconstrained
                                                     # (falls back to the station's own service radius only)
    silent_hours_start: Optional[int] = None       # hour 0-23; deliveries/servicing paused from here...
    silent_hours_end: Optional[int] = None         # ...to here (wraps past midnight if end < start). Meaningful mainly for
                                                     # Domestic / Private Vehicles zones (residential quiet hours)
    demand_variability_pct: float = 0.0            # +/- band representing seasonal/industrial demand swings around base_demand

    def __post_init__(self):
        # populated after load by _link_relationships() - a live PriorityClass
        # object, not stored in the JSON file. Mirrors the old SQLAlchemy
        # relationship so model_builder.py can keep doing d.priority_class.
        self.priority_class = None

    def to_dict(self):
        # only the real columns - matches the old SQLAlchemy to_dict(),
        # which never serialized the relationship object itself.
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class PriorityClass:
    id: int
    project_id: int
    name: str
    rank: int = 1
    min_fulfilment_pct: float = 0.7
    max_fulfilment_pct: float = 1.0
    penalty_weight: float = 1.0

    def to_dict(self):
        return asdict(self)


@dataclass
class ScenarioParameter:
    id: int
    scenario_id: int
    entity_type: str = ""
    entity_code: str = ""
    parameter: str = ""
    value: float = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class Scenario:
    id: int
    project_id: int
    name: str
    description: str = ""
    probability: float = 1.0
    is_default: bool = False
    demand_multiplier: float = 1.0
    pipeline_capacity_multiplier: float = 1.0
    transport_cost_multiplier: float = 1.0
    storage_restriction_multiplier: float = 1.0
    parameters: List[ScenarioParameter] = field(default_factory=list)

    def to_dict(self):
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "parameters"}
        d["parameters"] = [p.to_dict() for p in self.parameters]
        return d


@dataclass
class Assumption:
    id: int
    project_id: int
    entity_type: str = ""
    entity_code: str = ""
    parameter: str = ""
    value: str = ""
    unit: str = ""
    source: str = "User input"
    status: str = "Assumption"
    confidence: str = "Medium"
    notes: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Project:
    id: int
    name: str
    description: str = ""
    region: str = ""
    currency: str = "INR"
    gas_unit: str = "SCMD"
    demand_unit: str = "SCMD"
    time_granularity: str = "monthly"
    planning_horizon_years: int = 5
    num_periods: int = 1
    num_scenarios: int = 1
    status: str = "Draft"
    is_demo: bool = False
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    id_seq: int = 0  # single shared auto-increment counter for every child entity

    # --- realism-module toggles ---------------------------------------
    # Every one of these defaults to Off / neutral, so a project behaves
    # exactly as before until its owner opts in on the Setup tab. Each
    # module reads its numeric inputs from the entity fields above (per
    # source/CGS/station/demand-zone) - these switches only decide
    # whether the optimizer *enforces* them, never supply a hidden value.
    enable_pressure_model: bool = False        # gas-pressure feasibility on CGS->station->demand legs
    enable_silent_hours: bool = False          # household "no delivery window" throughput throttle
    enable_penalty_clauses: bool = False       # take-or-pay contract penalties on under-offtake sources
    enable_price_escalation: bool = False      # annual price/cost escalation in multi-period simulation
    enable_travel_distance_limit: bool = False  # zone-side max travel distance, on top of station service radius
    enable_logistics_variation: bool = False   # variable logistics cost swings in sensitivity/what-if runs
    enable_demand_variability: bool = False    # industrial/seasonal demand swing in sensitivity/what-if runs

    # --- dynamic global defaults (used for legs that have no per-row
    #     entity of their own - the dense CGS->station and station->demand
    #     hops - and for the base unmet-demand penalty) ---
    unmet_demand_penalty_base: float = 50.0    # currency / unit of unmet demand, before priority weighting
    jk_cost_per_km: float = 0.02               # CGS->station distance-based cost rate, currency/unit/km
    jk_flat_cost: float = 3.0                  # ...fallback when either end is missing coordinates
    kd_cost_per_km: float = 0.03               # station->demand distance-based cost rate, currency/unit/km
    kd_flat_cost: float = 2.0                  # ...fallback when either end is missing coordinates
    pressure_drop_rate_bar_per_km: float = 0.15  # pressure loss per km of travel, used by the pressure model
                                                   # on the CGS->station and station->demand hops

    sources: List[Source] = field(default_factory=list)
    corridors: List[Corridor] = field(default_factory=list)
    cgs_list: List[CGS] = field(default_factory=list)
    stations: List[CNGStation] = field(default_factory=list)
    demand_zones: List[DemandZone] = field(default_factory=list)
    priority_classes: List[PriorityClass] = field(default_factory=list)
    scenarios: List[Scenario] = field(default_factory=list)
    assumptions: List[Assumption] = field(default_factory=list)

    def next_id(self) -> int:
        self.id_seq += 1
        return self.id_seq

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "region": self.region, "currency": self.currency, "gas_unit": self.gas_unit,
            "demand_unit": self.demand_unit, "time_granularity": self.time_granularity,
            "planning_horizon_years": self.planning_horizon_years,
            "num_periods": self.num_periods, "num_scenarios": self.num_scenarios,
            "status": self.status, "is_demo": self.is_demo,
            "created_at": self.created_at,
            "enable_pressure_model": self.enable_pressure_model,
            "enable_silent_hours": self.enable_silent_hours,
            "enable_penalty_clauses": self.enable_penalty_clauses,
            "enable_price_escalation": self.enable_price_escalation,
            "enable_travel_distance_limit": self.enable_travel_distance_limit,
            "enable_logistics_variation": self.enable_logistics_variation,
            "enable_demand_variability": self.enable_demand_variability,
            "unmet_demand_penalty_base": self.unmet_demand_penalty_base,
            "jk_cost_per_km": self.jk_cost_per_km, "jk_flat_cost": self.jk_flat_cost,
            "kd_cost_per_km": self.kd_cost_per_km, "kd_flat_cost": self.kd_flat_cost,
            "pressure_drop_rate_bar_per_km": self.pressure_drop_rate_bar_per_km,
            "counts": {
                "sources": len(self.sources), "corridors": len(self.corridors),
                "cgs": len(self.cgs_list), "stations": len(self.stations),
                "demand_zones": len(self.demand_zones), "scenarios": len(self.scenarios),
            },
        }
