"""Tests for the genuinely time-indexed multi-period MILP
(app/optimization/model_builder.py::build_time_indexed_model), reached via
POST /api/optimize/<pid>/multiperiod. These are distinct from
app/simulation/timeline.py's sequential-solve simulation - here flows are
indexed by month inside ONE model, and per-month values (monthly_availability/
monthly_demand) actually bind the optimizer rather than just being displayed.
"""


def _build_known_network(client):
    r = client.post("/api/projects", json={"name": "Multi-period Known Case"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "Source1", "max_capacity": 100, "base_availability": 1.0, "supply_cost": 2})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "C1", "name": "CGS1", "capacity": 200, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "ST1", "name": "Station1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    r = client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "Zone1", "base_demand": 50, "min_service_level": 0.5})
    zone_id = r.get_json()["id"]
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "S1->C1", "origin_code": "S1", "destination_code": "C1",
        "capacity": 100, "transport_cost": 1})
    return pid, zone_id


def test_backward_compatible_flat_demand_repeats_every_month(client):
    """With no monthly_demand override, every month of the 12-month horizon
    should behave exactly like the flat single-period demand (50 units,
    service level 1.0, since 100 units/month are available)."""
    pid, _ = _build_known_network(client)
    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    assert r.status_code == 200
    res = r.get_json()
    assert res["status"] == "optimal"
    assert len(res["monthly_breakdown"]) == 12
    for row in res["monthly_breakdown"]:
        assert row["demand"] == 50
        assert row["shortage"] == 0.0
        assert row["service_level"] == 1.0
    # objective should be exactly 12x the single-period known-optimal cost (400.0,
    # see test_optimization.py::test_known_optimal_value - same network, same cost)
    assert res["objective_value"] == 4800.0


def test_monthly_demand_override_creates_a_genuine_shortage_only_in_that_month(client):
    """Month 2's demand (150) exceeds the source's monthly availability (100)
    while every other month stays at the flat 50 - this is only possible if
    the optimizer is actually consuming per-month data, not a single flat
    demand repeated 12 times."""
    pid, zone_id = _build_known_network(client)
    client.patch(f"/api/network/{pid}/demand/{zone_id}", json={"monthly_demand": {"1": 50, "2": 150}})

    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "optimal"

    by_month = {row["month"]: row for row in res["monthly_breakdown"]}
    assert by_month[1]["demand"] == 50
    assert by_month[1]["shortage"] == 0.0
    assert by_month[2]["demand"] == 150
    assert by_month[2]["supply_used"] == 100.0   # capped by monthly source availability
    assert by_month[2]["shortage"] == 50.0
    assert by_month[2]["service_level"] == round(100 / 150, 4)
    assert by_month[3]["demand"] == 50
    assert by_month[3]["shortage"] == 0.0

    # per-node monthly allocation table (spec section 16) carries the same numbers
    d1_month2 = next(row for row in res["monthly_allocation"] if row["node"] == "D1" and row["month"] == 2)
    assert d1_month2["shortage"] == 50.0


def test_monthly_source_availability_override_constrains_that_month_only(client):
    pid, _ = _build_known_network(client)
    r = client.get(f"/api/network/{pid}/sources")
    src_id = r.get_json()[0]["id"]
    # month 1 availability drops to 30, well under the 50-unit flat demand
    client.patch(f"/api/network/{pid}/sources/{src_id}", json={"monthly_availability": {"1": 30}})

    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    by_month = {row["month"]: row for row in res["monthly_breakdown"]}
    assert by_month[1]["supply_available"] == 30.0
    assert by_month[1]["shortage"] == 20.0
    assert by_month[2]["supply_available"] == 100.0
    assert by_month[2]["shortage"] == 0.0


def test_expansion_decision_relieves_a_binding_cgs_capacity(client):
    """CGS capacity (50) is below demand (100), but max_expansion (100) at
    expansion_cost=1/unit is cheap enough that the optimizer should choose to
    expand rather than accept a shortage penalty - proving e_cgs is a real
    decision variable, not a displayed-but-inert field (spec section 81)."""
    r = client.post("/api/projects", json={"name": "Expansion Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 2})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 50, "fixed_operating_cost": 0,
        "expansion_cost": 1, "max_expansion": 100, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "min_service_level": 1.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 1000, "transport_cost": 1})

    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    cgs = res["facilities"]["cgs"][0]
    assert cgs["expansion"] == 50.0
    assert cgs["effective_capacity"] == 100.0
    assert res["expansion_capex"] == 50.0  # a one-time capex charge, not multiplied by the 12-month horizon
    for row in res["monthly_breakdown"]:
        assert row["shortage"] == 0.0


