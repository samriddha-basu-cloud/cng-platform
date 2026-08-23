class ValidationError(Exception):
    pass


def require_fields(data: dict, fields: list[str]):
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(missing)}")


def check_duplicate_codes(existing_codes: list[str], new_code: str, exclude_id=None):
    return new_code in existing_codes


def validate_network(project) -> list[dict]:
    """
    Runs the structural checks described in spec section 32.
    Returns a list of {level: 'error'|'warning', message: str} dicts.
    Never raises - callers decide whether to block optimization on 'error' level.
    """
    issues = []

    source_codes = {s.code for s in project.sources if s.is_active}
    cgs_codes = {c.code for c in project.cgs_list if c.is_active}
    station_codes = {s.code for s in project.stations if s.is_active}

    # duplicate ID checks across each entity type
    def dup_check(items, label):
        seen = set()
        for it in items:
            if it.code in seen:
                issues.append({"level": "error", "message": f"Duplicate {label} ID: {it.code}"})
            seen.add(it.code)

    dup_check(project.sources, "Source")
    dup_check(project.corridors, "Corridor")
    dup_check(project.cgs_list, "CGS")
    dup_check(project.stations, "CNG Station")
    dup_check(project.demand_zones, "Demand Zone")

    # negative capacity / invalid coordinates
    for s in project.sources:
        if s.max_capacity is not None and s.max_capacity < 0:
            issues.append({"level": "error", "message": f"Source {s.code} has negative capacity."})
        if s.latitude is None or s.longitude is None:
            issues.append({"level": "warning", "message": f"Source {s.code} is missing coordinates (won't show on map)."})

    for c in project.cgs_list:
        if c.capacity is not None and c.capacity < 0:
            issues.append({"level": "error", "message": f"CGS {c.code} has negative capacity."})

    for st in project.stations:
        if st.capacity is not None and st.capacity < 0:
            issues.append({"level": "error", "message": f"Station {st.code} has negative capacity."})

    # corridor endpoint connectivity
    for cor in project.corridors:
        if cor.origin_type == "source" and cor.origin_code not in source_codes:
            issues.append({"level": "error", "message": f"Corridor {cor.code} references unknown/inactive source {cor.origin_code}."})
        if cor.destination_type == "cgs" and cor.destination_code not in cgs_codes:
            issues.append({"level": "error", "message": f"Corridor {cor.code} references unknown/inactive CGS {cor.destination_code}."})
        if cor.capacity is not None and cor.capacity < 0:
            issues.append({"level": "error", "message": f"Corridor {cor.code} has negative capacity."})

    # CGS without any inbound corridor
    fed_cgs = {c.destination_code for c in project.corridors if c.destination_type == "cgs"}
    for c in project.cgs_list:
        if c.is_active and c.code not in fed_cgs:
            issues.append({"level": "warning", "message": f"CGS {c.code} has no inbound source connectivity."})

    # station without a CGS reachable (Phase 2 optimizer defines CGS->station links;
    # for Phase 1 we just flag stations if there are zero active CGS at all)
    if project.stations and not cgs_codes:
        issues.append({"level": "error", "message": "There are CNG stations defined but no active CGS in the network."})

    # demand zones with zero stations at all
    if project.demand_zones and not station_codes:
        issues.append({"level": "error", "message": "There are demand zones defined but no active CNG stations in the network."})

    # per-zone reachability: is there any active station within service radius?
    import math

    def haversine(lat1, lon1, lat2, lon2):
        if None in (lat1, lon1, lat2, lon2):
            return None
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    active_stations = [s for s in project.stations if s.is_active]
    if active_stations:
        for d in project.demand_zones:
            reachable = False
            for st in active_stations:
                dist = haversine(st.latitude, st.longitude, d.latitude, d.longitude)
                if dist is None or dist <= (st.demand_service_radius_km or 0):
                    reachable = True
                    break
            if not reachable:
                issues.append({"level": "error",
                                "message": f"Demand zone {d.code} has no CNG station within its service radius - it cannot be served."})

    # scenario probability check
    default_scenarios = [s for s in project.scenarios if s.is_default]
    if default_scenarios:
        total_prob = sum(s.probability or 0 for s in default_scenarios)
        if abs(total_prob - 1.0) > 0.01:
            issues.append({"level": "warning",
                            "message": f"Default scenario probabilities sum to {total_prob:.2f}, not 1.00."})

    return issues
