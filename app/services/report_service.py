"""
Builds executive and technical report payloads from real solve results,
and exports them to CSV / Excel / PDF / JSON. No figures in here are
invented - everything traces back to a fresh deterministic solve (or the
project's most recent optimal run) plus whatever's actually stored in
the Assumption table.
"""
import os
import json
import csv
import io
from datetime import datetime, timezone

from app.optimization import model_builder as mb, engine
from app.analytics.resilience import compute_resilience
from app.analytics.recommendations import generate_recommendations
from app.services.scenario_service import build_preset_overrides


def _solve_baseline(project):
    base_nd = mb.snapshot_network(project)
    return base_nd, engine.solve_network(base_nd)


def build_report_payload(project):
    base_nd, result = _solve_baseline(project)

    severe_result = None
    try:
        overrides = build_preset_overrides(project, "shortage_40")
        severe_nd = mb.apply_overrides(base_nd, overrides)
        r = engine.solve_network(severe_nd)
        if r["status"] == "optimal":
            severe_result = r
    except Exception:
        pass

    resilience = None
    try:
        resilience = compute_resilience(project)
    except Exception:
        pass

    recs = generate_recommendations(result, severe_result, base_nd) if result["status"] == "optimal" else []

    assumptions = [a.to_dict() for a in project.assumptions]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": project.to_dict(),
        "problem_statement": (
            f"Design a CNG supply chain network for '{project.name}' "
            f"({project.region or 'unspecified region'}) that minimizes total cost "
            f"(infrastructure, supply, transportation, shortage penalty) while meeting "
            f"configured minimum service levels, under normal and scarcity conditions."
        ),
        "network_summary": project.to_dict()["counts"],
        "optimization_method": "Capacitated facility location-allocation MILP "
                                f"(solver: {result.get('solver_name', 'n/a')})",
        "normal_result": result,
        "severe_result": severe_result,
        "resilience": resilience,
        "recommendations": recs,
        "assumptions": assumptions,
        "data_quality_note": "Any project marked is_demo=True, or any Assumption row with "
                              "status='Illustrative', uses illustrative demonstration data and "
                              "must be replaced with validated data before real decision-making.",
    }


def build_technical_payload(project):
    base_nd, result = _solve_baseline(project)
    m = mb.build_model(base_nd)
    import pyomo.environ as pyo
    num_vars = sum(1 for _ in m.component_data_objects(pyo.Var))
    num_constraints = sum(1 for _ in m.component_data_objects(pyo.Constraint))

    return {
        "sets": {
            "S (sources)": len(base_nd.sources), "J (CGS)": len(base_nd.cgs),
            "K (CNG stations)": len(base_nd.stations), "D (demand zones)": len(base_nd.demand_zones),
            "SJ (source-CGS arcs)": len(base_nd.corridors),
            "JK (CGS-station arcs)": len(base_nd.jk_arcs),
            "KD (station-demand arcs)": len(base_nd.kd_arcs),
        },
        "decision_variables": [
            {"name": "y_j", "type": "binary", "description": "1 if CGS j is open"},
            {"name": "z_k", "type": "binary", "description": "1 if CNG station k is open"},
            {"name": "x_sj", "type": "continuous >= 0", "description": "gas flow from source s to CGS j"},
            {"name": "w_jk", "type": "continuous >= 0", "description": "gas flow from CGS j to station k"},
            {"name": "v_kd", "type": "continuous >= 0", "description": "gas delivered from station k to demand zone d"},
            {"name": "u_d", "type": "continuous >= 0", "description": "unmet demand at zone d"},
        ],
        "objective": "Minimize: fixed facility costs + supply cost + transportation cost "
                     "(source-CGS + CGS-station + station-demand) + shortage penalty (priority-weighted)",
        "constraints": [
            "Source capacity: outbound flow <= availability_factor x max_capacity",
            "Corridor capacity: source-CGS flow <= corridor capacity",
            "CGS flow balance: inbound = outbound",
            "CGS capacity: inbound flow <= capacity x y_j",
            "Station flow balance: inbound = outbound",
            "Station capacity: inbound flow <= capacity x z_k",
            "Demand balance: delivered + unmet = demand",
            "Service level: unmet <= (1 - min_service_level) x demand",
            "Existing facilities forced open (y_j = 1 / z_k = 1)",
        ],
        "solver": result.get("solver_name"),
        "model_size": {"variables": num_vars, "constraints": num_constraints},
        "solve_status": result.get("status"),
        "objective_value": result.get("objective_value"),
        "runtime_seconds": result.get("runtime_seconds"),
    }


EXPORT_DIR_NAME = "exports"


