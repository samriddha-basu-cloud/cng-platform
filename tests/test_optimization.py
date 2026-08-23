from app.optimization.solver_registry import get_active_solver


def _build_known_network(client):
    r = client.post("/api/projects", json={"name": "Known Case"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "Source1", "max_capacity": 100, "base_availability": 1.0, "supply_cost": 2})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "C1", "name": "CGS1", "capacity": 100, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "ST1", "name": "Station1", "capacity": 100, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "Zone1", "base_demand": 50, "min_service_level": 1.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "S1->C1", "origin_code": "S1", "destination_code": "C1",
        "capacity": 100, "transport_cost": 1})
    return pid


def test_solver_is_detected():
    active = get_active_solver()
    assert active.available, "No solver available - HiGHS should be bundled via highspy"


def test_known_optimal_value(client):
    """Hand-computable case: 100 units available at source (cost=2/unit),
    corridor transport cost=1/unit, no coordinates anywhere so CGS-station
    and station-demand legs use the documented flat default costs (3.0 and
    2.0 respectively), demand=50 fully served (service level=1.0).
    Expected total cost = 50*2 (supply) + 50*1 (SJ transport)
                         + 50*3 (JK flat default) + 50*2 (KD flat default)
                         = 100 + 50 + 150 + 100 = 400.0
    """
    pid = _build_known_network(client)
    r = client.post(f"/api/optimize/{pid}", json={})
    assert r.status_code == 200
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["objective_value"] == 400.0
    assert res["cost_breakdown"]["supply"] == 100.0
    assert res["cost_breakdown"]["transportation"] == 300.0
    assert res["cost_breakdown"]["infrastructure"] == 0.0
    assert res["cost_breakdown"]["shortage_penalty"] == 0.0
    assert res["kpis"]["total_unmet_demand"] == 0.0
    assert res["kpis"]["demand_fulfilment_pct"] == 1.0


def test_insufficient_supply_is_infeasible(client):
    pid = _build_known_network(client)
    # tighten source capacity below demand while requiring 100% service level
    r = client.get(f"/api/network/{pid}/sources")
    src_id = r.get_json()[0]["id"]
    client.patch(f"/api/network/{pid}/sources/{src_id}", json={"max_capacity": 10})

    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "infeasible"
    assert "diagnostics" in res
    causes = [f["cause"] for f in res["diagnostics"]["findings"]]
    assert "Insufficient total supply" in causes


def test_scenario_shock_increases_cost(client, demo_project_id):
    pid = demo_project_id
    r_base = client.post(f"/api/optimize/{pid}", json={})
    base_cost = r_base.get_json()["objective_value"]

    r_shock = client.post(f"/api/whatif/{pid}", json={"preset": "shortage_20"})
    shock = r_shock.get_json()
    if shock["after"]["status"] == "optimal":
        assert shock["after"]["total_cost"] >= base_cost


def test_stochastic_solve_returns_expected_and_worst_case(client, demo_project_id):
    pid = demo_project_id
    # exclude the extreme scenario, which is infeasible in the demo data at 40% availability
    scenarios = client.get(f"/api/scenarios/{pid}").get_json()
    extreme = next(s for s in scenarios if s["name"] == "Extreme Shortage")
    client.patch(f"/api/scenarios/{pid}/{extreme['id']}", json={"is_default": False})

    r = client.post(f"/api/optimize/{pid}/stochastic", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["expected_cost"] <= res["worst_case_cost"]
    assert len(res["scenario_results"]) == 3


def test_robust_mode_conservative_uses_low_end(client, demo_project_id):
    pid = demo_project_id
    r = client.post(f"/api/optimize/{pid}/robust", json={"mode": "conservative", "supply_range": [0.6, 1.0]})
    res = r.get_json()
    assert res["applied_availability_factor"] == 0.6


def test_dynamic_network_of_different_size_solves(client):
    """Confirms nothing about facility/source counts is hard-coded."""
    r = client.post("/api/projects", json={"name": "Different Shape"})
    pid = r.get_json()["id"]
    for i in range(4):
        client.post(f"/api/network/{pid}/sources", json={
            "code": f"SRC{i}", "name": f"Source {i}", "max_capacity": 200, "supply_cost": 5})
    for i in range(6):
        client.post(f"/api/network/{pid}/cgs", json={
            "code": f"CGS{i}", "name": f"CGS {i}", "capacity": 300, "infra_status": "existing" if i < 3 else "candidate"})
    for i in range(10):
        client.post(f"/api/network/{pid}/stations", json={
            "code": f"STN{i}", "name": f"Station {i}", "capacity": 100,
            "infra_status": "existing" if i < 6 else "candidate", "demand_service_radius_km": 1000})
    for i in range(8):
        client.post(f"/api/network/{pid}/demand", json={
            "code": f"DZ{i}", "name": f"Zone {i}", "base_demand": 40, "min_service_level": 0.7})
    for i in range(4):
        client.post(f"/api/network/{pid}/corridors", json={
            "code": f"COR{i}", "name": f"Corridor {i}", "origin_code": f"SRC{i}",
            "destination_code": f"CGS{i}", "capacity": 300, "transport_cost": 2})

    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    # 4 y + 10 z + arcs; just assert it scaled with network size, not fixed at demo's count
    assert res["num_variables"] > 50
