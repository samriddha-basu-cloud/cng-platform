import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-in-production")
    # No database anywhere - every project is a JSON file, every optimization
    # run is a line in a JSONL log, all under this one folder. Easy to back
    # up (copy the folder), easy to inspect (they're just files), and easy
    # to host anywhere with a writable disk.
    DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "storage"))
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB upload cap (spec section 49: safe uploads)
