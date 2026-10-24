
import argparse
import csv
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

FIELDS = [
    "query_number",
    "status",
    "planning_time_ms",
    "execution_time_ms",
    "wall_time_seconds",
    "error"
]

def extract_time(output, name):
    match = re.search(
        rf"{name}:\s*([\d.]+)\s*ms",
        output
    )
    return float(match.group(1)) if match else None


def execute_query(number, input_dir, output_dir,
                  container, database):

    query_file = input_dir / f"query_{number}.sql"
    output_file = output_dir / f"query_{number}.explain.txt"

    row = {
        "query_number": number,
        "status": "FAILED",
        "planning_time_ms": "",
        "execution_time_ms": "",
        "wall_time_seconds": "",
        "error": ""
    }

    if not query_file.is_file():
        row["status"] = "MISSING"
        row["error"] = "SQL file not found"
        print(f"Query {number}: MISSING", flush=True)
        return row

    raw_sql = query_file.read_text(encoding="utf-8")

    clean_sql = "\n".join(
        line for line in raw_sql.splitlines()
        if not line.strip().startswith("--")
    ).strip()

    if not clean_sql:
        row["error"] = "Empty SQL query"
        output_file.write_text(row["error"], encoding="utf-8")
        return row

    explain_sql = (
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
        + clean_sql
    )

    command = [
        "docker", "exec", "-i", container,
        "psql",
        "-X",
        "-v", "ON_ERROR_STOP=1",
        "-U", "tpcds",
        "-d", database,
        "-A", "-t"
    ]

    print(f"Executing Query {number}...", flush=True)
    start = time.perf_counter()

    try:
        result = subprocess.run(
            command,
            input=explain_sql,
            text=True,
            capture_output=True,
            encoding="utf-8"
        )

        elapsed = time.perf_counter() - start
        row["wall_time_seconds"] = round(elapsed, 3)

        output = result.stdout

        if result.stderr:
            output += "\n--- STDERR ---\n" + result.stderr

        output_file.write_text(output, encoding="utf-8")

        planning = extract_time(result.stdout, "Planning Time")
        execution = extract_time(result.stdout, "Execution Time")

        if planning is not None:
            row["planning_time_ms"] = planning

        if execution is not None:
            row["execution_time_ms"] = execution

        if result.returncode == 0 and execution is not None:
            row["status"] = "SUCCESS"
        else:
            row["status"] = "FAILED"
            row["error"] = (
                result.stderr.strip()[:1000]
                or "Missing Execution Time"
            )

        print(
            f"Query {number}: {row['status']} | "
            f"DB execution: {row['execution_time_ms']} ms | "
            f"Wall: {row['wall_time_seconds']} s",
            flush=True
        )

    except Exception as exc:
        row["wall_time_seconds"] = round(
            time.perf_counter() - start, 3
        )
        row["error"] = str(exc)
        output_file.write_text(
            f"ERROR: {exc}", encoding="utf-8"
        )
        print(f"Query {number}: FAILED - {exc}", flush=True)

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-q", "--query", required=True)
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-c", "--container", default="tpcds-postgres")
    parser.add_argument("-d", "--database", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.query.lower() == "all":
        query_numbers = list(range(1, 100))
    elif "," in args.query:
        query_numbers = [
            int(q.strip()) for q in args.query.split(",")
        ]
    elif "-" in args.query:
        start, end = map(int, args.query.split("-"))
        query_numbers = list(range(start, end + 1))
    else:
        query_numbers = [int(args.query)]

    if not input_dir.is_dir():
        parser.error(f"Input directory not found: {input_dir}")

    csv_file = output_dir / "query_metrics.csv"
    summary_file = output_dir / "benchmark_summary.txt"

    # Prevent accidental overwriting of previous measurements
    if csv_file.exists() or summary_file.exists():
        parser.error(
            "Results already exist in this directory. "
            "Use a new output directory to preserve them."
        )

    rows = []
    start_timestamp = datetime.now(timezone.utc)
    start = time.perf_counter()

    print(f"Database: {args.database}", flush=True)
    print(f"Started: {start_timestamp.isoformat()}", flush=True)

    try:
        with csv_file.open(
            "w", newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            f.flush()

            for number in query_numbers:
                row = execute_query(
                    number, input_dir, output_dir,
                    args.container, args.database
                )
                rows.append(row)
                writer.writerow(row)
                f.flush()

    finally:
        end_timestamp = datetime.now(timezone.utc)
        total_wall = time.perf_counter() - start

        successful = [
            row for row in rows if row["status"] == "SUCCESS"
        ]

        total_db_ms = sum(
            row["execution_time_ms"]
            for row in successful
        )

        summary = (
            f"Database: {args.database}\n"
            f"Started UTC: {start_timestamp.isoformat()}\n"
            f"Finished UTC: {end_timestamp.isoformat()}\n"
            f"Requested queries: {len(query_numbers)}\n"
            f"Completed queries: {len(rows)}\n"
            f"Successful queries: {len(successful)}\n"
            f"Failed or missing: {len(rows) - len(successful)}\n"
            f"Total benchmark wall time (s): {total_wall:.3f}\n"
            f"Total benchmark wall time (min): {total_wall / 60:.3f}\n"
            f"Sum of successful DB execution times (ms): "
            f"{total_db_ms:.3f}\n"
            f"Sum of successful DB execution times (min): "
            f"{total_db_ms / 60000:.3f}\n"
        )

        if len(successful) == len(query_numbers):
            summary += "Status: ALL REQUESTED QUERIES SUCCEEDED\n"
        else:
            summary += "Status: INCOMPLETE OR ERRORS PRESENT\n"

        summary_file.write_text(summary, encoding="utf-8")
        print("\n" + summary, flush=True)


if __name__ == "__main__":
    main()
