"""Investment decision support (spec sections 22, 84): minimum CAPEX for a
target service level, and maximum service level for a fixed budget - both
real MILP solves against the time-indexed model, not a lookup table."""


def _build_expandable_network(client):
    r = client.post("/api/projects", json={"name": "Investment Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 50, "fixed_operating_cost": 0,
        "expansion_cost": 2, "max_expansion": 100, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "min_service_level": 0.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 1000, "transport_cost": 1})
    return pid


def test_min_capex_for_full_service(client):
    """CGS capacity (50) covers half of demand (100); expanding by 50 units
    at 2/unit = 100 CAPEX closes the gap exactly to 100% service."""
    pid = _build_expandable_network(client)
    r = client.post(f"/api/optimize/{pid}/investment/min-capex", json={"target_service_level": 1.0})
    assert r.status_code == 200
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["kpis"]["overall_service_level"] == 1.0
    assert res["expansion_capex"] == 100.0
    assert res["facilities"]["cgs"][0]["expansion"] == 50.0


def test_min_capex_for_partial_target_is_cheaper(client):
    """A lower target service level should never require MORE investment
    than a higher one against the same network."""
    pid = _build_expandable_network(client)
    r_full = client.post(f"/api/optimize/{pid}/investment/min-capex", json={"target_service_level": 1.0})
    r_half = client.post(f"/api/optimize/{pid}/investment/min-capex", json={"target_service_level": 0.75})
    capex_full = r_full.get_json()["expansion_capex"]
    capex_half = r_half.get_json()["expansion_capex"]
    assert capex_half <= capex_full
    assert capex_half == 25.0 * 2  # 25 extra units needed to go from 50% to 75% service


def test_min_capex_infeasible_beyond_max_expansion(client):
    pid = _build_expandable_network(client)
    r = client.post(f"/api/optimize/{pid}/investment/min-capex", json={"target_service_level": 1.0})
    assert r.get_json()["status"] == "optimal"  # sanity: 100% is reachable given max_expansion=100...
    # ...but nothing above what max_expansion allows is reachable at all:
    # capacity(50) + max_expansion(100) = 150 > demand(100), so instead prove
    # infeasibility a different way - drop max_expansion below the gap.
    r = client.get(f"/api/network/{pid}/cgs")
    cgs_id = r.get_json()[0]["id"]
    client.patch(f"/api/network/{pid}/cgs/{cgs_id}", json={"max_expansion": 10})
    r = client.post(f"/api/optimize/{pid}/investment/min-capex", json={"target_service_level": 1.0})
    res = r.get_json()
    assert res["status"] == "infeasible"
    assert "diagnostics" in res


def test_max_service_for_budget(client):
    pid = _build_expandable_network(client)
    r_zero = client.post(f"/api/optimize/{pid}/investment/max-service", json={"budget": 0})
    res_zero = r_zero.get_json()
    assert res_zero["status"] == "optimal"
    assert res_zero["kpis"]["overall_service_level"] == 0.5  # only the base 50-unit capacity, no expansion affordable

    r_full = client.post(f"/api/optimize/{pid}/investment/max-service", json={"budget": 100})
    res_full = r_full.get_json()
    assert res_full["kpis"]["overall_service_level"] == 1.0
    assert res_full["expansion_capex"] <= 100
