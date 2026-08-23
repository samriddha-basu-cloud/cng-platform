"""
Illustrative demo dataset.

IMPORTANT: These values are ILLUSTRATIVE DEMO DATA — NOT ACTUAL INDUSTRY
DATA. They exist only so a new user sees a populated network on first
load. The project is marked is_demo=True and every numeric value is
also written to the project's assumptions list with status="Illustrative"
so the UI can label it honestly everywhere it appears (spec section 45 / 62).

This module contains no logic the optimizer depends on - delete the
project and the platform behaves identically for a from-scratch network
of any size.
"""
from app.data import repo

DEMO_LABEL = "Illustrative assumption for demonstration. Replace with validated industry/public data before decision-making."


def seed_demo_project_simple():
    project = repo.create_project({
        "name": "Demo: North-West Corridor CNG Network",
        "description": "ILLUSTRATIVE DEMO DATA - NOT ACTUAL INDUSTRY DATA. "
                        "A stylized network for exploring the platform's features.",
        "region": "Illustrative Region", "currency": "INR",
        "gas_unit": "SCMD", "demand_unit": "SCMD", "time_granularity": "monthly",
        "planning_horizon_years": 5, "num_periods": 1, "num_scenarios": 4,
        "is_demo": True,
    })
    project.status = "Configured"

    # ---- Priority classes ----
    priorities = {}
    for name, rank, min_f, max_f, weight in [
        ("Public Transport", 1, 0.95, 1.0, 5.0),
        ("Critical Services", 2, 0.90, 1.0, 4.0),
        ("Industrial", 3, 0.80, 1.0, 2.5),
        ("Commercial", 4, 0.70, 1.0, 1.5),
        ("Private Vehicles", 5, 0.60, 1.0, 1.0),
    ]:
        item = repo.add_entity(project, "priorities", {
            "name": name, "rank": rank, "min_fulfilment_pct": min_f,
            "max_fulfilment_pct": max_f, "penalty_weight": weight,
        })
        priorities[name] = item

    # ---- Sources ----
    source_defs = [
        {"code": "SRC-DOM", "name": "Domestic Field A", "source_type": "Domestic",
         "latitude": 23.75, "longitude": 68.85, "max_capacity": 500, "base_availability": 1.0,
         "min_operational_qty": 50, "supply_cost": 5.0, "contracted_quantity": 450, "reliability": 0.95},
        {"code": "SRC-LNG1", "name": "LNG Terminal North", "source_type": "LNG Terminal",
         "latitude": 22.30, "longitude": 69.10, "max_capacity": 800, "base_availability": 1.0,
         "min_operational_qty": 100, "supply_cost": 8.0, "contracted_quantity": 700, "reliability": 0.9},
        {"code": "SRC-LNG2", "name": "LNG Terminal South", "source_type": "LNG Terminal",
         "latitude": 17.98, "longitude": 73.18, "max_capacity": 400, "base_availability": 1.0,
         "min_operational_qty": 50, "supply_cost": 6.5, "contracted_quantity": 350, "reliability": 0.85},
    ]
    for s in source_defs:
        repo.add_entity(project, "sources", s)
        for p, u in [("max_capacity", "SCMD"), ("supply_cost", "INR/SCM"), ("reliability", "fraction")]:
            repo.add_assumption(project, entity_type="source", entity_code=s["code"], parameter=p,
                                 value=str(s[p]), unit=u, source="Demo seed", status="Illustrative",
                                 confidence="Low", notes=DEMO_LABEL)

    # ---- CGS ----
    for c in [
        {"code": "CGS-N1", "name": "City Gate North-1", "latitude": 28.60, "longitude": 77.20,
         "capacity": 850, "fixed_operating_cost": 200, "expansion_cost": 0.4, "max_expansion": 300, "infra_status": "existing"},
        {"code": "CGS-W1", "name": "City Gate West-1", "latitude": 19.08, "longitude": 72.88,
         "capacity": 600, "fixed_operating_cost": 150, "expansion_cost": 0.5, "max_expansion": 250, "infra_status": "existing"},
        {"code": "CGS-C1", "name": "City Gate Central-1 (candidate)", "latitude": 21.15, "longitude": 79.09,
         "capacity": 400, "fixed_operating_cost": 180, "expansion_cost": 0.45, "max_expansion": 200, "infra_status": "candidate"},
    ]:
        repo.add_entity(project, "cgs", c)

    # ---- Corridors: sources -> CGS ----
    for cor in [
        {"code": "COR-1", "name": "Domestic -> North CGS", "origin_type": "source", "origin_code": "SRC-DOM",
         "destination_type": "cgs", "destination_code": "CGS-N1", "capacity": 500, "distance_km": 310,
         "transport_cost": 1.8, "fixed_cost": 0, "loss_pct": 0.01, "reliability": 0.95, "pipeline_type": "pipeline"},
        {"code": "COR-2", "name": "LNG North -> North CGS", "origin_type": "source", "origin_code": "SRC-LNG1",
         "destination_type": "cgs", "destination_code": "CGS-N1", "capacity": 700, "distance_km": 520,
         "transport_cost": 2.6, "fixed_cost": 0, "loss_pct": 0.015, "reliability": 0.9, "pipeline_type": "pipeline"},
        {"code": "COR-3", "name": "LNG South -> West CGS", "origin_type": "source", "origin_code": "SRC-LNG2",
         "destination_type": "cgs", "destination_code": "CGS-W1", "capacity": 400, "distance_km": 180,
         "transport_cost": 1.4, "fixed_cost": 0, "loss_pct": 0.01, "reliability": 0.92, "pipeline_type": "pipeline"},
        {"code": "COR-4", "name": "LNG North -> Central CGS (virtual)", "origin_type": "source", "origin_code": "SRC-LNG1",
         "destination_type": "cgs", "destination_code": "CGS-C1", "capacity": 200, "distance_km": 940,
         "transport_cost": 4.2, "fixed_cost": 15, "loss_pct": 0.03, "reliability": 0.8, "pipeline_type": "virtual"},
    ]:
        repo.add_entity(project, "corridors", cor)

    # ---- CNG Stations ----
    for st in [
        {"code": "STN-N1", "name": "Station North-1", "latitude": 28.61, "longitude": 77.21,
         "capacity": 300, "fixed_cost": 40, "expansion_cost": 0.3, "infra_status": "existing", "demand_service_radius_km": 40},
        {"code": "STN-N2", "name": "Station North-2", "latitude": 28.45, "longitude": 77.03,
         "capacity": 300, "fixed_cost": 45, "expansion_cost": 0.3, "infra_status": "existing", "demand_service_radius_km": 40},
        {"code": "STN-W1", "name": "Station West-1", "latitude": 19.07, "longitude": 72.87,
         "capacity": 250, "fixed_cost": 35, "expansion_cost": 0.35, "infra_status": "existing", "demand_service_radius_km": 35},
        {"code": "STN-W2", "name": "Station West-2", "latitude": 19.22, "longitude": 72.98,
         "capacity": 250, "fixed_cost": 38, "expansion_cost": 0.35, "infra_status": "candidate", "demand_service_radius_km": 35},
        {"code": "STN-C1", "name": "Station Central-1", "latitude": 21.16, "longitude": 79.10,
         "capacity": 180, "fixed_cost": 30, "expansion_cost": 0.4, "infra_status": "candidate", "demand_service_radius_km": 45},
    ]:
        repo.add_entity(project, "stations", st)

    # ---- Demand Zones ----
    demand_defs = [
        {"code": "DZ-DEL", "name": "Delhi", "latitude": 28.61, "longitude": 77.21, "base_demand": 220,
         "growth_rate": 0.06, "demand_type": "Mixed", "priority": "Public Transport", "min_service_level": 0.95},
        {"code": "DZ-NOI", "name": "Noida", "latitude": 28.54, "longitude": 77.39, "base_demand": 150,
         "growth_rate": 0.05, "demand_type": "Commercial", "priority": "Commercial", "min_service_level": 0.70},
        {"code": "DZ-GUR", "name": "Gurugram", "latitude": 28.46, "longitude": 77.03, "base_demand": 130,
         "growth_rate": 0.07, "demand_type": "Private Vehicles", "priority": "Private Vehicles", "min_service_level": 0.60},
        {"code": "DZ-MUM", "name": "Mumbai", "latitude": 19.08, "longitude": 72.88, "base_demand": 180,
         "growth_rate": 0.05, "demand_type": "Mixed", "priority": "Public Transport", "min_service_level": 0.95},
        {"code": "DZ-THA", "name": "Thane", "latitude": 19.22, "longitude": 72.98, "base_demand": 140,
         "growth_rate": 0.06, "demand_type": "Commercial", "priority": "Commercial", "min_service_level": 0.70},
        {"code": "DZ-NAV", "name": "Navi Mumbai", "latitude": 19.03, "longitude": 73.02, "base_demand": 120,
         "growth_rate": 0.06, "demand_type": "Private Vehicles", "priority": "Private Vehicles", "min_service_level": 0.60},
        {"code": "DZ-NAG", "name": "Nagpur", "latitude": 21.15, "longitude": 79.09, "base_demand": 95,
         "growth_rate": 0.08, "demand_type": "Industrial", "priority": "Industrial", "min_service_level": 0.80},
    ]
    for d in demand_defs:
        pdef = dict(d)
        prio_name = pdef.pop("priority")
        pdef["priority_class_id"] = priorities[prio_name].id
        pdef["max_service_level"] = 1.0
        repo.add_entity(project, "demand", pdef)

    # ---- Default scarcity scenarios ----
    scenario_defs = [
        {"name": "Normal Supply", "description": "Baseline, no shocks.", "probability": 0.50,
         "is_default": True, "demand_multiplier": 1.0, "pipeline_capacity_multiplier": 1.0,
         "transport_cost_multiplier": 1.0, "availability": 1.00},
        {"name": "Moderate Shortage", "description": "Supply factor ~80%.", "probability": 0.30,
         "is_default": True, "demand_multiplier": 1.0, "pipeline_capacity_multiplier": 1.0,
         "transport_cost_multiplier": 1.05, "availability": 0.80},
        {"name": "Severe Shortage", "description": "Supply factor ~60%.", "probability": 0.15,
         "is_default": True, "demand_multiplier": 1.05, "pipeline_capacity_multiplier": 0.95,
         "transport_cost_multiplier": 1.1, "availability": 0.60},
        {"name": "Extreme Shortage", "description": "Supply factor ~40%.", "probability": 0.05,
         "is_default": True, "demand_multiplier": 1.1, "pipeline_capacity_multiplier": 0.9,
         "transport_cost_multiplier": 1.2, "availability": 0.40},
    ]
    for sc in scenario_defs:
        availability = sc.pop("availability")
        params = [{"entity_type": "source", "entity_code": s["code"],
                    "parameter": "availability_factor", "value": availability} for s in source_defs]
        sc["parameters"] = params
        repo.add_scenario(project, sc)

    repo.save_project(project)
    return project


