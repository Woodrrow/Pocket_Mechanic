"""Maintenance guides: generic procedures, tailored to a vehicle where we can.

Three layers, deliberately kept separate:

  1. Data/guides/*.json      the procedure itself, identical for every car
  2. Data/guide_rules.json   conditional edits keyed on vehicle ATTRIBUTES
  3. Data/vehicle_specs.json the per-car numbers (torque, part numbers)

Layers 2 and 3 are additive. A car we know nothing about still gets a usable
guide; it just carries more "not on file" and more "check before you start".
An attribute we cannot establish resolves to "unknown", never to a guess,
because a wrong "no electric parking brake" wrecks a caliper.
"""

import copy
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "Data"
GUIDES_DIR = DATA_DIR / "guides"
RULES_FILE = DATA_DIR / "guide_rules.json"
TRAITS_FILE = DATA_DIR / "vehicle_traits.json"
SPECS_FILE = DATA_DIR / "vehicle_specs.json"

DISCLAIMER = (
    "General guidance only, not a substitute for the workshop manual for your "
    "exact vehicle. Torque figures and part numbers must be verified before use. "
    "If you are not confident, have the work done by a qualified mechanic."
)

# Traits a rule may ask about. Anything not established resolves to "unknown".
TRAIT_KEYS = (
    "epb",
    "rear_brake_type",
    "rear_piston_type",
    "wear_sensor",
    "start_stop",
    "bms_registration",
    "battery_location",
    "has_dipstick",
)

UNKNOWN = "unknown"

_cache: dict = {}


class GuideError(Exception):
    """Raised when a guide cannot be built."""


# --- loading ---------------------------------------------------------------


def _load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _guides() -> dict[str, dict]:
    if "guides" not in _cache:
        guides = {}
        for path in sorted(GUIDES_DIR.glob("*.json")):
            guide = _load_json(path)
            guides[guide["id"]] = guide
        _cache["guides"] = guides
    return _cache["guides"]


def _rules() -> list[dict]:
    if "rules" not in _cache:
        _cache["rules"] = _load_json(RULES_FILE)["rules"]
    return _cache["rules"]


def _traits() -> list[dict]:
    if "traits" not in _cache:
        _cache["traits"] = _load_json(TRAITS_FILE)["traits"]
    return _cache["traits"]


def _specs() -> list[dict]:
    if "specs" not in _cache:
        _cache["specs"] = _load_json(SPECS_FILE)["specs"]
    return _cache["specs"]


def reload_data() -> None:
    """Drop the cache so edited JSON is picked up without a restart."""
    _cache.clear()


# --- matching --------------------------------------------------------------


