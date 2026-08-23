def test_resilience_score_is_bounded_and_transparent(client, demo_project_id):
    r = client.get(f"/api/analytics/{demo_project_id}/resilience")
    assert r.status_code == 200
    res = r.get_json()
    assert 0 <= res["score"] <= 100
    assert set(res["components"].keys()) == set(res["weights"].keys())
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-6


def test_resilience_weights_are_configurable(client, demo_project_id):
    r1 = client.get(f"/api/analytics/{demo_project_id}/resilience")
    r2 = client.get(f"/api/analytics/{demo_project_id}/resilience?service_continuity=0.9&supply_diversification=0.033&capacity_slack=0.033&network_redundancy=0.034")
    assert r1.get_json()["score"] != r2.get_json()["score"]


def test_pareto_frontier_is_monotonic_non_decreasing_cost(client, demo_project_id):
    r = client.get(f"/api/analytics/{demo_project_id}/pareto")
    assert r.status_code == 200
    points = [p for p in r.get_json()["points"] if p["status"] == "optimal"]
    costs = [p["cost"] for p in points]
    # higher service level should never be cheaper than a lower one
    assert costs == sorted(costs)


def test_tornado_rows_sorted_by_impact_desc(client, demo_project_id):
    r = client.get(f"/api/analytics/{demo_project_id}/tornado")
    assert r.status_code == 200
    rows = r.get_json()["rows"]
    impacts = [row["impact"] for row in rows]
    assert impacts == sorted(impacts, reverse=True)


def test_recommendations_only_from_optimal_result(client, demo_project_id):
    r = client.get(f"/api/analytics/{demo_project_id}/recommendations")
    assert r.status_code == 200
    body = r.get_json()
    assert body["base_status"] == "optimal"
    assert isinstance(body["recommendations"], list)


def test_summary_endpoint_shape(client, demo_project_id):
    r = client.get(f"/api/analytics/{demo_project_id}/summary")
    assert r.status_code == 200
    body = r.get_json()
    for key in ["normal_scenario", "severe_scenario", "resilience_score", "top_recommendations"]:
        assert key in body


def test_simulation_timeline_runs_requested_periods(client, demo_project_id):
    r = client.post(f"/api/simulate/{demo_project_id}", json={"num_periods": 3})
    assert r.status_code == 200
    body = r.get_json()
    assert body["num_periods"] == 3
    assert len(body["periods"]) == 3
    assert body["periods"][0]["period"] == 0


def test_whatif_preset_applies_and_compares(client, demo_project_id):
    r = client.post(f"/api/whatif/{demo_project_id}", json={"preset": "pipeline_failure"})
    assert r.status_code == 200
    body = r.get_json()
    assert "before" in body and "after" in body


def test_whatif_unknown_preset_rejected(client, demo_project_id):
    r = client.post(f"/api/whatif/{demo_project_id}", json={"preset": "not_a_real_preset"})
    assert r.status_code == 400


def test_report_exports_produce_files(client, demo_project_id):
    for fmt in ["json", "csv", "excel", "pdf"]:
        r = client.get(f"/api/report/{demo_project_id}/export/{fmt}")
        assert r.status_code == 200, f"{fmt} export failed: {r.data}"
        assert len(r.data) > 0


def test_technical_report_has_correct_set_sizes(client, demo_project_id):
    r = client.get(f"/api/report/{demo_project_id}/technical")
    assert r.status_code == 200
    sets = r.get_json()["sets"]
    assert sets["S (sources)"] == 3
    assert sets["J (CGS)"] == 3
    assert sets["K (CNG stations)"] == 5
    assert sets["D (demand zones)"] == 7


def test_illustrative_data_labeled_in_report(client, demo_project_id):
    r = client.get(f"/api/report/{demo_project_id}/executive")
    body = r.get_json()
    assert body["project"]["is_demo"] is True
    assert "ILLUSTRATIVE" in body["data_quality_note"] or "Illustrative" in body["data_quality_note"]
