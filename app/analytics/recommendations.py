"""
Generates explainable recommendations strictly from a solved result +
network snapshot. Every recommendation carries the numbers that produced
it (spec section 27/58 "Why?" requirement) - nothing here is a canned
string; each rule reads real utilization/concentration/shortage figures
off the result payload it's given.
"""

UTIL_BOTTLENECK = 0.90
UTIL_UNDERUSED = 0.30
SOURCE_CONCENTRATION_FLAG = 0.50  # a single source supplying >50% of used flow


def generate_recommendations(base_result: dict, severe_result: dict = None, base_nd=None) -> list:
    """base_result: an optimal deterministic solve under normal conditions.
    severe_result: optional optimal solve under a severe scarcity scenario,
    used for utilization-under-stress recommendations.
    base_nd: optional NetworkData snapshot, used for source concentration."""
    recs = []

    if base_result.get("status") != "optimal":
        return recs

    # 1. bottleneck / expansion candidates
    for f in base_result["facilities"]["cgs"] + base_result["facilities"]["stations"]:
        if not f["open"]:
            continue
        why = {"utilization_normal": f["utilization"]}
        severe_util = None
        if severe_result and severe_result.get("status") == "optimal":
            pool = severe_result["facilities"]["cgs"] + severe_result["facilities"]["stations"]
            match = next((x for x in pool if x["code"] == f["code"]), None)
            if match:
                severe_util = match["utilization"]
                why["utilization_severe_scenario"] = severe_util
        if f["utilization"] >= UTIL_BOTTLENECK or (severe_util is not None and severe_util >= 1.0):
            recs.append({
                "type": "expand_facility",
                "title": f"Consider expanding {f['code']}",
                "reason": f"Utilization is {f['utilization']*100:.0f}% under normal conditions"
                          + (f" and {severe_util*100:.0f}% under the severe scenario (over capacity)." if severe_util and severe_util >= 1.0
                             else "."),
                "why": why,
            })
        elif f["utilization"] < UTIL_UNDERUSED:
            recs.append({
                "type": "underutilized",
                "title": f"{f['code']} is underutilized",
                "reason": f"Running at {f['utilization']*100:.0f}% of capacity under normal conditions - "
                          f"review whether it's needed at its current size before further investment nearby.",
                "why": why,
            })

    # 2. source concentration
    if base_nd is not None:
        flows = base_result["flows"]["source_to_cgs"]
        total_flow = sum(fl["flow"] for fl in flows)
        by_source = {}
        for fl in flows:
            by_source[fl["from"]] = by_source.get(fl["from"], 0) + fl["flow"]
        if total_flow > 0:
            top_source, top_flow = max(by_source.items(), key=lambda kv: kv[1])
            share = top_flow / total_flow
            if share >= SOURCE_CONCENTRATION_FLAG:
                recs.append({
                    "type": "source_concentration",
                    "title": f"Network is concentrated on {top_source}",
                    "reason": f"{top_source} supplies {share*100:.0f}% of total gas flow in the optimal solution - "
                              f"a disruption there has an outsized network-wide impact.",
                    "why": {"source": top_source, "share_of_flow": round(share, 4)},
                })

    # 3. shortage-driven zones
    for d in base_result.get("demand_results", []):
        if d["unmet"] > 1e-6:
            recs.append({
                "type": "unmet_demand_zone",
                "title": f"{d['code']} is not fully served",
                "reason": f"{d['unmet']:.1f} units unmet ({(1-d['fulfilment_pct'])*100:.0f}% of demand), "
                          f"priority class: {d['priority']}.",
                "why": {"zone": d["code"], "unmet": d["unmet"], "priority": d["priority"]},
            })

    return recs
