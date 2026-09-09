"""
Tests for the opt-in "realism modules" (gas pressure, silent hours,
take-or-pay penalty clauses, GAIL-style upstream interruption, household
travel-distance limit, logistics/industrial variability presets). Every
module defaults to Off, so the first assertion in each test is usually
that the baseline behaves exactly as if the module didn't exist.
"""


def _simple_pid(client):
    r = client.post("/api/projects", json={"name": "Realism Test"})
    return r.get_json()["id"]


def test_toggles_default_off_and_project_exposes_them(client):
    pid = _simple_pid(client)
    p = client.get(f"/api/projects/{pid}").get_json()
    for key in ["enable_pressure_model", "enable_silent_hours", "enable_penalty_clauses",
                "enable_price_escalation", "enable_travel_distance_limit",
                "enable_logistics_variation", "enable_demand_variability"]:
        assert p[key] is False
    assert p["unmet_demand_penalty_base"] == 50.0
    assert p["jk_cost_per_km"] == 0.02


def test_take_or_pay_penalty_only_applies_when_enabled(client):
    pid = _simple_pid(client)
    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "Source1", "max_capacity": 50, "base_availability": 1.0, "supply_cost": 2,
        "contracted_quantity": 150, "take_or_pay_penalty_rate": 2.0})
    client.post(f"/api/network/{pid}/cgs", json={"code": "C1", "name": "CGS1", "capacity": 100, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "ST1", "name": "Station1", "capacity": 100, "infra_status": "existing", "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={"code": "D1", "name": "Zone1", "base_demand": 30, "min_service_level": 0.5})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "S1->C1", "origin_code": "S1", "destination_code": "C1", "capacity": 100, "transport_cost": 1})

    # module off: no contract_penalties cost even though offtake (<=30, since demand=30) is far below contracted 150
    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["cost_breakdown"]["contract_penalties"] == 0.0

    # module on: shortfall is billed
    client.patch(f"/api/projects/{pid}", json={"enable_penalty_clauses": True})
    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["cost_breakdown"]["contract_penalties"] > 0
    assert len(res["contract_shortfalls"]) == 1
    assert res["contract_shortfalls"][0]["source"] == "S1"


def test_pressure_model_removes_infeasible_arc(client):
    pid = _simple_pid(client)
    client.post(f"/api/network/{pid}/sources", json={"code": "S1", "name": "Source1", "max_capacity": 100, "supply_cost": 2})
    # CGS and station ~550km apart (5 degrees latitude) - default drop rate 0.15 bar/km wipes out any
    # plausible discharge pressure over that distance
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "C1", "name": "CGS1", "capacity": 100, "infra_status": "existing",
        "latitude": 20.0, "longitude": 78.0, "discharge_pressure_bar": 19})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "ST1", "name": "Station1", "capacity": 100, "infra_status": "existing", "demand_service_radius_km": 1000,
        "latitude": 25.0, "longitude": 78.0, "min_inlet_pressure_bar": 16})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "Zone1", "base_demand": 30, "min_service_level": 1.0,
        "latitude": 25.0, "longitude": 78.0})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "S1->C1", "origin_code": "S1", "destination_code": "C1", "capacity": 100, "transport_cost": 1})

    # module off: the dense CGS->station arc exists regardless of distance/pressure
    r = client.post(f"/api/optimize/{pid}", json={})
    assert r.get_json()["status"] == "optimal"

    # module on: pressure can't reach the station over that distance, so the arc disappears and
    # the zone (100% service level required) can no longer be served at all
    client.patch(f"/api/projects/{pid}", json={"enable_pressure_model": True})
    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "infeasible"


def test_silent_hours_throttles_throughput(client):
    pid = _simple_pid(client)
    client.post(f"/api/network/{pid}/sources", json={"code": "S1", "name": "Source1", "max_capacity": 200, "supply_cost": 2})
    client.post(f"/api/network/{pid}/cgs", json={"code": "C1", "name": "CGS1", "capacity": 200, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "ST1", "name": "Station1", "capacity": 100, "infra_status": "existing", "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "Household Zone", "base_demand": 90, "min_service_level": 0.5, "demand_type": "Domestic",
        "silent_hours_start": 22, "silent_hours_end": 6})  # 8h window -> 16/24 = 66.7% of capacity available
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "COR1", "name": "S1->C1", "origin_code": "S1", "destination_code": "C1", "capacity": 200, "transport_cost": 1})

    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["kpis"]["total_unmet_demand"] == 0.0  # module off: full 90 flows through the one station

    client.patch(f"/api/projects/{pid}", json={"enable_silent_hours": True})
    r = client.post(f"/api/optimize/{pid}", json={})
    res = r.get_json()
    assert res["status"] == "optimal"
    # capacity is capped at 100 * 16/24 = 66.67 on that one arc, below the 90 demanded
    assert res["kpis"]["total_unmet_demand"] > 0


def test_gail_upstream_interruption_preset_targets_flagged_sources_only(client, demo_project_id):
    pid = demo_project_id
    sources = client.get(f"/api/network/{pid}/sources").get_json()
    gail_src = sources[0]
    client.patch(f"/api/network/{pid}/sources/{gail_src['id']}", json={
        "is_upstream_gail": True, "interruption_probability": 0.4})

    r = client.get(f"/api/scenarios/{pid}/presets/gail_upstream_interruption")
    assert r.status_code == 200
    overrides = r.get_json()["overrides"]
    assert overrides["source_availability"] == {gail_src["code"]: 0.6}