def _export_dir(app):
    d = os.path.join(app.root_path, "static", EXPORT_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def export_json(app, project) -> str:
    payload = build_report_payload(project)
    path = os.path.join(_export_dir(app), f"project_{project.id}_report.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def export_csv(app, project) -> str:
    _, result = _solve_baseline(project)
    path = os.path.join(_export_dir(app), f"project_{project.id}_results.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Section", "Field", "Value"])
        writer.writerow(["Summary", "Status", result.get("status")])
        writer.writerow(["Summary", "Total Cost", result.get("objective_value")])
        if result.get("cost_breakdown"):
            for k, v in result["cost_breakdown"].items():
                writer.writerow(["Cost Breakdown", k, v])
        writer.writerow([])
        writer.writerow(["Facility", "Code", "Open", "Capacity", "Utilization"])
        if result.get("facilities"):
            for f_ in result["facilities"]["cgs"]:
                writer.writerow(["CGS", f_["code"], f_["open"], f_["capacity"], f_["utilization"]])
            for f_ in result["facilities"]["stations"]:
                writer.writerow(["Station", f_["code"], f_["open"], f_["capacity"], f_["utilization"]])
        writer.writerow([])
        writer.writerow(["Demand Zone", "Demand", "Unmet", "Fulfilment %", "Priority"])
        for d in result.get("demand_results") or []:
            writer.writerow([d["code"], d["demand"], d["unmet"], d["fulfilment_pct"], d["priority"]])
    return path


def export_excel(app, project) -> str:
    from openpyxl import Workbook
    _, result = _solve_baseline(project)
    path = os.path.join(_export_dir(app), f"project_{project.id}_results.xlsx")
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    ws.append(["Project", project.name])
    ws.append(["Status", result.get("status")])
    ws.append(["Total Cost", result.get("objective_value")])
    ws.append([])
    ws.append(["Cost Component", "Value"])
    for k, v in (result.get("cost_breakdown") or {}).items():
        ws.append([k, v])

    ws2 = wb.create_sheet("Facilities")
    ws2.append(["Type", "Code", "Open", "Capacity", "Inbound Flow", "Utilization"])
    for f_ in (result.get("facilities") or {}).get("cgs", []):
        ws2.append(["CGS", f_["code"], f_["open"], f_["capacity"], f_["inbound_flow"], f_["utilization"]])
    for f_ in (result.get("facilities") or {}).get("stations", []):
        ws2.append(["Station", f_["code"], f_["open"], f_["capacity"], f_["inbound_flow"], f_["utilization"]])

    ws3 = wb.create_sheet("Flows")
    ws3.append(["From", "To", "Flow", "Leg"])
    for leg, rows in (result.get("flows") or {}).items():
        for r in rows:
            ws3.append([r["from"], r["to"], r["flow"], leg])

    ws4 = wb.create_sheet("Demand")
    ws4.append(["Zone", "Demand", "Unmet", "Fulfilment %", "Min Service Level", "Priority"])
    for d in result.get("demand_results") or []:
        ws4.append([d["code"], d["demand"], d["unmet"], d["fulfilment_pct"], d["min_service_level"], d["priority"]])

    wb.save(path)
    return path


def export_pdf(app, project) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    payload = build_report_payload(project)
    result = payload["normal_result"]
    path = os.path.join(_export_dir(app), f"project_{project.id}_executive_report.pdf")

    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"CNG Network Design — Executive Report", styles["Title"]),
        Paragraph(project.name, styles["Heading2"]),
        Spacer(1, 12),
        Paragraph("Problem Statement", styles["Heading3"]),
        Paragraph(payload["problem_statement"], styles["BodyText"]),
        Spacer(1, 10),
    ]

    if project.is_demo:
        story.append(Paragraph(
            "<b>ILLUSTRATIVE DEMO DATA — NOT ACTUAL INDUSTRY DATA.</b> "
            "Replace with validated industry/public data before decision-making.",
            styles["BodyText"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Optimization Result", styles["Heading3"]))
    if result.get("status") == "optimal":
        kpi_rows = [
            ["Total Cost", f"{result['objective_value']:,.0f} {project.currency}"],
            ["Demand Fulfilment", f"{result['kpis']['demand_fulfilment_pct']*100:.1f}%"],
            ["Unmet Demand", f"{result['kpis']['total_unmet_demand']:,.1f} {project.demand_unit}"],
            ["CGS Open", f"{result['kpis']['cgs_open_count']}/{result['kpis']['cgs_total_count']}"],
            ["Stations Open", f"{result['kpis']['station_open_count']}/{result['kpis']['station_total_count']}"],
        ]
        t = Table(kpi_rows, colWidths=[7*cm, 7*cm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

        story.append(Paragraph("Cost Breakdown", styles["Heading3"]))
        cb_rows = [["Component", "Amount"]] + [[k.title(), f"{v:,.0f}"] for k, v in result["cost_breakdown"].items()]
        t2 = Table(cb_rows, colWidths=[7*cm, 7*cm])
        t2.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16233a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ]))
        story.append(t2)
    else:
        story.append(Paragraph(f"Status: {result.get('status')}", styles["BodyText"]))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Key Recommendations", styles["Heading3"]))
    if payload["recommendations"]:
        for r in payload["recommendations"][:8]:
            story.append(Paragraph(f"&bull; <b>{r['title']}</b> — {r['reason']}", styles["BodyText"]))
    else:
        story.append(Paragraph("No specific recommendations were triggered by the current network.", styles["BodyText"]))

    if payload.get("resilience"):
        story.append(Spacer(1, 14))
        story.append(Paragraph("Resilience Score", styles["Heading3"]))
        res = payload["resilience"]
        story.append(Paragraph(f"Overall score: {res['score']}/100", styles["BodyText"]))
        comp_rows = [["Component", "Weight", "Score"]] + [
            [res["component_labels"][k], f"{res['weights'][k]*100:.0f}%", f"{v*100:.0f}%"]
            for k, v in res["components"].items()
        ]
        t3 = Table(comp_rows, colWidths=[6*cm, 4*cm, 4*cm])
        t3.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.append(t3)

    story.append(Spacer(1, 16))
    story.append(Paragraph(f"<i>{payload['data_quality_note']}</i>", styles["BodyText"]))

    doc.build(story)
    return path
