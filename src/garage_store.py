import json
from pathlib import Path
from threading import Lock

# Project root, one level up from src/, regardless of the process cwd.
GARAGE_FILE = Path(__file__).resolve().parent.parent / "garage.json"
_lock = Lock()


def load_garage() -> list[dict]:
    if not GARAGE_FILE.exists():
        return []
    with GARAGE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def _save_garage(entries: list[dict]) -> None:
    with GARAGE_FILE.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def add_vehicle(record: dict) -> list[dict]:
    """Add (or replace, keyed by registration) a vehicle record and persist to garage.json."""
    with _lock:
        entries = load_garage()
        entries = [e for e in entries if e.get("registration") != record.get("registration")]
        entries.append(record)
        _save_garage(entries)
        return entries
