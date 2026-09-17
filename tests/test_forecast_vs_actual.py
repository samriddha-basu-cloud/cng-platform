"""Forecast vs Actual (spec section 31)."""


def test_forecast_vs_actual_computes_variance_and_mape(client):
    r = client.post("/api/projects", json={"name": "Forecast Test"})
    pid = r.get_json()["id"]
    r = client.post(f"/api/network/{pid}/demand", json={
        "code": "D1", "name": "D1", "base_demand": 100, "demand_type": "Industrial",
        "monthly_demand": {"1": 100, "2": 100}})
    zone_id = r.get_json()["id"]
    client.patch(f"/api/network/{pid}/demand/{zone_id}", json={"actual_demand": {"1": 120, "2": 90}})

    r = client.get(f"/api/analytics/{pid}/forecast-vs-actual")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["rows"]) == 2
    row1 = next(x for x in data["rows"] if x["month"] == 1)
    assert row1["forecast"] == 100
    assert row1["actual"] == 120
    assert row1["variance"] == 20
    assert row1["percentage_error"] == 0.2

    node_summary = next(x for x in data["by_node"] if x["node"] == "D1")
    assert node_summary["count"] == 2
    assert node_summary["mape"] == 0.15  # avg of 20% and 10% error

    type_summary = next(x for x in data["by_customer_segment"] if x["customer_segment"] == "Industrial")
    assert type_summary["count"] == 2

    assert data["overall"]["count"] == 2


def test_forecast_vs_actual_empty_when_no_actuals_recorded(client):
    r = client.post("/api/projects", json={"name": "No Actuals Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/demand", json={"code": "D1", "name": "D1", "base_demand": 100})
    r = client.get(f"/api/analytics/{pid}/forecast-vs-actual")
    data = r.get_json()
    assert data["rows"] == []
    assert data["overall"]["count"] == 0
