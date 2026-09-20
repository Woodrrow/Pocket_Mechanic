#!/usr/bin/env python3
"""
Real MOT 2022 data: what's answerable today, and what's still missing.

MOT_HISTORY/ currently has:
  - test_result_2022.csv   one row per MOT test (pass/fail) - no defect detail
  - item_detail.csv        rfr_id -> description: a *lookup* table for what each code means
  - item_group.csv         test_item_id -> item_name (category lookup)
  - mdr_*.csv              small code -> label lookups (fuel type, test outcome, test type, ...)

None of these link an *individual test* to the *specific rfr_id(s)* found on it.
That link lives in DVSA's separate "MOT testing data failure item (2022)" download,
on the same data.gov.uk page test_result_2022.csv came from - it isn't in
MOT_HISTORY/ yet. item_detail.csv only tells you what a code *means*; it doesn't
say which tests had it. So "most common faults per car" genuinely can't be
computed yet - doing it with what's here would mean making the per-test defect
data up.

What this script does instead, against the real files you do have:
  1. Real pass/fail stats per make/model from test_result_2022.csv
  2. Real code -> description decoding via item_detail.csv
  3. Prints the exact join to add once the failure-item file is downloaded

Run:
    python Data/demo_common_faults.py
"""

import duckdb

con = duckdb.connect()

con.execute("""
    CREATE VIEW test_result AS
    SELECT * FROM read_csv('MOT_HISTORY/test_result_2022.csv', delim='|')
""")
con.execute("""
    CREATE VIEW item_detail AS
    SELECT * FROM read_csv('MOT_HISTORY/item_detail.csv', delim='|')
""")

# --- 1) Real, answerable today: pass rate by make/model, busiest models first
print("Pass rate by make/model, 2022 (top 15 most-tested, normal tests only):\n")
rows = con.execute("""
    SELECT
        make,
        model,
        COUNT(*) AS tests,
        ROUND(100.0 * SUM(CASE WHEN test_result = 'P' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pass_rate_pct
    FROM test_result
    WHERE test_type = 'NT'  -- normal test; excludes retests/appeals/abandoned
    GROUP BY make, model
    HAVING COUNT(*) >= 500
    ORDER BY tests DESC
    LIMIT 15
""").fetchall()
for make, model, tests, pass_rate in rows:
    print(f"  {make:<14} {model:<20} {tests:>8} tests   {pass_rate}% pass")

# --- 2) Real code decoding: what a handful of rfr_ids actually mean
print("\nSample of real defect-code decodes from item_detail.csv:\n")
rows = con.execute("""
    SELECT rfr_id, rfr_desc, rfr_deficiency_category, minor_item
    FROM item_detail
    WHERE rfr_desc IS NOT NULL AND rfr_desc != ''
    LIMIT 8
""").fetchall()
for rfr_id, desc, category, minor in rows:
    print(f"  [{rfr_id}] ({category}, minor={minor}) {desc}")

# --- 3) The join that becomes possible once the failure-item file is added
print(
    "\nOnce a per-test defect file (e.g. MOT_HISTORY/test_item_2022.csv, DVSA's\n"
    "'failure item' download, with columns like test_id + rfr_id) is added,\n"
    "per-vehicle fault counts become:\n"
    "\n"
    "    CREATE VIEW test_item AS\n"
    "        SELECT * FROM read_csv('MOT_HISTORY/test_item_2022.csv', delim='|');\n"
    "\n"
    "    SELECT r.make, r.model, d.rfr_desc, COUNT(*) AS occurrences\n"
    "    FROM test_result AS r\n"
    "    JOIN test_item   AS i ON r.test_id = i.test_id\n"
    "    JOIN item_detail AS d ON i.rfr_id  = d.rfr_id\n"
    "    GROUP BY r.make, r.model, d.rfr_desc\n"
    "    ORDER BY r.make, r.model, occurrences DESC;\n"
)
