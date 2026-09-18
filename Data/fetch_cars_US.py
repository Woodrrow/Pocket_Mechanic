#!/usr/bin/env python3
"""
Build a static makes/models JSON for a UK car-details form.

Source: NHTSA vPIC (free, no key, no rate limit published).
Because vPIC is a US registry, this script:
  - only keeps makes on a UK allowlist
  - maps US-registry names to UK names (Opel -> Vauxhall)
  - merges in a hand-maintained overrides file for what vPIC misses

Usage:
    python build_vehicles.py --from 2005 --to 2026 --out vehicles.json
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"

# Makes worth offering on a UK form. vPIC name on the left where it differs.
# Format: vPIC make name -> name you want to show the user.
UK_MAKES = {
    "ABARTH": "Abarth",
    "ALFA ROMEO": "Alfa Romeo",
    "ASTON MARTIN": "Aston Martin",
    "AUDI": "Audi",
    "BENTLEY": "Bentley",
    "BMW": "BMW",
    "BYD": "BYD",
    "CHEVROLET": "Chevrolet",
    "CHRYSLER": "Chrysler",
    "CITROEN": "Citroen",
    "DACIA": "Dacia",
    "FIAT": "Fiat",
    "FORD": "Ford",
    "GENESIS": "Genesis",
    "HONDA": "Honda",
    "HYUNDAI": "Hyundai",
    "INFINITI": "Infiniti",
    "ISUZU": "Isuzu",
    "JAGUAR": "Jaguar",
    "JEEP": "Jeep",
    "KIA": "Kia",
    "LAND ROVER": "Land Rover",
    "LEXUS": "Lexus",
    "LOTUS": "Lotus",
    "MASERATI": "Maserati",
    "MAZDA": "Mazda",
    "MCLAREN": "McLaren",
    "MERCEDES-BENZ": "Mercedes-Benz",
    "MG": "MG",
    "MINI": "Mini",
    "MITSUBISHI": "Mitsubishi",
    "NISSAN": "Nissan",
    "OPEL": "Vauxhall",          # UK badge for the same cars
    "PEUGEOT": "Peugeot",
    "POLESTAR": "Polestar",
    "PORSCHE": "Porsche",
    "RENAULT": "Renault",
    "ROLLS-ROYCE": "Rolls-Royce",
    "SAAB": "Saab",
    "SEAT": "SEAT",
    "SKODA": "Skoda",
    "SMART": "Smart",
    "SUBARU": "Subaru",
    "SUZUKI": "Suzuki",
    "TESLA": "Tesla",
    "TOYOTA": "Toyota",
    "VOLKSWAGEN": "Volkswagen",
    "VOLVO": "Volvo",
}

# vPIC model names carry trim and drivetrain noise. Strip these tokens.
NOISE = re.compile(
    r"\b(4matic|quattro|xdrive|sdrive|awd|fwd|rwd|4wd|2wd|4x4|4x2"
    r"|hybrid|phev|plug-?in|electric|ev|bev|mhev|tdi|tsi|tfsi|hdi|dci|crdi"
    r"|automatic|manual|dsg|cvt|convertible|coupe|saloon|estate|hatchback"
    r"|cabriolet|roadster|sportback|avant|touring|wagon|van)\b",
    re.IGNORECASE,
)

# Models vPIC will never have, or gets wrong. Edit this by hand as you find gaps.
OVERRIDES_DEFAULT = {
    "Vauxhall": [
        "Adam", "Agila", "Ampera", "Antara", "Astra", "Cascada", "Combo",
        "Corsa", "Crossland", "Grandland", "Insignia", "Meriva", "Mokka",
        "Vectra", "Viva", "Vivaro", "Zafira",
    ],
    "Ford": ["Ka", "Ka+", "Puma", "Tourneo", "Transit", "Grand C-Max"],
    "Nissan": ["Qashqai", "Juke", "Note", "Micra", "X-Trail", "Ariya"],
    "Toyota": ["Yaris", "Aygo", "Aygo X", "Auris", "Corolla", "C-HR", "Proace"],
    "Peugeot": ["108", "208", "308", "508", "2008", "3008", "5008", "Rifter"],
    "Citroen": ["C1", "C3", "C3 Aircross", "C4", "C5 Aircross", "Berlingo"],
    "Renault": ["Clio", "Captur", "Megane", "Scenic", "Kadjar", "Zoe", "Austral"],
    "Dacia": ["Sandero", "Duster", "Jogger", "Logan", "Spring"],
    "SEAT": ["Ibiza", "Leon", "Arona", "Ateca", "Tarraco", "Alhambra", "Mii"],
    "Skoda": ["Fabia", "Octavia", "Superb", "Kamiq", "Karoq", "Kodiaq", "Enyaq",
              "Citigo", "Scala", "Yeti", "Roomster"],
    "Volkswagen": ["Polo", "Golf", "Passat", "Tiguan", "T-Roc", "T-Cross", "Up",
                   "Touran", "Sharan", "ID.3", "ID.4", "ID.5", "ID.7"],
    "MG": ["MG3", "MG4", "MG5", "ZS", "HS", "MG2", "Cyberster"],
    "Hyundai": ["i10", "i20", "i30", "i40", "Tucson", "Kona", "Ioniq",
                "Ioniq 5", "Ioniq 6", "Bayon", "Santa Fe"],
    "Kia": ["Picanto", "Rio", "Ceed", "Sportage", "Niro", "Stonic", "EV6",
            "EV3", "Sorento", "Xceed"],
    "BMW": ["1 Series", "2 Series", "3 Series", "4 Series", "5 Series",
            "6 Series", "7 Series", "8 Series", "X1", "X2", "X3", "X4", "X5",
            "X6", "X7", "Z4", "i3", "i4", "iX", "iX1", "iX3"],
    "Mercedes-Benz": ["A-Class", "B-Class", "C-Class", "E-Class", "S-Class",
                      "CLA", "CLS", "GLA", "GLB", "GLC", "GLE", "GLS", "V-Class",
                      "EQA", "EQB", "EQC", "EQE", "EQS", "Vito", "Sprinter"],
    "Audi": ["A1", "A3", "A4", "A5", "A6", "A7", "A8", "Q2", "Q3", "Q4 e-tron",
             "Q5", "Q7", "Q8", "TT", "R8", "e-tron", "e-tron GT"],
    "Mini": ["Hatch", "Clubman", "Countryman", "Convertible", "Paceman", "Coupe"],
    "Land Rover": ["Defender", "Discovery", "Discovery Sport", "Freelander",
                   "Range Rover", "Range Rover Sport", "Range Rover Evoque",
                   "Range Rover Velar"],
    "Fiat": ["500", "500L", "500X", "Panda", "Punto", "Tipo", "Doblo", "600"],
    "Honda": ["Jazz", "Civic", "CR-V", "HR-V", "e", "ZR-V"],
    "Mazda": ["2", "3", "6", "CX-3", "CX-30", "CX-5", "CX-60", "MX-5", "MX-30"],
    "Volvo": ["V40", "V60", "V90", "S60", "S90", "XC40", "XC60", "XC90",
              "EX30", "EX40", "EX90"],
    "Suzuki": ["Swift", "Vitara", "S-Cross", "Ignis", "Jimny", "Celerio"],
    "Tesla": ["Model 3", "Model S", "Model X", "Model Y", "Cybertruck"],
}


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                print(f"  ! giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


def clean_model(raw):
    """Strip trim/drivetrain noise and normalise spacing and case."""
    name = NOISE.sub("", raw)
    name = re.sub(r"\s+", " ", name).strip(" -/")
    if not name or len(name) > 40:
        return None
    # Leave all-caps short names (BMW X5, MG ZS) and alphanumerics alone;
    # title-case anything that looks like a shouted word.
    def fix(word):
        # Handle hyphenated shouting: A-CLASS -> A-Class, X-TRAIL -> X-Trail
        if "-" in word:
            return "-".join(fix(p) for p in word.split("-"))
        if len(word) > 3 and word.isalpha() and word.isupper():
            return word.capitalize()
        return word

    return " ".join(fix(w) for w in name.split())


def dedupe(models):
    """Case-insensitive dedupe, keeping the first-seen spelling."""
    seen, out = set(), []
    for m in models:
        key = m.lower().replace("-", " ").replace(".", "")
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def build(year_from, year_to, overrides):
    result = defaultdict(list)

    for vpic_name, uk_name in sorted(UK_MAKES.items()):
        print(f"{uk_name} ...", flush=True)
        collected = []
        for year in range(year_from, year_to + 1):
            url = (
                f"{BASE}/GetModelsForMakeYear/make/{quote(vpic_name)}"
                f"/modelyear/{year}?format=json"
            )
            data = fetch(url)
            if not data:
                continue
            for row in data.get("Results", []):
                cleaned = clean_model(row.get("Model_Name", ""))
                if cleaned:
                    collected.append(cleaned)
            time.sleep(0.15)  # be polite

        collected.extend(overrides.get(uk_name, []))
        models = dedupe(sorted(collected, key=str.lower))
        result[uk_name] = models
        print(f"  {len(models)} models")

    # Makes that exist only in overrides (vPIC had nothing at all)
    for make, models in overrides.items():
        if make not in result:
            result[make] = dedupe(sorted(models, key=str.lower))

    return dict(sorted(result.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="year_from", type=int, default=2005)
    ap.add_argument("--to", dest="year_to", type=int, default=2026)
    ap.add_argument("--out", default="vehicles.json")
    ap.add_argument(
        "--overrides",
        help="JSON file of {make: [models]} merged in on top of vPIC. "
             "Defaults to the built-in list.",
    )
    ap.add_argument("--pretty", action="store_true", help="indent the output")
    args = ap.parse_args()

    overrides = OVERRIDES_DEFAULT
    if args.overrides:
        overrides = json.loads(Path(args.overrides).read_text())

    data = build(args.year_from, args.year_to, overrides)

    out = Path(args.out)
    out.write_text(
        json.dumps(data, indent=2 if args.pretty else None, ensure_ascii=False)
    )

    makes = len(data)
    models = sum(len(v) for v in data.values())
    size = out.stat().st_size / 1024
    print(f"\nWrote {out}: {makes} makes, {models} models, {size:.0f} KB")


if __name__ == "__main__":
    main()