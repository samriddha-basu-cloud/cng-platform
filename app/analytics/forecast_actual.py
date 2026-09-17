"""Forecast vs Actual (spec section 31): compares each demand zone's
planning forecast (monthly_demand, the number the optimizer actually used)
against its recorded actual_demand (observational, set via PATCH on the
demand-zone entity or the /api/analytics/<pid>/actuals route below), at
node, customer-segment, and overall level. This is deliberately read-only
analytics - it never feeds back into the optimizer on its own; that's the
job of a future rolling-horizon "update demand from actuals" step, not yet
wired in (see engine.solve_rolling_horizon's docstring).
"""


def _row(zone, month, forecast, actual):
    variance = actual - forecast
    abs_error = abs(variance)
    pct_error = abs_error / forecast if forecast else None
    return {
        "node": zone, "month": month, "forecast": round(forecast, 4), "actual": round(actual, 4),
        "variance": round(variance, 4), "absolute_error": round(abs_error, 4),
        "percentage_error": round(pct_error, 4) if pct_error is not None else None,
        "bias": round(variance, 4),  # signed - positive = actual ran over forecast
    }


def _aggregate(rows):
    if not rows:
        return {"mape": None, "bias": None, "count": 0}
    pct_errors = [r["percentage_error"] for r in rows if r["percentage_error"] is not None]
    forecasts = [r["forecast"] for r in rows]
    variances = [r["variance"] for r in rows]
    return {
        "mape": round(sum(pct_errors) / len(pct_errors), 4) if pct_errors else None,
        "bias": round(sum(variances) / sum(forecasts), 4) if sum(forecasts) else None,
        "mean_absolute_error": round(sum(r["absolute_error"] for r in rows) / len(rows), 4),
        "count": len(rows),
    }


def compute_forecast_vs_actual(nd) -> dict:
    rows = []
    for d, dinfo in nd.demand_zones.items():
        for month, actual in dinfo.get("actual_demand", {}).items():
            forecast = dinfo["monthly_demand"].get(month)
            if forecast is None:
                continue
            rows.append({**_row(d, month, forecast, actual), "demand_type": dinfo.get("demand_type", "Mixed")})

    by_node = {}
    for r in rows:
        by_node.setdefault(r["node"], []).append(r)
    node_summary = [{"node": node, **_aggregate(node_rows)} for node, node_rows in by_node.items()]

    by_type = {}
    for r in rows:
        by_type.setdefault(r["demand_type"], []).append(r)
    type_summary = [{"customer_segment": t, **_aggregate(type_rows)} for t, type_rows in by_type.items()]

    return {
        "rows": rows,
        "by_node": node_summary,
        "by_customer_segment": type_summary,
        "overall": _aggregate(rows),
    }
