def test_create_and_delete_project(client):
    r = client.post("/api/projects", json={"name": "Test Net"})
    assert r.status_code == 201
    pid = r.get_json()["id"]
    assert r.get_json()["status"] == "Draft"

    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200

    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_demo_seed_has_expected_shape(client, demo_project_id):
    r = client.get(f"/api/projects/{demo_project_id}")
    counts = r.get_json()["counts"]
    assert counts["sources"] == 3
    assert counts["cgs"] == 3
    assert counts["stations"] == 5
    assert counts["demand_zones"] == 7
    assert counts["scenarios"] == 4


def test_dynamic_network_size_is_not_hardcoded(client):
    r = client.post("/api/projects", json={"name": "Big Net"})
    pid = r.get_json()["id"]

    for i in range(5):
        client.post(f"/api/network/{pid}/sources", json={"code": f"S{i}", "name": f"Src{i}", "max_capacity": 100})
    for i in range(8):
        client.post(f"/api/network/{pid}/cgs", json={"code": f"C{i}", "name": f"CGS{i}", "capacity": 200})
    for i in range(15):
        client.post(f"/api/network/{pid}/stations", json={"code": f"ST{i}", "name": f"Stn{i}", "capacity": 50, "demand_service_radius_km": 100})
    for i in range(9):
        client.post(f"/api/network/{pid}/demand", json={"code": f"D{i}", "name": f"Dz{i}", "base_demand": 20})

    r = client.get(f"/api/projects/{pid}")
    counts = r.get_json()["counts"]
    assert counts == {"sources": 5, "corridors": 0, "cgs": 8, "stations": 15, "demand_zones": 9, "scenarios": 0}


def test_duplicate_code_rejected(client):
    r = client.post("/api/projects", json={"name": "Dup Test"})
    pid = r.get_json()["id"]
    r = client.post(f"/api/network/{pid}/sources", json={"code": "X1", "name": "one"})
    assert r.status_code == 201
    r = client.post(f"/api/network/{pid}/sources", json={"code": "X1", "name": "two"})
    assert r.status_code == 400


def test_missing_required_field_rejected(client):
    r = client.post("/api/projects", json={"name": "Missing Field Test"})
    pid = r.get_json()["id"]
    r = client.post(f"/api/network/{pid}/cgs", json={"name": "no code given"})
    assert r.status_code == 400


def test_validation_flags_disconnected_demand_zone(client, demo_project_id):
    # add a demand zone far from any station's service radius
    client.post(f"/api/network/{demo_project_id}/demand", json={
        "code": "DZ-FAR", "name": "Far Away", "base_demand": 10,
        "latitude": -10, "longitude": 10, "min_service_level": 0.5,
    })
    r = client.get(f"/api/network/{demo_project_id}/validate")
    issues = r.get_json()["issues"]
    assert any("DZ-FAR" in i["message"] for i in issues)


def test_cascade_delete_removes_children(client):
    r = client.post("/api/projects", json={"name": "Cascade Test"})
    pid = r.get_json()["id"]
    client.post(f"/api/network/{pid}/sources", json={"code": "S1", "name": "s1"})
    client.delete(f"/api/projects/{pid}")
    # re-creating a project with the same id space shouldn't see old rows
    r = client.post("/api/projects", json={"name": "Cascade Test 2"})
    pid2 = r.get_json()["id"]
    r = client.get(f"/api/network/{pid2}/sources")
    assert r.get_json() == []
