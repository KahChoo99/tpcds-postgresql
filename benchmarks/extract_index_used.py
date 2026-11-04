
#!/usr/bin/env python3

import argparse
import csv
import re
from pathlib import Path


def extract_indexes(plan_text):
    """Extract index names actually referenced by index scan nodes."""
    indexes = set()

    # PostgreSQL plan nodes such as:
    # Index Scan using idx_name on table_name
    # Index Only Scan using idx_name on table_name
    # Bitmap Index Scan on idx_name
    patterns = [
        r"\bIndex Scan using\s+([^\s]+)",
        r"\bIndex Only Scan using\s+([^\s]+)",
        r"\bBitmap Index Scan on\s+([^\s]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, plan_text, re.IGNORECASE):
            indexes.add(match.group(1).strip('"'))

    return sorted(indexes)


def main():
    parser = argparse.ArgumentParser(
        description="Add indexes used by each TPC-DS query to a CSV."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input benchmark results CSV",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results_with_indexes.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--plans",
        help="Directory containing QXX.run1.explain.txt files",
    )
    args = parser.parse_args()

    input_csv = Path(args.input).expanduser()
    output_csv = Path(args.output).expanduser()
    plan_dir = Path(args.plans).expanduser()

    if not input_csv.is_file():
        raise SystemExit(f"Input CSV not found: {input_csv}")

    if not plan_dir.is_dir():
        raise SystemExit(f"Plan directory not found: {plan_dir}")

    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise SystemExit("Input CSV has no header.")

        rows = list(reader)
        fieldnames = list(reader.fieldnames)

    if "indexes_used" not in fieldnames:
        fieldnames.append("indexes_used")

    missing_plans = []

    for row in rows:
        query = row.get("query", "").strip().upper()

        if not re.fullmatch(r"Q\d+", query):
            row["indexes_used"] = "INVALID_QUERY_ID"
            continue

        plan_file = plan_dir / f"{query}.run1.explain.txt"

        if not plan_file.is_file():
            row["indexes_used"] = "PLAN_NOT_FOUND"
            missing_plans.append(query)
            continue

        plan_text = plan_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        indexes = extract_indexes(plan_text)

        row["indexes_used"] = (
            ";".join(indexes) if indexes
            else "NONE (no index scan found)"
        )

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Input rows: {len(rows)}")
    print(f"Output saved to: {output_csv}")
    print(f"Queries without plan files: {len(missing_plans)}")

    if missing_plans:
        print("Missing plans:", ", ".join(missing_plans))


if __name__ == "__main__":
    main()
