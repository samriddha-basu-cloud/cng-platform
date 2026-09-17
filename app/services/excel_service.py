"""
Excel template generation, sample-data generation, parsing, and validation
for planning-data import (spec sections 37-57). The app never requires the
user to supply an external Excel file - both the blank template and a
complete, internally-consistent sample dataset are generated here.

Schema principle (spec section 38): the master-data sheets (Sources,
Corridors, CGS, CNG_Stations, Demand_Zones, Priority_Tiers) are generated
straight from the entity dataclasses in app/data/entities.py
(dataclasses.fields()), so adding a field there is automatically reflected
here with zero separate schema file to maintain. The monthly per-entity
data (which the optimizer actually consumes - see model_builder.py) is
exported/imported in the long format spec sections 45-48 describe:
one row per (entity, month).

*_id columns in the monthly sheets and in Corridors' from_id/to_id hold the
entity's `code` (e.g. "SRC-DOM", "CGS-N1") - this app's existing stable
business key - not the internal numeric id, matching how corridors already
reference sources/CGS by code elsewhere in the platform.
"""
import io
import dataclasses
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.data import entities as E
from app.data import repo

TEMPLATE_VERSION = "1.0"

# entity_key -> (dataclass, sheet title, dict-valued monthly fields to split into their own sheet)
ENTITY_SHEETS = {
    "sources": (E.Source, "Sources", ["monthly_availability"]),
    "corridors": (E.Corridor, "Corridors", ["monthly_capacity", "monthly_transport_cost"]),
    "cgs": (E.CGS, "CGS", []),
    "stations": (E.CNGStation, "CNG_Stations", []),
    # actual_demand is excluded from the template's master-data columns too - it's
    # observational data (spec section 31), not part of the planning schema. There is no
    # Actuals sheet yet (see MODEL_DOCUMENTATION.md limitations); set it via PATCH for now.
    "demand": (E.DemandZone, "Demand_Zones", ["monthly_demand", "actual_demand"]),
    "priorities": (E.PriorityClass, "Priority_Tiers", []),
}
ENTITY_ORDER = ["priorities", "sources", "cgs", "stations", "demand", "corridors"]

MONTHLY_SHEETS = {
    # sheet name -> (entity_key, dataclass field, header for the id column, header for the value column)
    "Monthly_Supply": ("sources", "monthly_availability", "source_id", "available_gas_scm"),
    "Monthly_Demand": ("demand", "monthly_demand", "node_id", "demand_scm"),
    "Monthly_Capacity": ("corridors", "monthly_capacity", "arc_id", "capacity_scm"),
    "Costs": ("corridors", "monthly_transport_cost", "arc_id", "transport_cost_inr_scm"),
}

# fields never shown as a plain column - internal linkage or handled specially
HIDDEN_FIELDS = {"id", "project_id", "priority_class_id"}
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _entity_columns(entity_key):
    cls, _, monthly_fields = ENTITY_SHEETS[entity_key]
    cols = [f.name for f in dataclasses.fields(cls)
            if f.name not in HIDDEN_FIELDS and f.name not in monthly_fields]
    if entity_key == "demand":
        # priority_class_id (an internal numeric FK) is replaced by the human-readable
        # tier name, resolved against the Priority_Tiers sheet on both export and import.
        cols.insert(cols.index("name") + 1, "priority_tier_name")
    return cols


