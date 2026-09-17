"""Run comparison (spec section 60): Run A vs Run B, metrics read straight
from each run's stored result payload."""


def test_compare_two_multiperiod_runs(client):
    r = client.post("/api/projects", json={"name": "Compare Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 100, "base_availability": 1.0, "supply_cost": 2})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 200, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 50, "min_service_level": 0.5})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 100, "transport_cost": 1})

    r1 = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    run_a = r1.get_json()["run_id"]

    r_zone = client.get(f"/api/network/{pid}/demand")
    zone_id = r_zone.get_json()[0]["id"]
    client.patch(f"/api/network/{pid}/demand/{zone_id}", json={"base_demand": 10})
    r2 = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    run_b = r2.get_json()["run_id"]

    r = client.get(f"/api/runs/compare?run_a={run_a}&run_b={run_b}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["run_a"]["id"] == run_a
    assert data["run_b"]["id"] == run_b
    cost_row = next(m for m in data["comparison"] if m["metric"] == "total_cost")
    assert cost_row["delta"] < 0  # lower demand -> lower cost
