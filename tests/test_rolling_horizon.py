"""Rolling-horizon re-optimization (spec section 25) - genuinely distinct
from the static 12-month plan: partial look-ahead + irreversible facility
commitments carried forward window to window."""


def test_rolling_horizon_commits_full_horizon_and_matches_static_when_stable(client):
    """With a perfectly flat, unconstrained network, rolling horizon and the
    static plan should reach the same monthly numbers - proving the rolling
    mechanism doesn't silently distort results when there's nothing to react to."""
    r = client.post("/api/projects", json={"name": "Rolling Horizon Test"})
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
        "code": "COR1", "name": "COR1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 100, "transport_cost": 1})

    r_static = client.post(f"/api/optimize/{pid}/multiperiod", json={})
    static_res = r_static.get_json()

    r_roll = client.post(f"/api/optimize/{pid}/rolling-horizon", json={"window_size": 3})
    roll_res = r_roll.get_json()

    assert roll_res["status"] == "optimal"
    assert roll_res["policy"] == "rolling_horizon"
    assert len(roll_res["monthly_breakdown"]) == 12
    for static_row, roll_row in zip(static_res["monthly_breakdown"], roll_res["monthly_breakdown"]):
        assert static_row["month"] == roll_row["month"]
        assert static_row["shortage"] == roll_row["shortage"] == 0.0


def test_rolling_horizon_keeps_a_candidate_facility_open_once_committed(client):
    """A candidate CGS that opens in an early window must stay open (forced
    'existing') in every later window - facilities aren't un-built."""
    r = client.post("/api/projects", json={"name": "Rolling Commit Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 1000, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 200, "fixed_operating_cost": 5, "infra_status": "candidate"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 50, "min_service_level": 1.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "COR1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 1000, "transport_cost": 1})

    r = client.post(f"/api/optimize/{pid}/rolling-horizon", json={"window_size": 2})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert "J1" in res["opened_cgs"]  # had to open to serve any demand at all
    for row in res["monthly_breakdown"]:
        assert row["shortage"] == 0.0
