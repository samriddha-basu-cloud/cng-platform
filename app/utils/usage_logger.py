"""
Simple usage/audit log: one CSV file, one row per meaningful action. No
database - just appends to a file under DATA_DIR/logs/usage_log.csv, so
you can open it in Excel or `tail -f` it directly on the server.
"""
import os
import csv
from datetime import datetime, timezone
from flask import current_app


def log_usage(event: str, project_id=None, detail: str = ""):
    try:
        logs_dir = os.path.join(current_app.config["DATA_DIR"], "logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, "usage_log.csv")
        is_new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["timestamp", "event", "project_id", "detail"])
            writer.writerow([datetime.now(timezone.utc).isoformat(), event, project_id or "", detail])
    except Exception:
        # usage logging must never break the actual request
        pass