def test_expansion_stays_zero_with_no_max_expansion_configured(client):
    """Backward compatibility: max_expansion defaults to 0, so the expansion
    variable is pinned to 0 and nothing about pre-existing networks changes."""
    pid, _ = _build_known_network(client)
    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["facilities"]["cgs"][0]["expansion"] == 0.0
    assert res["expansion_capex"] == 0.0


def test_storage_module_off_by_default_and_carries_inventory_when_enabled(client):
    r = client.post("/api/projects", json={"name": "Storage Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 2,
        "monthly_availability": {"1": 200, "2": 0}})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 500, "fixed_operating_cost": 0, "infra_status": "existing",
        "storage_capacity": 200, "storage_cost": 0.1})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 500, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "min_service_level": 0.0,
        "monthly_demand": {"1": 100, "2": 100}})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 1000, "transport_cost": 1})

    # storage module off by default: month 2 has zero available supply, so it
    # must show a shortage even though month 1 had a 100-unit surplus
    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    by_month = {row["month"]: row for row in res["monthly_breakdown"]}
    assert by_month[2]["shortage"] == 100.0
    assert "inventory_by_month" not in res

    # turn storage on: the same 100-unit month-1 surplus should now be carried
    # into month 2 as inventory, fully covering month 2's demand with zero shortage
    client.patch(f"/api/projects/{pid}", json={"enable_storage": True})
    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    by_month = {row["month"]: row for row in res["monthly_breakdown"]}
    assert by_month[1]["shortage"] == 0.0
    assert by_month[2]["shortage"] == 0.0
    assert res["inventory_by_month"]["J1"]["1"] == 100.0
    assert res["inventory_by_month"]["J1"]["2"] == 0.0


def test_mode_choice_between_parallel_corridors(client):
    """Two corridors between the SAME (origin, destination) pair - a cheap
    low-capacity 'pipeline' and an expensive high-capacity 'virtual pipeline'
    - must be tracked as genuinely distinct arcs, each with its own flow,
    not collapsed into one (spec section 24: mode choice is a real decision,
    not just a label). The optimizer should fill the cheap corridor to its
    capacity before touching the expensive one."""
    r = client.post("/api/projects", json={"name": "Mode Choice Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 1000, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 1000, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 150, "min_service_level": 1.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR-PIPE", "name": "Pipeline", "origin_code": "S1", "destination_code": "J1",
        "capacity": 100, "transport_cost": 1, "pipeline_type": "pipeline"})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR-VIRT", "name": "Virtual Pipeline", "origin_code": "S1", "destination_code": "J1",
        "capacity": 200, "transport_cost": 5, "pipeline_type": "virtual"})

    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "optimal"

    flows = res["flows_by_month"]["1"]["source_to_cgs"]
    by_corridor = {f["corridor"]: f["flow"] for f in flows}
    # cheap pipeline maxed out at its own 100-unit capacity...
    assert by_corridor["COR-PIPE"] == 100.0
    # ...and only the remaining 50 units go through the expensive virtual pipeline
    assert by_corridor["COR-VIRT"] == 50.0
    assert res["monthly_breakdown"][0]["shortage"] == 0.0


def test_multiperiod_infeasible_reports_per_month_diagnostics(client):
    pid, zone_id = _build_known_network(client)
    # 100% min service level, month 2 demand (150) exceeds max possible supply (100) -> infeasible
    client.patch(f"/api/network/{pid}/demand/{zone_id}", json={
        "monthly_demand": {"2": 150}, "min_service_level": 1.0})

    r = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    res = r.get_json()
    assert res["status"] == "infeasible"
    assert "diagnostics" in res
    assert res["diagnostics"]["worst_month"] == 2
    causes = [f["cause"] for f in res["diagnostics"]["per_month"]["2"]["findings"]]
    assert "Insufficient total supply" in causes