def _style_header(ws, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        ws.column_dimensions[get_column_letter(c)].width = max(14, len(str(cell.value or "")) + 2)
    ws.freeze_panes = "A2"


def _write_readme(wb, sample: bool):
    ws = wb.active
    ws.title = "README"
    lines = [
        ("CNG / City Gas Network - Planning Data " + ("Sample Dataset" if sample else "Template"), True),
        (f"Template version: {TEMPLATE_VERSION}", False),
        (f"Generated: {datetime.now(timezone.utc).isoformat()}", False),
        (f"Planning horizon: 12 months (month = 1..12)", False),
        (f"Gas / demand unit: SCM (standard cubic metres) per month", False),
        (f"Currency: INR", False),
        ("", False),
        ("How this workbook is structured:", True),
        ("- Priority_Tiers, Sources, CGS, CNG_Stations, Demand_Zones, Corridors are MASTER DATA.", False),
        ("  Each row's 'code' (or 'name' for Priority_Tiers) is its unique id, referenced by other sheets.", False),
        ("- Monthly_Supply, Monthly_Demand, Monthly_Capacity, Costs are PLANNING DATA:", False),
        ("  one row per (entity id, month). Leaving an entity out of these sheets is fine - the", False),
        ("  optimizer then falls back to that entity's flat master-data value for every month.", False),
        ("- Corridors.origin_code must be a Sources.code; Corridors.destination_code must be a CGS.code.", False),
        ("- Demand_Zones.priority_tier_name must match a Priority_Tiers.name row.", False),
        ("", False),
        ("Mandatory fields: code/name, and any numeric field with no sensible zero default", False),
        ("(max_capacity, base_demand, capacity). Optional fields may be left blank - the", False),
        ("platform's own defaults apply (see MODEL_DOCUMENTATION.md).", False),
        ("", False),
        ("Percentages (reliability, base_availability, min_service_level, loss_pct) are", False),
        ("fractions between 0 and 1, not 0-100.", False),
        ("", False),
        ("Import process: Upload -> Validate -> Preview -> Confirm Import. Validation never", False),
        ("silently writes data; nothing is changed until you confirm the preview.", False),
    ]
    for text, bold in lines:
        ws.append([text])
        if bold:
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 100


def _write_entity_sheet(wb, entity_key, rows, priority_name_by_id=None):
    cls, title, _ = ENTITY_SHEETS[entity_key]
    cols = _entity_columns(entity_key)
    ws = wb.create_sheet(title)
    ws.append(cols)
    for item in rows:
        d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        row = []
        for c in cols:
            if c == "priority_tier_name":
                pid = d.get("priority_class_id")
                row.append((priority_name_by_id or {}).get(pid, ""))
            else:
                row.append(d.get(c, ""))
        ws.append(row)
    _style_header(ws, len(cols))
    return ws


def _write_monthly_sheet(wb, sheet_name, entity_key, field_name, id_header, value_header, entities_by_key):
    ws = wb.create_sheet(sheet_name)
    ws.append([id_header, "month", value_header])
    for item in entities_by_key.get(entity_key, []):
        monthly = getattr(item, field_name, None) or {}
        for month_str, value in sorted(monthly.items(), key=lambda kv: int(kv[0])):
            ws.append([item.code, int(month_str), value])
    _style_header(ws, 3)
    return ws


def _build_workbook(entities_by_key, priority_name_by_id, sample: bool) -> io.BytesIO:
    wb = Workbook()
    _write_readme(wb, sample=sample)
    for key in ENTITY_ORDER:
        _write_entity_sheet(wb, key, entities_by_key.get(key, []), priority_name_by_id)
    for sheet_name, (entity_key, field_name, id_header, value_header) in MONTHLY_SHEETS.items():
        _write_monthly_sheet(wb, sheet_name, entity_key, field_name, id_header, value_header, entities_by_key)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def generate_template_workbook() -> io.BytesIO:
    """A blank template: every sheet with headers only, no data rows."""
    return _build_workbook(entities_by_key={}, priority_name_by_id={}, sample=False)


def _sample_network():
    """An in-memory (never persisted) illustrative network, deliberately small,
    exercising every sheet: 2 sources, 2 CGS, 3 stations (CNG-labelled but the
    schema doesn't distinguish PNG/industrial beyond demand_type), 4 demand
    zones (Mixed/PNG-style, Industrial), corridors, priority tiers, and 12
    months of supply/demand/capacity/cost data engineered to show a shortage
    in months 6-8 (winter demand peak vs a planned maintenance dip in supply)
    so the sample demonstrates shortage, priority allocation and bottlenecks
    (spec section 68) out of the box.
    """
    project = E.Project(id=0, name="Sample", monthly_horizon=12)

    def nid():
        return project.next_id()

    priorities = [
        E.PriorityClass(id=nid(), project_id=0, name="PNG Households", rank=1,
                         min_fulfilment_pct=0.95, max_fulfilment_pct=1.0, penalty_weight=5.0),
        E.PriorityClass(id=nid(), project_id=0, name="CNG Stations", rank=2,
                         min_fulfilment_pct=0.90, max_fulfilment_pct=1.0, penalty_weight=3.0),
        E.PriorityClass(id=nid(), project_id=0, name="Industrial", rank=3,
                         min_fulfilment_pct=0.80, max_fulfilment_pct=1.0, penalty_weight=1.5),
    ]
    prio_by_name = {p.name: p for p in priorities}

    winter_dip = {str(t): 420 if t in (6, 7, 8) else 500 for t in range(1, 13)}
    sources = [
        E.Source(id=nid(), project_id=0, code="SRC-DOM", name="Domestic Field (sample)", source_type="Domestic",
                  latitude=23.0, longitude=72.5, max_capacity=500, base_availability=1.0, supply_cost=5.0,
                  contracted_quantity=450, reliability=0.95, monthly_availability=winter_dip),
        E.Source(id=nid(), project_id=0, code="SRC-LNG", name="LNG Terminal (sample)", source_type="LNG Terminal",
                  latitude=21.7, longitude=72.2, max_capacity=350, base_availability=1.0, supply_cost=8.0,
                  contracted_quantity=300, reliability=0.9),
    ]

    cgs = [
        E.CGS(id=nid(), project_id=0, code="CGS-A", name="City Gate A (sample)", latitude=23.02, longitude=72.55,
              capacity=650, fixed_operating_cost=150, expansion_cost=0.4, max_expansion=250, infra_status="existing"),
        E.CGS(id=nid(), project_id=0, code="CGS-B", name="City Gate B (sample, candidate)", latitude=21.75,
              longitude=72.25, capacity=300, fixed_operating_cost=120, expansion_cost=0.5, max_expansion=200,
              infra_status="candidate"),
    ]

    corridors = [
        E.Corridor(id=nid(), project_id=0, code="COR-1", name="Domestic -> CGS-A", origin_code="SRC-DOM",
                   destination_code="CGS-A", capacity=500, distance_km=60, transport_cost=1.5, loss_pct=0.01,
                   reliability=0.95),
        E.Corridor(id=nid(), project_id=0, code="COR-2", name="LNG -> CGS-A", origin_code="SRC-LNG",
                   destination_code="CGS-A", capacity=250, distance_km=40, transport_cost=1.2, loss_pct=0.01,
                   reliability=0.92),
        E.Corridor(id=nid(), project_id=0, code="COR-3", name="LNG -> CGS-B", origin_code="SRC-LNG",
                   destination_code="CGS-B", capacity=200, distance_km=30, transport_cost=1.0, loss_pct=0.01,
                   reliability=0.9,
                   monthly_capacity={str(t): (120 if t in (6, 7) else 200) for t in range(1, 13)}),
    ]

    stations = [
        E.CNGStation(id=nid(), project_id=0, code="STN-1", name="Station 1 (sample)", latitude=23.03,
                     longitude=72.56, capacity=320, fixed_cost=35, infra_status="existing",
                     demand_service_radius_km=50),
        E.CNGStation(id=nid(), project_id=0, code="STN-2", name="Station 2 (sample)", latitude=21.76,
                     longitude=72.26, capacity=280, fixed_cost=30, infra_status="existing",
                     demand_service_radius_km=50),
        E.CNGStation(id=nid(), project_id=0, code="STN-3", name="Station 3 (sample, candidate)", latitude=22.4,
                     longitude=72.4, capacity=200, fixed_cost=25, infra_status="candidate",
                     demand_service_radius_km=80),
    ]

    winter_peak = {str(t): 140 if t in (6, 7, 8) else 100 for t in range(1, 13)}
    demand = [
        E.DemandZone(id=nid(), project_id=0, code="DZ-PNG1", name="PNG Households North (sample)", latitude=23.02,
                     longitude=72.55, base_demand=100, min_service_level=0.95, demand_type="PNG Domestic",
                     priority_class_id=prio_by_name["PNG Households"].id, monthly_demand=winter_peak),
        E.DemandZone(id=nid(), project_id=0, code="DZ-CNG1", name="CNG Corridor North (sample)", latitude=23.05,
                     longitude=72.58, base_demand=150, min_service_level=0.90, demand_type="CNG",
                     priority_class_id=prio_by_name["CNG Stations"].id),
        E.DemandZone(id=nid(), project_id=0, code="DZ-IND1", name="Industrial Park South (sample)", latitude=21.77,
                     longitude=72.27, base_demand=90, min_service_level=0.80, demand_type="Industrial",
                     priority_class_id=prio_by_name["Industrial"].id,
                     monthly_demand={str(t): 130 if t in (6, 7, 8) else 90 for t in range(1, 13)}),
        E.DemandZone(id=nid(), project_id=0, code="DZ-IND2", name="Industrial Park East (sample)", latitude=22.41,
                     longitude=72.41, base_demand=60, min_service_level=0.80, demand_type="Industrial",
                     priority_class_id=prio_by_name["Industrial"].id),
    ]

    entities_by_key = {
        "priorities": priorities, "sources": sources, "cgs": cgs,
        "stations": stations, "demand": demand, "corridors": corridors,
    }
    priority_name_by_id = {p.id: p.name for p in priorities}
    return entities_by_key, priority_name_by_id


def generate_sample_workbook() -> io.BytesIO:
    entities_by_key, priority_name_by_id = _sample_network()
    return _build_workbook(entities_by_key, priority_name_by_id, sample=True)


# ----------------------------------------------------------------- parsing --
def parse_workbook(file_stream) -> dict:
    """Returns {sheet_name: [ {header: value, ...}, ... ]} for every known
    sheet present in the uploaded workbook. Unknown sheets are ignored;
    missing sheets simply produce no rows for that key (schema validation
    below reports which required sheets were absent)."""
    wb = load_workbook(file_stream, data_only=True, read_only=True)
    known_sheets = [title for _, title, _ in ENTITY_SHEETS.values()] + list(MONTHLY_SHEETS.keys())
    parsed = {}
    for name in known_sheets:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
        except StopIteration:
            parsed[name] = []
            continue
        rows = []
        for raw in rows_iter:
            if raw is None or all(v is None for v in raw):
                continue
            rows.append({header[i]: raw[i] for i in range(min(len(header), len(raw)))})
        parsed[name] = rows
    return parsed


# -------------------------------------------------------------- validation --
NUMERIC_NONNEGATIVE = {"max_capacity", "supply_cost", "capacity", "transport_cost", "fixed_operating_cost",
                        "fixed_cost", "expansion_cost", "max_expansion", "distance_km", "base_demand",
                        "contracted_quantity", "available_gas_scm", "demand_scm", "capacity_scm",
                        "transport_cost_inr_scm"}
FRACTION_0_1 = {"reliability", "base_availability", "loss_pct", "min_service_level", "max_service_level",
                "min_fulfilment_pct", "max_fulfilment_pct"}


def _issue(level, message, sheet=None, row=None, column=None):
    d = {"level": level, "message": message}
    if sheet is not None:
        d["sheet"] = sheet
    if row is not None:
        d["row"] = row
    if column is not None:
        d["column"] = column
    return d


def validate_import(parsed: dict) -> list:
    """Returns the same flat {level, message, ...} shape as
    app/utils/validation.py::validate_network, extended with sheet/row/column
    context. Schema -> data types -> referential integrity -> business rules
    -> time rules (spec section 51), in that order so the earliest, most
    fundamental problems surface first."""
    issues = []

    required_sheets = [title for _, title, _ in ENTITY_SHEETS.values()]
    for name in required_sheets:
        if name not in parsed:
            issues.append(_issue("error", f"Required sheet '{name}' is missing from the workbook.", sheet=name))
    if any(i["level"] == "error" for i in issues):
        return issues  # nothing else is checkable without the master-data sheets

    def rows(sheet):
        return parsed.get(sheet, [])

    codes = {}
    for key in ENTITY_ORDER:
        _, title, _ = ENTITY_SHEETS[key]
        id_field = "name" if key == "priorities" else "code"
        seen = set()
        entity_codes = []
        for i, row in enumerate(rows(title), start=2):
            val = row.get(id_field)
            if not val:
                issues.append(_issue("error", f"Missing '{id_field}' in row {i}.", sheet=title, row=i, column=id_field))
                continue
            if val in seen:
                issues.append(_issue("error", f"Duplicate {id_field} '{val}'.", sheet=title, row=i, column=id_field))
            seen.add(val)
            entity_codes.append(val)
        codes[key] = entity_codes

        cols = _entity_columns(key)
        for i, row in enumerate(rows(title), start=2):
            for col in cols:
                if col not in NUMERIC_NONNEGATIVE and col not in FRACTION_0_1:
                    continue
                v = row.get(col)
                if v in (None, ""):
                    continue
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    issues.append(_issue("error", f"'{col}' must be numeric, got '{row.get(col)}'.",
                                          sheet=title, row=i, column=col))
                    continue
                if col in NUMERIC_NONNEGATIVE and v < 0:
                    issues.append(_issue("error", f"'{col}' must be >= 0.", sheet=title, row=i, column=col))
                if col in FRACTION_0_1 and not (0 <= v <= 1):
                    issues.append(_issue("error", f"'{col}' must be between 0 and 1 (fraction, not percent).",
                                          sheet=title, row=i, column=col))

    # referential integrity: master data
    for i, row in enumerate(rows("Corridors"), start=2):
        if row.get("origin_code") and row["origin_code"] not in codes["sources"]:
            issues.append(_issue("error", f"Corridors.origin_code '{row['origin_code']}' is not a known Sources.code.",
                                  sheet="Corridors", row=i, column="origin_code"))
        if row.get("destination_code") and row["destination_code"] not in codes["cgs"]:
            issues.append(_issue("error", f"Corridors.destination_code '{row['destination_code']}' is not a known CGS.code.",
                                  sheet="Corridors", row=i, column="destination_code"))
    for i, row in enumerate(rows("Demand_Zones"), start=2):
        tier = row.get("priority_tier_name")
        if tier and tier not in codes["priorities"]:
            issues.append(_issue("error", f"Demand_Zones.priority_tier_name '{tier}' is not a known Priority_Tiers.name.",
                                  sheet="Demand_Zones", row=i, column="priority_tier_name"))

    # monthly / planning-data sheets: referential integrity + duplicate (id, month) + range
    for sheet_name, (entity_key, _field, id_header, value_header) in MONTHLY_SHEETS.items():
        valid_ids = set(codes.get(entity_key, []))
        seen_pairs = set()
        for i, row in enumerate(rows(sheet_name), start=2):
            eid, month, value = row.get(id_header), row.get("month"), row.get(value_header)
            if not eid:
                issues.append(_issue("error", f"Missing '{id_header}'.", sheet=sheet_name, row=i, column=id_header))
                continue
            if eid not in valid_ids:
                issues.append(_issue("error", f"'{eid}' is not a known {id_header}.",
                                      sheet=sheet_name, row=i, column=id_header))
            try:
                month = int(month)
            except (TypeError, ValueError):
                issues.append(_issue("error", f"'month' must be an integer 1-12, got '{row.get('month')}'.",
                                      sheet=sheet_name, row=i, column="month"))
                continue
            if not (1 <= month <= 12):
                issues.append(_issue("error", f"'month' must be between 1 and 12, got {month}.",
                                      sheet=sheet_name, row=i, column="month"))
            pair = (eid, month)
            if pair in seen_pairs:
                issues.append(_issue("error", f"Duplicate row for {id_header}='{eid}', month={month}.",
                                      sheet=sheet_name, row=i))
            seen_pairs.add(pair)
            if value in (None, ""):
                issues.append(_issue("warning", f"Missing '{value_header}' for {id_header}='{eid}', month={month}.",
                                      sheet=sheet_name, row=i, column=value_header))
            else:
                try:
                    if float(value) < 0:
                        issues.append(_issue("error", f"'{value_header}' must be >= 0.",
                                              sheet=sheet_name, row=i, column=value_header))
                except (TypeError, ValueError):
                    issues.append(_issue("error", f"'{value_header}' must be numeric, got '{value}'.",
                                          sheet=sheet_name, row=i, column=value_header))

        months_present = {r for _, r in seen_pairs}
        if valid_ids and len(months_present) < 12:
            issues.append(_issue("warning",
                                  f"{sheet_name} covers only {len(months_present)}/12 months - "
                                  f"missing months fall back to each entity's flat master-data value.",
                                  sheet=sheet_name))

    return issues


def preview_summary(parsed: dict, project) -> dict:
    """Add/update counts (spec section 53) computed against the target
    project's existing codes, plus a simple data-quality score."""
    existing = {}
    for key in ENTITY_ORDER:
        id_field = "name" if key == "priorities" else "code"
        existing[key] = {getattr(item, id_field) for item in repo.list_entities(project, key)}

    summary = {}
    for key in ENTITY_ORDER:
        _, title, _ = ENTITY_SHEETS[key]
        id_field = "name" if key == "priorities" else "code"
        incoming = [row.get(id_field) for row in parsed.get(title, []) if row.get(id_field)]
        added = sum(1 for c in incoming if c not in existing[key])
        updated = len(incoming) - added
        summary[key] = {"added": added, "updated": updated, "total_rows": len(parsed.get(title, []))}

    for sheet_name in MONTHLY_SHEETS:
        summary[sheet_name] = {"records": len(parsed.get(sheet_name, []))}

    issues = validate_import(parsed)
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    checks = max(1, len(errors) + len(warnings) + 20)  # +20 baseline checks always "passing" when clean
    quality = round(1 - len(errors) / checks - 0.5 * len(warnings) / checks, 4)
    return {
        "summary": summary, "errors": errors, "warnings": warnings,
        "error_count": len(errors), "warning_count": len(warnings),
        "data_quality": max(0.0, quality),
        "planning_horizon_months": 12,
        "status": "FAILED" if errors else "PASSED",
    }


# -------------------------------------------------------------------- apply --
def apply_import(project, parsed: dict, mode: str = "replace") -> dict:
    """Upserts master data by code (or name for priorities), then REPLACES
    the monthly planning-data rows for every entity touched by the workbook
    (spec section 54's two safest modes only: mode='create_new' is meaningful
    only via a fresh project - this function itself always upserts into
    whatever project it's given; the route layer decides whether that project
    is a newly-created one or the caller's existing project being replaced).
    Never called without validate_import() having returned zero errors first."""
    if mode not in ("create_new", "replace"):
        raise ValueError("mode must be 'create_new' or 'replace'")

    added = {k: 0 for k in ENTITY_ORDER}
    updated = {k: 0 for k in ENTITY_ORDER}

    priority_id_by_name = {p.name: p.id for p in project.priority_classes}
    for row in parsed.get("Priority_Tiers", []):
        name = row.get("name")
        data = {k: v for k, v in row.items() if k != "name" and v not in (None, "")}
        existing = next((p for p in project.priority_classes if p.name == name), None)
        if existing:
            repo.update_entity(project, "priorities", existing.id, data)
            updated["priorities"] += 1
        else:
            item = repo.add_entity(project, "priorities", {**data, "name": name})
            priority_id_by_name[name] = item.id
            added["priorities"] += 1

    for key in ["sources", "cgs", "stations"]:
        _, title, _ = ENTITY_SHEETS[key]
        existing_by_code = {item.code: item for item in repo.list_entities(project, key)}
        for row in parsed.get(title, []):
            code = row.get("code")
            data = {k: v for k, v in row.items() if v not in (None, "")}
            if code in existing_by_code:
                repo.update_entity(project, key, existing_by_code[code].id, data)
                updated[key] += 1
            else:
                repo.add_entity(project, key, data)
                added[key] += 1

    existing_demand_by_code = {item.code: item for item in repo.list_entities(project, "demand")}
    for row in parsed.get("Demand_Zones", []):
        code = row.get("code")
        data = {k: v for k, v in row.items() if k != "priority_tier_name" and v not in (None, "")}
        tier = row.get("priority_tier_name")
        if tier:
            data["priority_class_id"] = priority_id_by_name.get(tier)
        if code in existing_demand_by_code:
            repo.update_entity(project, "demand", existing_demand_by_code[code].id, data)
            updated["demand"] += 1
        else:
            repo.add_entity(project, "demand", data)
            added["demand"] += 1

    existing_cor_by_code = {item.code: item for item in repo.list_entities(project, "corridors")}
    for row in parsed.get("Corridors", []):
        code = row.get("code")
        data = {k: v for k, v in row.items() if v not in (None, "")}
        data.setdefault("origin_type", "source")
        data.setdefault("destination_type", "cgs")
        if code in existing_cor_by_code:
            repo.update_entity(project, "corridors", existing_cor_by_code[code].id, data)
            updated["corridors"] += 1
        else:
            repo.add_entity(project, "corridors", data)
            added["corridors"] += 1

    # monthly planning-data sheets replace the affected entities' monthly dicts entirely
    monthly_records = 0
    for sheet_name, (entity_key, field_name, id_header, value_header) in MONTHLY_SHEETS.items():
        by_code = {}
        for row in parsed.get(sheet_name, []):
            eid, month, value = row.get(id_header), row.get("month"), row.get(value_header)
            if not eid or value in (None, ""):
                continue
            by_code.setdefault(eid, {})[str(int(month))] = float(value)
            monthly_records += 1
        items_by_code = {item.code: item for item in repo.list_entities(project, entity_key)}
        for code, monthly in by_code.items():
            item = items_by_code.get(code)
            if item is None:
                continue
            repo.update_entity(project, entity_key, item.id, {field_name: monthly})

    return {
        "added": added, "updated": updated, "monthly_records_imported": monthly_records,
        "planning_horizon_months": 12,
    }
