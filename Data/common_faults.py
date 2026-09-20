#!/usr/bin/env python3
"""
Compute the most common faults per make/model from DVSA's anonymised MOT
bulk data, for a given year.

Needs four files in MOT_HISTORY/ for that year:
  - test_result_<year>.csv   one row per test: make, model, test_class_id, ...
  - test_item_<year>.csv     one row per defect found on a test:
                              test_id, rfr_id, rfr_type_code, location_id, dangerous_mark
  - item_detail.csv          (rfr_id, test_class_id) -> rfr_desc, deficiency category
                              (shared lookup table, not year-specific)
  - item_group.csv           (test_item_id, test_class_id) -> item_name, parent_id
                              a tree of vehicle components/sections (shared, not year-specific)

rfr_desc alone is terse ("efficiency below requirements", "not working") because
DVSA splits a defect into *what component* (item_group, a tree e.g.
Brakes > Brake performance > Gradient hand brake) and *what's wrong with it*
(item_detail.rfr_desc). This script walks the item_group tree once (it's only
~4k rows) to get each defect's immediate component name and its full
breadcrumb path, then prefixes rfr_desc with the component name so entries
read like "Gradient hand brake efficiency below requirements" instead of just
"efficiency below requirements".

"Fault" means a defect that actually failed the test. rfr_type_code values are:
    F  Fail      - failed the test
    P  PRS       - would have failed, but rectified at the station during test
    M  Minor     - post-May-2018 category; noted, doesn't fail the vehicle
    A  Advisory  - noted, doesn't fail the vehicle
By default this counts F + P only. Use --include-minor / --include-advisories
to fold those back in if you want a broader "things noted on this car" view
instead of "things that failed it".

item_detail.csv's real unique key is (rfr_id, test_class_id), not rfr_id alone
- the same rfr_id repeats under different test classes with different
descriptions (7,505 distinct rfr_id values but 21,069 rows). The join here
matches on both columns to avoid double-counting from that fan-out.

Usage:
    python Data/common_faults.py --year 2022
    python Data/common_faults.py --year 2022 --top 5 --min-tests 500
    python Data/common_faults.py --year 2023 --include-minor --out MOT_HISTORY/common_faults_2023.json
"""

import argparse
import json
import shutil
import string
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
MOT_DIR = ROOT / "MOT_HISTORY"

FAULT_TYPES = {
    "fail": "F",
    "prs": "P",
    "minor": "M",
    "advisory": "A",
}


def pick_spill_dir(min_free_bytes: int = 5 * 1024**3) -> Path | None:
    """Pick the drive with the most free space for DuckDB's on-disk spill
    files, and return a subfolder on it. A join this size (86M x 42M rows)
    needs scratch disk space beyond RAM; on this machine C: was down to
    1.5GB free (out of 446GB) which is what caused the first OOM - D: has
    365GB free, so that's preferred automatically when available.
    """
    candidates = [Path(f"{letter}:/") for letter in string.ascii_uppercase if Path(f"{letter}:/").exists()]
    best, best_free = None, -1
    for root in candidates:
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = root, free

    if best is None or best_free < min_free_bytes:
        return None

    spill_dir = best / "duckdb_spill_tmp"
    spill_dir.mkdir(exist_ok=True)
    return spill_dir


