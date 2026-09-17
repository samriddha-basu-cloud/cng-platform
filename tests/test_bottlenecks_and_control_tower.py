"""Tests for binding-constraint/bottleneck analysis (spec section 19),
finite-difference marginal value analysis (spec section 20), and the
Control Tower KPIs/alerts (spec sections 34-36) - all computed from a real
multi-period MILP solve, not canned numbers."""


def _build_binding_network(client):
    """A corridor capacity (60) below what would otherwise be used (100),
    forcing it to bind every month, with a cheaper alternate source that
    is NOT capacity-constrained - so raising the binding corridor's
    capacity should have a real, non-zero, negative marginal cost impact."""
    r = client.post("/api/projects", json={"name": "Bottleneck Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "Cheap Source", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S2", "name": "Expensive Source", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 10})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 1000, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 1000, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "min_service_level": 1.0})
    # S1->J1 capped at 60 (binding, cheap source); S2->J1 uncapped (expensive fallback)
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "S1->J1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 60, "transport_cost": 1})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C2", "name": "S2->J1", "origin_code": "S2", "destination_code": "J1",
        "capacity": 1000, "transport_cost": 1})
    return pid


def test_bottleneck_analysis_flags_the_binding_corridor(client):
    pid = _build_binding_network(client)
    r = client.get(f"/api/analytics/{pid}/bottlenecks")
    assert r.status_code == 200
    data = r.get_json()
    codes = {c["asset_code"]: c for c in data["critical"]}
    assert "C1" in codes
    assert codes["C1"]["months_binding"] == 12
    assert codes["C1"]["severity"] == "HIGH"
    assert "C2" not in codes  # never binds - has huge slack


def test_marginal_value_of_binding_corridor_is_negative_and_labeled(client):
    """Relaxing C1's capacity should let the model substitute away from the
    expensive S2 fallback, strictly reducing total cost - a genuine
    non-zero finite-difference marginal value, clearly labeled as such."""
    pid = _build_binding_network(client)
    r = client.get(f"/api/analytics/{pid}/bottlenecks")
    data = r.get_json()
    mv = {m["asset_code"]: m for m in data["marginal_values"]}
    assert "C1" in mv
    assert mv["C1"]["marginal_value_per_unit"] > 0  # objective drops per unit of relaxed capacity
    assert "NOT an LP dual" in mv["C1"]["methodology"]


def test_control_tower_reports_kpis_and_critical_alert(client):
    pid = _build_binding_network(client)
    r = client.get(f"/api/analytics/{pid}/control-tower")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "optimal"
    assert data["kpis"]["overall_service_level"] == 1.0
    assert data["kpis"]["total_cost"] > 0
    severities = {a["asset"]: a["severity"] for a in data["alerts"]}
    assert severities.get("C1") == "CRITICAL"


def test_control_tower_tier_service_levels_use_configured_floor(client):
    r = client.post("/api/projects", json={"name": "Tier Test"})
    pid = r.get_json()["id"]
    rp = client.post(f"/api/network/{pid}/priorities", json={
        "name": "Tier1", "rank": 1, "min_fulfilment_pct": 0.95, "max_fulfilment_pct": 1.0, "penalty_weight": 5})
    tier_id = rp.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 10, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 100, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 100, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "min_service_level": 0.0, "priority_class_id": tier_id})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 100, "transport_cost": 1})

    r = client.get(f"/api/analytics/{pid}/control-tower")
    data = r.get_json()
    tier1 = next(t for t in data["tier_service_levels"] if t["tier"] == "Tier1")
    assert tier1["target"] == 0.95
    assert tier1["service_level"] < 0.95  # only 10/100 suppliable
    assert tier1["below_target"] is True
    assert any(a["metric"] == "tier_service_level" and a["severity"] == "CRITICAL" for a in data["alerts"])
