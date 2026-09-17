"""Assumption Register (spec section 62) - was backend-only (entities.py +
demo_seed) with no API route until now."""


def test_assumption_crud(client):
    r = client.post("/api/projects", json={"name": "Assumption Test"})
    pid = r.get_json()["id"]

    r = client.post(f"/api/assumptions/{pid}", json={
        "parameter": "discount_rate", "value": "0.08", "unit": "fraction",
        "source": "Finance team", "confidence": "High", "status": "Actual"})
    assert r.status_code == 201
    a = r.get_json()
    assert a["parameter"] == "discount_rate"

    r = client.get(f"/api/assumptions/{pid}")
    assert len(r.get_json()) == 1

    r = client.patch(f"/api/assumptions/{pid}/{a['id']}", json={"confidence": "Medium"})
    assert r.get_json()["confidence"] == "Medium"

    r = client.delete(f"/api/assumptions/{pid}/{a['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/assumptions/{pid}").get_json() == []


def test_demo_project_assumptions_are_visible(client, demo_project_id):
    """The demo seed populates assumptions for every source - confirms
    they're actually reachable via the API now, not just in the JSON file."""
    r = client.get(f"/api/assumptions/{demo_project_id}")
    assert r.status_code == 200
    assumptions = r.get_json()
    assert len(assumptions) > 0
    assert all(a["status"] == "Illustrative" for a in assumptions)
