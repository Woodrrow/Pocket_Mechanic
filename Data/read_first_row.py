#!/usr/bin/env python3
"""
Print the header and first data row of a (possibly huge) CSV/TSV file.

Reads only as many lines as needed - never loads the whole file into memory,
which matters for files like MOT_HISTORY/test_result.csv (3.6GB, ~42M rows).

Usage:
    python Data/read_first_row.py MOT_HISTORY/test_result.csv
    python Data/read_first_row.py path/to/file.csv --delimiter ,
"""

import argparse
import csv


def read_first_row(path: str, delimiter: str | None = None) -> tuple[list[str], list[str]]:
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        if delimiter is None:
            sample = f.readline()
            f.seek(0)
            delimiter = "|" if sample.count("|") >= sample.count(",") else ","

        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader)
        try:
            first_row = next(reader)
        except StopIteration:
            first_row = []

    return header, first_row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to the CSV/TSV file")
    parser.add_argument(
        "--delimiter",
        default=None,
        help="Field delimiter (auto-detected between ',' and '|' if omitted)",
    )
    args = parser.parse_args()

    header, first_row = read_first_row(args.csv_path, args.delimiter)

    print(f"Columns ({len(header)}):")
    for name in header:
        print(f"  - {name}")

    print("\nFirst row:")
    if not first_row:
        print("  (file has a header but no data rows)")
    else:
        for name, value in zip(header, first_row):
            print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