def seed_demo_project_advanced():
    """
    A larger, deliberately more complex illustrative network that touches
    every entity type and every option the platform supports:
      - all three source types (Domestic, LNG Terminal, Other)
      - both corridor modes (pipeline and virtual/M-D-O)
      - both existing and candidate infrastructure at CGS and station level
      - all six demand types, across all five priority classes
      - a scenario that overrides specific corridors/stations directly
        (outage-style), not just a uniform availability factor - this is
        the more general form the simple demo doesn't exercise.

    Same rule as the simple demo: ILLUSTRATIVE DEMO DATA - NOT ACTUAL
    INDUSTRY DATA.
    """
    project = repo.create_project({
        "name": "Demo: Pan-India Multi-Corridor Network (Advanced)",
        "description": "ILLUSTRATIVE DEMO DATA - NOT ACTUAL INDUSTRY DATA. "
                        "A larger, multi-region network exercising every entity type: "
                        "mixed source types, pipeline + virtual corridors, existing and "
                        "candidate infrastructure, all demand types and priority classes, "
                        "and an outage-style scenario with corridor/station-level overrides.",
        "region": "Illustrative - Pan-India", "currency": "INR",
        "gas_unit": "SCMD", "demand_unit": "SCMD", "time_granularity": "monthly",
        "planning_horizon_years": 5, "num_periods": 1, "num_scenarios": 5,
        "is_demo": True,
    })
    project.status = "Configured"

    priorities = {}
    for name, rank, min_f, max_f, weight in [
        ("Public Transport", 1, 0.95, 1.0, 5.0),
        ("Critical Services", 2, 0.90, 1.0, 4.0),
        ("Industrial", 3, 0.80, 1.0, 2.5),
        ("Commercial", 4, 0.70, 1.0, 1.5),
        ("Private Vehicles", 5, 0.60, 1.0, 1.0),
    ]:
        priorities[name] = repo.add_entity(project, "priorities", {
            "name": name, "rank": rank, "min_fulfilment_pct": min_f,
            "max_fulfilment_pct": max_f, "penalty_weight": weight,
        })

    source_defs = [
        {"code": "SRC-DOM1", "name": "Domestic Field - Gujarat", "source_type": "Domestic",
         "latitude": 21.62, "longitude": 73.00, "max_capacity": 600, "base_availability": 1.0,
         "min_operational_qty": 50, "supply_cost": 5.0, "contracted_quantity": 500, "reliability": 0.95},
        {"code": "SRC-DOM2", "name": "Domestic Field - Assam", "source_type": "Domestic",
         "latitude": 27.30, "longitude": 95.30, "max_capacity": 300, "base_availability": 1.0,
         "min_operational_qty": 30, "supply_cost": 5.5, "contracted_quantity": 250, "reliability": 0.90},
        {"code": "SRC-LNG1", "name": "LNG Terminal - Kochi", "source_type": "LNG Terminal",
         "latitude": 9.93, "longitude": 76.26, "max_capacity": 500, "base_availability": 1.0,
         "min_operational_qty": 60, "supply_cost": 8.0, "contracted_quantity": 400, "reliability": 0.88},
        {"code": "SRC-LNG2", "name": "LNG Terminal - Dahej", "source_type": "LNG Terminal",
         "latitude": 21.70, "longitude": 72.55, "max_capacity": 550, "base_availability": 1.0,
         "min_operational_qty": 60, "supply_cost": 7.5, "contracted_quantity": 450, "reliability": 0.90},
        {"code": "SRC-OTH1", "name": "Compressed Biogas Blending - Hosur", "source_type": "Other",
         "latitude": 12.74, "longitude": 77.83, "max_capacity": 80, "base_availability": 1.0,
         "min_operational_qty": 10, "supply_cost": 9.0, "contracted_quantity": 60, "reliability": 0.80},
    ]
    for s in source_defs:
        repo.add_entity(project, "sources", s)
        for p, u in [("max_capacity", "SCMD"), ("supply_cost", "INR/SCM"), ("reliability", "fraction")]:
            repo.add_assumption(project, entity_type="source", entity_code=s["code"], parameter=p,
                                 value=str(s[p]), unit=u, source="Demo seed", status="Illustrative",
                                 confidence="Low", notes=DEMO_LABEL)

    for c in [
        {"code": "CGS-N1", "name": "City Gate North - Delhi", "latitude": 28.61, "longitude": 77.21,
         "capacity": 700, "fixed_operating_cost": 220, "expansion_cost": 0.4, "max_expansion": 300, "infra_status": "existing"},
        {"code": "CGS-W1", "name": "City Gate West - Mumbai", "latitude": 19.08, "longitude": 72.88,
         "capacity": 900, "fixed_operating_cost": 280, "expansion_cost": 0.4, "max_expansion": 350, "infra_status": "existing"},
        {"code": "CGS-S1", "name": "City Gate South - Bengaluru", "latitude": 12.97, "longitude": 77.59,
         "capacity": 650, "fixed_operating_cost": 210, "expansion_cost": 0.45, "max_expansion": 280, "infra_status": "existing"},
        {"code": "CGS-E1", "name": "City Gate East - Kolkata (candidate)", "latitude": 22.57, "longitude": 88.36,
         "capacity": 400, "fixed_operating_cost": 190, "expansion_cost": 0.5, "max_expansion": 220, "infra_status": "candidate"},
        {"code": "CGS-C1", "name": "City Gate Central - Nagpur (candidate)", "latitude": 21.15, "longitude": 79.09,
         "capacity": 350, "fixed_operating_cost": 170, "expansion_cost": 0.5, "max_expansion": 200, "infra_status": "candidate"},
    ]:
        repo.add_entity(project, "cgs", c)

    for cor in [
        {"code": "COR-1", "name": "Gujarat -> North CGS", "origin_type": "source", "origin_code": "SRC-DOM1",
         "destination_type": "cgs", "destination_code": "CGS-N1", "capacity": 400, "distance_km": 950,
         "transport_cost": 3.0, "fixed_cost": 0, "loss_pct": 0.02, "reliability": 0.90, "pipeline_type": "pipeline"},
        {"code": "COR-2", "name": "Gujarat -> West CGS", "origin_type": "source", "origin_code": "SRC-DOM1",
         "destination_type": "cgs", "destination_code": "CGS-W1", "capacity": 350, "distance_km": 300,
         "transport_cost": 1.2, "fixed_cost": 0, "loss_pct": 0.01, "reliability": 0.95, "pipeline_type": "pipeline"},
        {"code": "COR-3", "name": "Dahej LNG -> West CGS", "origin_type": "source", "origin_code": "SRC-LNG2",
         "destination_type": "cgs", "destination_code": "CGS-W1", "capacity": 500, "distance_km": 300,
         "transport_cost": 1.5, "fixed_cost": 0, "loss_pct": 0.015, "reliability": 0.92, "pipeline_type": "pipeline"},
        {"code": "COR-4", "name": "Kochi LNG -> South CGS", "origin_type": "source", "origin_code": "SRC-LNG1",
         "destination_type": "cgs", "destination_code": "CGS-S1", "capacity": 400, "distance_km": 350,
         "transport_cost": 1.6, "fixed_cost": 0, "loss_pct": 0.015, "reliability": 0.90, "pipeline_type": "pipeline"},
        {"code": "COR-5", "name": "Assam -> East CGS (virtual)", "origin_type": "source", "origin_code": "SRC-DOM2",
         "destination_type": "cgs", "destination_code": "CGS-E1", "capacity": 250, "distance_km": 1000,
         "transport_cost": 4.5, "fixed_cost": 20, "loss_pct": 0.04, "reliability": 0.75, "pipeline_type": "virtual"},
        {"code": "COR-6", "name": "Kochi LNG -> Central CGS (virtual)", "origin_type": "source", "origin_code": "SRC-LNG1",
         "destination_type": "cgs", "destination_code": "CGS-C1", "capacity": 200, "distance_km": 1400,
         "transport_cost": 5.5, "fixed_cost": 25, "loss_pct": 0.05, "reliability": 0.70, "pipeline_type": "virtual"},
        {"code": "COR-7", "name": "CBG Blending -> South CGS", "origin_type": "source", "origin_code": "SRC-OTH1",
         "destination_type": "cgs", "destination_code": "CGS-S1", "capacity": 100, "distance_km": 350,
         "transport_cost": 2.0, "fixed_cost": 0, "loss_pct": 0.02, "reliability": 0.85, "pipeline_type": "pipeline"},
    ]:
        repo.add_entity(project, "corridors", cor)

    for st in [
        {"code": "STN-N1", "name": "Station Delhi", "latitude": 28.61, "longitude": 77.21,
         "capacity": 300, "fixed_cost": 45, "expansion_cost": 0.3, "infra_status": "existing", "demand_service_radius_km": 40},
        {"code": "STN-N2", "name": "Station Gurugram", "latitude": 28.46, "longitude": 77.03,
         "capacity": 250, "fixed_cost": 40, "expansion_cost": 0.3, "infra_status": "existing", "demand_service_radius_km": 35},
        {"code": "STN-W1", "name": "Station Mumbai", "latitude": 19.08, "longitude": 72.88,
         "capacity": 320, "fixed_cost": 50, "expansion_cost": 0.35, "infra_status": "existing", "demand_service_radius_km": 40},
        {"code": "STN-W2", "name": "Station Pune (candidate)", "latitude": 18.52, "longitude": 73.86,
         "capacity": 220, "fixed_cost": 35, "expansion_cost": 0.35, "infra_status": "candidate", "demand_service_radius_km": 60},
        {"code": "STN-S1", "name": "Station Bengaluru", "latitude": 12.97, "longitude": 77.59,
         "capacity": 280, "fixed_cost": 42, "expansion_cost": 0.35, "infra_status": "existing", "demand_service_radius_km": 40},
        {"code": "STN-S2", "name": "Station Chennai", "latitude": 13.08, "longitude": 80.27,
         "capacity": 260, "fixed_cost": 38, "expansion_cost": 0.35, "infra_status": "existing", "demand_service_radius_km": 50},
        {"code": "STN-E1", "name": "Station Kolkata (candidate)", "latitude": 22.57, "longitude": 88.36,
         "capacity": 200, "fixed_cost": 32, "expansion_cost": 0.4, "infra_status": "candidate", "demand_service_radius_km": 45},
        {"code": "STN-C1", "name": "Station Nagpur (candidate)", "latitude": 21.15, "longitude": 79.09,
         "capacity": 180, "fixed_cost": 30, "expansion_cost": 0.4, "infra_status": "candidate", "demand_service_radius_km": 50},
        {"code": "STN-NE1", "name": "Station Guwahati", "latitude": 26.14, "longitude": 91.74,
         "capacity": 150, "fixed_cost": 28, "expansion_cost": 0.4, "infra_status": "existing", "demand_service_radius_km": 60},
    ]:
        repo.add_entity(project, "stations", st)

    demand_defs = [
        {"code": "DZ-DEL", "name": "Delhi", "latitude": 28.61, "longitude": 77.21, "base_demand": 200,
         "growth_rate": 0.06, "demand_type": "Mixed", "priority": "Public Transport", "min_service_level": 0.95},
        {"code": "DZ-GUR", "name": "Gurugram", "latitude": 28.46, "longitude": 77.03, "base_demand": 140,
         "growth_rate": 0.07, "demand_type": "Private Vehicles", "priority": "Private Vehicles", "min_service_level": 0.60},
        {"code": "DZ-MUM", "name": "Mumbai", "latitude": 19.08, "longitude": 72.88, "base_demand": 230,
         "growth_rate": 0.05, "demand_type": "Mixed", "priority": "Public Transport", "min_service_level": 0.95},
        {"code": "DZ-PUN", "name": "Pune", "latitude": 18.52, "longitude": 73.86, "base_demand": 110,
         "growth_rate": 0.08, "demand_type": "Commercial", "priority": "Commercial", "min_service_level": 0.70},
        {"code": "DZ-BLR", "name": "Bengaluru", "latitude": 12.97, "longitude": 77.59, "base_demand": 170,
         "growth_rate": 0.07, "demand_type": "Domestic", "priority": "Critical Services", "min_service_level": 0.90},
        {"code": "DZ-CHE", "name": "Chennai", "latitude": 13.08, "longitude": 80.27, "base_demand": 150,
         "growth_rate": 0.06, "demand_type": "Industrial", "priority": "Industrial", "min_service_level": 0.80},
        {"code": "DZ-KOL", "name": "Kolkata", "latitude": 22.57, "longitude": 88.36, "base_demand": 120,
         "growth_rate": 0.09, "demand_type": "Transport", "priority": "Public Transport", "min_service_level": 0.95},
        {"code": "DZ-NAG", "name": "Nagpur", "latitude": 21.15, "longitude": 79.09, "base_demand": 90,
         "growth_rate": 0.08, "demand_type": "Industrial", "priority": "Industrial", "min_service_level": 0.80},
        {"code": "DZ-GUW", "name": "Guwahati", "latitude": 26.14, "longitude": 91.74, "base_demand": 70,
         "growth_rate": 0.10, "demand_type": "Mixed", "priority": "Critical Services", "min_service_level": 0.90},
    ]
    for d in demand_defs:
        pdef = dict(d)
        prio_name = pdef.pop("priority")
        pdef["priority_class_id"] = priorities[prio_name].id
        pdef["max_service_level"] = 1.0
        repo.add_entity(project, "demand", pdef)

    scenario_defs = [
        {"name": "Normal Supply", "description": "Baseline, no shocks.", "probability": 0.40,
         "is_default": True, "demand_multiplier": 1.0, "pipeline_capacity_multiplier": 1.0,
         "transport_cost_multiplier": 1.0, "availability": 1.00},
        {"name": "Moderate Shortage", "description": "Supply factor ~80% across all sources.", "probability": 0.25,
         "is_default": True, "demand_multiplier": 1.0, "pipeline_capacity_multiplier": 1.0,
         "transport_cost_multiplier": 1.05, "availability": 0.80},
        {"name": "Severe Shortage", "description": "Supply factor ~60% across all sources.", "probability": 0.15,
         "is_default": True, "demand_multiplier": 1.05, "pipeline_capacity_multiplier": 0.95,
         "transport_cost_multiplier": 1.1, "availability": 0.60},
        {"name": "Extreme Shortage", "description": "Supply factor ~40% across all sources.", "probability": 0.10,
         "is_default": True, "demand_multiplier": 1.1, "pipeline_capacity_multiplier": 0.9,
         "transport_cost_multiplier": 1.2, "availability": 0.40},
    ]
    for sc in scenario_defs:
        availability = sc.pop("availability")
        params = [{"entity_type": "source", "entity_code": s["code"],
                    "parameter": "availability_factor", "value": availability} for s in source_defs]
        sc["parameters"] = params
        repo.add_scenario(project, sc)

    # A fifth scenario that overrides specific corridors/stations directly,
    # rather than a uniform availability factor - the more general override
    # form (spec section 11: "Pipeline Capacity = -10%" style named shocks).
    outage_params = [
        {"entity_type": "source", "entity_code": s["code"], "parameter": "availability_factor", "value": 0.85}
        for s in source_defs
    ] + [
        {"entity_type": "corridor", "entity_code": "COR-6", "parameter": "inactive", "value": 1},
        {"entity_type": "station", "entity_code": "STN-C1", "parameter": "inactive", "value": 1},
    ]
    repo.add_scenario(project, {
        "name": "Regional Pipeline Outage", "description": "Kochi->Nagpur virtual corridor and Nagpur station "
                                                             "both out of service, with a mild broader supply dip.",
        "probability": 0.10, "is_default": True, "demand_multiplier": 1.1,
        "pipeline_capacity_multiplier": 1.0, "transport_cost_multiplier": 1.0,
        "parameters": outage_params,
    })

    repo.save_project(project)
    return project