def _norm(value) -> str:
    """Fold case, spacing and punctuation so 'ALFA ROMEO' matches 'Alfa Romeo'."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _entry_matches(entry: dict, make: str, model: str, year) -> bool:
    if _norm(entry.get("make")) != _norm(make):
        return False

    models = entry.get("models")
    if models and _norm(model) not in {_norm(m) for m in models}:
        return False

    if year is not None:
        if entry.get("year_from") is not None and year < entry["year_from"]:
            return False
        if entry.get("year_to") is not None and year > entry["year_to"]:
            return False

    return True


def _best_match(entries: list[dict], make: str, model: str, year) -> dict | None:
    """Most specific match wins: a make+model entry beats a make-wide one."""
    matches = [e for e in entries if _entry_matches(e, make, model, year)]
    if not matches:
        return None
    return max(matches, key=lambda e: len(e.get("models") or []) > 0)


# --- attributes ------------------------------------------------------------


def resolve_attributes(vehicle: dict | None, options: dict | None = None) -> dict:
    """Flatten a Zyfy vehicle record (plus caller options) into rule inputs."""
    vehicle = vehicle or {}
    options = options or {}

    make = vehicle.get("make") or ""
    model = vehicle.get("model") or ""
    year = vehicle.get("yearOfManufacture")
    fuel = (vehicle.get("fuelType") or "").lower() or UNKNOWN

    attrs: dict = {
        "make": make.title() if make else UNKNOWN,
        "model": model.title() if model else UNKNOWN,
        "year": year if year is not None else UNKNOWN,
        "fuel": fuel,
        "engine_cc": vehicle.get("engineCapacityCc", UNKNOWN),
        # Job options the caller supplies, e.g. which axle the brakes are on.
        "axle": (options.get("axle") or "unspecified").lower(),
    }

    # Every trait starts unknown and is only overwritten by a real match.
    for key in TRAIT_KEYS:
        attrs[key] = UNKNOWN

    matched = _best_match(_traits(), make, model, year) if make else None
    if matched:
        attrs.update(matched.get("set", {}))

    # DPFs became effectively universal on diesels with Euro 5 (Sept 2009).
    if fuel == "diesel" and isinstance(year, int):
        attrs["dpf"] = year >= 2009
    elif fuel in ("petrol", "electric", "hybrid electric"):
        attrs["dpf"] = False
    else:
        attrs["dpf"] = UNKNOWN

    return attrs


# --- rule evaluation -------------------------------------------------------


def _condition_met(condition: dict, attrs: dict) -> bool:
    value = attrs.get(condition["attr"], UNKNOWN)

    if "equals" in condition:
        return value == condition["equals"]
    if "not_equals" in condition:
        return value != condition["not_equals"]
    if "in" in condition:
        return value in condition["in"]
    if "not_in" in condition:
        return value not in condition["not_in"]
    if "gte" in condition:
        return isinstance(value, (int, float)) and value >= condition["gte"]
    if "lte" in condition:
        return isinstance(value, (int, float)) and value <= condition["lte"]

    raise GuideError(f"Unrecognised condition: {condition}")


def _rule_applies(rule: dict, job_id: str, attrs: dict) -> bool:
    applies_to = rule.get("applies_to", ["*"])
    if "*" not in applies_to and job_id not in applies_to:
        return False
    return all(_condition_met(c, attrs) for c in rule.get("when", []))


def _step_index(steps: list[dict], step_id: str) -> int:
    for i, step in enumerate(steps):
        if step["id"] == step_id:
            return i
    raise GuideError(f"Rule referenced unknown step '{step_id}'")


def _apply_effect(effect: dict, built: dict, rule_id: str) -> None:
    kind = effect["type"]

    if kind == "add_warning":
        built["warnings"].append(
            {
                "severity": effect.get("severity", "medium"),
                "text": effect["text"],
                "because_of": rule_id,
            }
        )
    elif kind == "add_tool":
        built["tools"].append({**effect["tool"], "because_of": rule_id})
    elif kind == "add_part":
        built["parts"].append({**effect["part"], "because_of": rule_id})
    elif kind == "insert_step":
        step = {**effect["step"], "because_of": rule_id}
        if "after" in effect:
            built["steps"].insert(_step_index(built["steps"], effect["after"]) + 1, step)
        elif "before" in effect:
            built["steps"].insert(_step_index(built["steps"], effect["before"]), step)
        else:
            built["steps"].append(step)
    elif kind == "replace_step":
        index = _step_index(built["steps"], effect["step_id"])
        built["steps"][index] = {**effect["step"], "because_of": rule_id}
    elif kind == "set_spec":
        built["_rule_specs"][effect["key"]] = effect["value"]
    else:
        raise GuideError(f"Unrecognised effect type: {kind}")


# --- specs -----------------------------------------------------------------


def _resolve_specs(guide: dict, attrs: dict, rule_specs: dict) -> list[dict]:
    declared = guide.get("specs", [])
    if not declared:
        return []

    values, source = {}, None
    entry = _best_match(_specs(), attrs.get("make"), attrs.get("model"), attrs.get("year"))
    if entry:
        values = entry.get("jobs", {}).get(guide["id"], {})
        source = entry.get("source", "vehicle_specs.json")

    resolved = []
    for spec in declared:
        key = spec["key"]
        if key in rule_specs:
            value, spec_source = rule_specs[key], "guide rule"
        else:
            value, spec_source = values.get(key), source

        resolved.append(
            {
                "key": key,
                "label": spec["label"],
                "unit": spec.get("unit"),
                "value": value,
                "source": spec_source if value is not None else None,
                "note": None
                if value is not None
                else "Not on file for this vehicle. Check the workshop manual before relying on a figure.",
            }
        )
    return resolved


# --- public API ------------------------------------------------------------


def list_guides() -> list[dict]:
    """Guide metadata only, no steps."""
    return [
        {
            "id": g["id"],
            "title": g["title"],
            "category": g["category"],
            "summary": g["summary"],
            "difficulty": g["difficulty"],
            "estimated_minutes": g["estimated_minutes"],
            "interval": g.get("interval"),
        }
        for g in sorted(_guides().values(), key=lambda g: (g["category"], g["title"]))
    ]


def build_guide(job_id: str, vehicle: dict | None = None, options: dict | None = None) -> dict:
    """A guide, with layer 2 and 3 applied if we have a vehicle to apply them to."""
    guide = _guides().get(job_id)
    if guide is None:
        raise GuideError(f"No guide with id '{job_id}'")

    guide = copy.deepcopy(guide)
    attrs = resolve_attributes(vehicle, options)

    built = {
        "warnings": [{"severity": "info", "text": w, "because_of": None} for w in guide.get("safety", [])],
        "tools": list(guide.get("tools", [])),
        "parts": list(guide.get("parts", [])),
        "steps": list(guide.get("steps", [])),
        "_rule_specs": {},
    }

    applied = []
    for rule in _rules():
        if _rule_applies(rule, job_id, attrs):
            applied.append(rule["id"])
            for effect in rule["effects"]:
                _apply_effect(effect, built, rule["id"])

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    built["warnings"].sort(key=lambda w: severity_order.get(w["severity"], 5))

    unknown_traits = sorted(k for k in TRAIT_KEYS if attrs.get(k) == UNKNOWN)

    return {
        "id": guide["id"],
        "title": guide["title"],
        "category": guide["category"],
        "summary": guide["summary"],
        "difficulty": guide["difficulty"],
        "estimated_minutes": guide["estimated_minutes"],
        "interval": guide.get("interval"),
        "options": guide.get("options", []),
        "tailored_to": None
        if vehicle is None
        else {
            "registration": vehicle.get("registration"),
            "make": attrs["make"],
            "model": attrs["model"],
            "year": attrs["year"],
            "fuel": attrs["fuel"],
        },
        "attributes": attrs,
        "unknown_attributes": unknown_traits,
        "applied_rules": applied,
        "warnings": built["warnings"],
        "tools": built["tools"],
        "parts": built["parts"],
        "specs": _resolve_specs(guide, attrs, built["_rule_specs"]),
        "steps": built["steps"],
        "disclaimer": DISCLAIMER,
    }


def recommend_guides(vehicle: dict) -> list[dict]:
    """Rank guides against what this car's MOT history keeps flagging."""
    signals = (vehicle or {}).get("signals") or {}
    failures = {c.lower() for c in signals.get("failureClusters") or []}
    advisories = {c.lower() for c in signals.get("advisoryClusters") or []}

    ranked = []
    for meta in list_guides():
        clusters = set(_guides()[meta["id"]].get("mot_clusters", []))
        hit_failure = clusters & failures
        hit_advisory = clusters & advisories

        if hit_failure:
            priority, reason = "high", (
                f"This car has failed an MOT on {', '.join(sorted(hit_failure))} before."
            )
        elif hit_advisory:
            priority, reason = "medium", (
                f"{', '.join(sorted(hit_advisory)).capitalize()} has come up as an MOT advisory on this car."
            )
        else:
            priority, reason = "routine", "Routine maintenance, not flagged on this car's MOT history."

        ranked.append({**meta, "priority": priority, "reason": reason})

    order = {"high": 0, "medium": 1, "routine": 2}
    ranked.sort(key=lambda g: (order[g["priority"]], g["title"]))
    return ranked
