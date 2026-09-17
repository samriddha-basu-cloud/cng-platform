"""Lexicographic priority allocation (spec section 14, Mode B): a genuinely
sequential solve that fully protects a higher tier before a lower tier gets
anything, as opposed to Mode A's weighted-penalty policy where a high
enough combined shortage in a low tier can still out-trade a small shortage
in a higher tier if the weights allow it."""


def _build_two_tier_shortage_network(client):
    """Supply (100) is less than combined demand (Tier1=60 + Tier2=60=120),
    so SOMEONE must go short. Tier1's penalty weight is only slightly higher
    than Tier2's (3 vs 1) - under weighted-penalty Mode A, a big enough
    Tier2 shortfall could still be cheaper than a small Tier1 one, but
    lexicographic Mode B must NEVER let Tier1 go short while Tier2 could
    still absorb more."""
    r = client.post("/api/projects", json={"name": "Lexicographic Test"})
    pid = r.get_json()["id"]
    r1 = client.post(f"/api/network/{pid}/priorities", json={
        "name": "Tier1", "rank": 1, "min_fulfilment_pct": 0.0, "max_fulfilment_pct": 1.0, "penalty_weight": 3})
    tier1_id = r1.get_json()["id"]
    r2 = client.post(f"/api/network/{pid}/priorities", json={
        "name": "Tier2", "rank": 2, "min_fulfilment_pct": 0.0, "max_fulfilment_pct": 1.0, "penalty_weight": 1})
    tier2_id = r2.get_json()["id"]

    client.post(f"/api/network/{pid}/sources", json={
        "code": "S1", "name": "S1", "max_capacity": 100, "base_availability": 1.0, "supply_cost": 1})
    client.post(f"/api/network/{pid}/cgs", json={
        "code": "J1", "name": "J1", "capacity": 200, "fixed_operating_cost": 0, "infra_status": "existing"})
    client.post(f"/api/network/{pid}/stations", json={
        "code": "K1", "name": "K1", "capacity": 200, "fixed_cost": 0, "infra_status": "existing",
        "demand_service_radius_km": 1000})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "Tier1 Zone", "base_demand": 60, "min_service_level": 0.0,
        "priority_class_id": tier1_id})
    client.post(f"/api/network/{pid}/demand", json={
        "code": "D2", "name": "Tier2 Zone", "base_demand": 60, "min_service_level": 0.0,
        "priority_class_id": tier2_id})
    client.post(f"/api/network/{pid}/corridors", json={
        "code": "C1", "name": "C1", "origin_code": "S1", "destination_code": "J1",
        "capacity": 200, "transport_cost": 1})
    return pid


def test_lexicographic_fully_protects_higher_tier(client):
    pid = _build_two_tier_shortage_network(client)
    r = client.post(f"/api/optimize/{pid}/multiperiod/lexicographic", json={})
    assert r.status_code == 200
    res = r.get_json()
    assert res["status"] == "optimal"
    assert res["policy"] == "lexicographic"

    by_node = {row["node"]: row for row in res["monthly_allocation"] if row["month"] == 1}
    # Tier1 (60 demand, 100 supply) must be FULLY served - zero shortage -
    # even though Tier2's weight is low enough that Mode A might trade it off.
    assert by_node["D1"]["shortage"] == 0.0
    assert by_node["D1"]["allocated"] == 60.0
    # Tier2 absorbs the entire remaining shortage (100 supply - 60 to Tier1 = 40 left for a 60 demand)
    assert by_node["D2"]["allocated"] == 40.0
    assert by_node["D2"]["shortage"] == 20.0

    stages = res["lexicographic_stages"]
    assert stages[0]["tier"] == "Tier1"
    assert stages[0]["total_shortage"] == 0.0
    assert stages[1]["tier"] == "Tier2"
    assert abs(stages[1]["total_shortage"] - 20.0 * 12) < 0.01  # ~20/month shortfall over the 12-month horizon