def build_component_lookup(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """For every (test_item_id, test_class_id) in item_group.csv, resolve its
    own name ("component") and the full root->leaf breadcrumb ("component_path"),
    e.g. component="Gradient hand brake",
         component_path="Brakes > Brake performance > Gradient hand brake".

    item_group is a small tree (~4k rows: test_item_id, test_class_id, parent_id,
    item_name), so this is done once in Python rather than as a SQL recursive
    query - simpler to guard against cycles/missing parents that way.
    """
    rows = con.execute("SELECT test_item_id, test_class_id, parent_id, item_name FROM item_group").fetchall()
    by_key = {(tid, tcid): (parent_id, name) for tid, tcid, parent_id, name in rows}

    lookup = []
    for key, (_, own_name) in by_key.items():
        chain = []
        current, seen = key, set()
        while current in by_key and current not in seen:
            seen.add(current)
            parent_id, name = by_key[current]
            chain.append(name)
            if parent_id == 0 or parent_id == current[0]:
                break
            current = (parent_id, current[1])
        chain.reverse()
        lookup.append((key[0], key[1], own_name, " > ".join(chain)))
    return lookup


def run(year: int, top_n: int, min_tests: int, type_codes: list[str]) -> list[dict]:
    result_file = MOT_DIR / f"test_result_{year}.csv"
    item_file = MOT_DIR / f"test_item_{year}.csv"
    detail_file = MOT_DIR / "item_detail.csv"
    group_file = MOT_DIR / "item_group.csv"
    for f in (result_file, item_file, detail_file, group_file):
        if not f.exists():
            raise FileNotFoundError(f"Missing required file: {f}")

    con = duckdb.connect()

    spill_dir = pick_spill_dir()
    if spill_dir:
        con.execute(f"PRAGMA temp_directory='{spill_dir.as_posix()}'")
        free_gb = shutil.disk_usage(spill_dir).free / 1024**3
        print(f"DuckDB spill directory: {spill_dir} ({free_gb:.1f} GB free)")
    else:
        print("Warning: no drive found with enough free space for DuckDB spill files - the join may OOM.")

    # DuckDB's default memory_limit is 80% of *total* system RAM, not what's
    # actually free right now. On a machine already under memory pressure that
    # makes it try to grab RAM that doesn't physically exist and fail outright
    # instead of spilling to disk in time. Cap it well below typical free RAM
    # so it spills to spill_dir early instead of hitting a hard allocation error.
    con.execute("PRAGMA memory_limit='4GB'")

    # Only the columns actually used downstream - a join this size (86M x 42M
    # rows) is much lighter on memory built from 4-5 narrow columns than from
    # test_result's full 14 and test_item's full 5.
    con.execute(f"""
        CREATE VIEW test_result AS
        SELECT test_id, make, model, test_class_id, test_type, test_result
        FROM read_csv('{result_file.as_posix()}', delim='|')
    """)
    con.execute(f"""
        CREATE VIEW test_item AS
        SELECT test_id, rfr_id, rfr_type_code
        FROM read_csv('{item_file.as_posix()}', delim='|')
    """)
    con.execute(f"CREATE VIEW item_detail AS SELECT * FROM read_csv('{detail_file.as_posix()}', delim='|')")
    con.execute(f"CREATE VIEW item_group  AS SELECT * FROM read_csv('{group_file.as_posix()}', delim='|')")

    con.execute("""
        CREATE TABLE component_path (
            test_item_id INTEGER, test_class_id INTEGER, component VARCHAR, component_path VARCHAR
        )
    """)
    con.executemany("INSERT INTO component_path VALUES (?, ?, ?, ?)", build_component_lookup(con))

    type_list = ", ".join(f"'{t}'" for t in type_codes)

    rows = con.execute(f"""
        WITH model_tests AS (
            SELECT make, model, COUNT(*) AS tests
            FROM test_result
            WHERE test_type = 'NT'
            GROUP BY make, model
        ),
        fault_counts AS (
            SELECT
                r.make,
                r.model,
                TRIM(d.rfr_desc) AS defect,
                COALESCE(cp.component, 'General') AS component,
                cp.component_path,
                d.rfr_deficiency_category AS category,
                COUNT(*) AS occurrences
            FROM test_result AS r
            JOIN test_item AS i
                ON r.test_id = i.test_id
            JOIN item_detail AS d
                ON i.rfr_id = d.rfr_id AND r.test_class_id = d.test_class_id
            LEFT JOIN component_path AS cp
                ON d.test_item_id = cp.test_item_id AND d.test_class_id = cp.test_class_id
            WHERE i.rfr_type_code IN ({type_list})
            GROUP BY r.make, r.model, TRIM(d.rfr_desc), cp.component, cp.component_path, d.rfr_deficiency_category
        ),
        ranked AS (
            SELECT
                f.*,
                ROW_NUMBER() OVER (
                    PARTITION BY f.make, f.model ORDER BY f.occurrences DESC
                ) AS rank
            FROM fault_counts AS f
            JOIN model_tests AS t ON f.make = t.make AND f.model = t.model
            WHERE t.tests >= {min_tests}
        )
        SELECT make, model, defect, component, component_path, category, occurrences
        FROM ranked
        WHERE rank <= {top_n}
        ORDER BY make, model, occurrences DESC
    """).fetchall()

    return [
        {
            "make": make,
            "model": model,
            "description": build_description(component, defect),
            "component": component,
            "component_path": component_path,
            "defect": defect,
            "category": category,
            "occurrences": occurrences,
        }
        for make, model, defect, component, component_path, category, occurrences in rows
    ]


def build_description(component: str, defect: str) -> str:
    """Combine a component name and its raw rfr_desc into a readable sentence.

    Some rfr_desc text already repeats the component name (e.g. component
    "Tread depth" + defect "tread depth below requirements of 1.6mm"), so
    concatenating unconditionally would read "Tread depth tread depth below
    requirements of 1.6mm". Detect that overlap and use the defect text alone.
    """
    if component == "General" or defect.lower().startswith(component.lower()):
        return defect[0].upper() + defect[1:] if defect else defect
    return f"{component} {defect}".strip()


def to_nested(rows: list[dict]) -> dict:
    """[{make, model, description, ...}] -> {make: {model: [{description, ...}]}}"""
    nested: dict = {}
    for row in rows:
        make_bucket = nested.setdefault(row["make"], {})
        model_bucket = make_bucket.setdefault(row["model"], [])
        model_bucket.append(
            {
                "description": row["description"],
                "component": row["component"],
                "component_path": row["component_path"],
                "category": row["category"],
                "occurrences": row["occurrences"],
            }
        )
    return nested


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2022, help="MOT data year to process (default: 2022)")
    parser.add_argument("--top", type=int, default=10, help="Top N faults to keep per make/model (default: 10)")
    parser.add_argument(
        "--min-tests", type=int, default=200,
        help="Skip make/models with fewer than this many normal tests (default: 200)",
    )
    parser.add_argument("--include-minor", action="store_true", help="Also count 'Minor' (non-failing) items")
    parser.add_argument("--include-advisories", action="store_true", help="Also count 'Advisory' (non-failing) items")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path (default: MOT_HISTORY/common_faults_<year>.json)")
    parser.add_argument("--preview", type=int, default=5, help="Number of make/model combos to print to the console (default: 5)")
    args = parser.parse_args()

    type_codes = [FAULT_TYPES["fail"], FAULT_TYPES["prs"]]
    if args.include_minor:
        type_codes.append(FAULT_TYPES["minor"])
    if args.include_advisories:
        type_codes.append(FAULT_TYPES["advisory"])

    out_path = args.out or (MOT_DIR / f"common_faults_{args.year}.json")

    start = time.time()
    rows = run(args.year, args.top, args.min_tests, type_codes)
    elapsed = time.time() - start

    nested = to_nested(rows)
    out_path.write_text(json.dumps(nested, indent=2), encoding="utf-8")

    print(f"{args.year}: {len(rows)} defect rows across {len(nested)} makes in {elapsed:.1f}s")
    print(f"Wrote {out_path}\n")

    combos = [(make, model, faults) for make, models in nested.items() for model, faults in models.items()]
    print(f"Preview (first {args.preview} make/model combos):")
    for make, model, faults in combos[: args.preview]:
        print(f"\n{make} {model}")
        for f in faults:
            print(f"  {f['occurrences']:>7}x  [{f['category']}] {f['description']}")


if __name__ == "__main__":
    main()
