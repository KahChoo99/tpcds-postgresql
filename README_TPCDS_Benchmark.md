#!/usr/bin/env python3
"""Execute TPC-DS SQL queries twice using psycopg2 (no EXPLAIN).

Writes one CSV row per query with two wall-clock timings, their average,
individual statuses and errors. Results are saved after every attempted run.
"""
import argparse
import csv
import os
import re
import time
from pathlib import Path

try:
    import psycopg2
except ImportError as exc:
    raise SystemExit("psycopg2 is not installed. Run: python3 -m pip install psycopg2-binary") from exc

FIELDS = ["query", "run_1_seconds", "run_2_seconds", "average_seconds",
          "run_1_status", "run_2_status", "errors"]


def parse_queries(value):
    if value.lower() == "all":
        return list(range(1, 100))
    numbers = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            a, b = map(int, part.split("-", 1))
            if a > b:
                raise ValueError("Query range must be increasing")
            numbers.extend(range(a, b + 1))
        else:
            numbers.append(int(part))
    if not numbers or any(n not in range(1, 100) for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("Select unique query numbers from 1 to 99")
    return numbers


def save_csv(path, rows):
    temp = path.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def execute_query(conn, path):
    if not path.is_file():
        return "MISSING", None, f"File not found: {path}"
    sql = path.read_text(encoding="utf-8")
    started = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)  # Executes the actual SQL, not EXPLAIN
            if cur.description is not None:
                # Drain all result rows so timing includes delivering the results;
                # do not keep them in memory or create per-query output files.
                while cur.fetchmany(1000):
                    pass
        return "SUCCESS", time.perf_counter() - started, ""
    except psycopg2.Error as e:
        elapsed = time.perf_counter() - started
        message = (e.pgerror or str(e)).strip().replace("\n", " ")
        status = "TIMEOUT" if e.pgcode == "57014" and "statement timeout" in message.lower() else "ERROR"
        return status, elapsed, message
    except Exception as e:
        return "ERROR", time.perf_counter() - started, str(e)


def main():
    parser = argparse.ArgumentParser(description="Run TPC-DS queries twice and write one CSV row per query")
    parser.add_argument("--query", "-q", default="all", help="all, 76, 1-10 or 1,3,76")
    parser.add_argument("--input", "-i", required=True, help="Folder containing query_1.sql ... query_99.sql")
    parser.add_argument("--output", "-o", required=True, help="Results folder")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5436)
    parser.add_argument("--user", default="tpcds")
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD", "tpcds"))
    parser.add_argument("--database", "-d", required=True)
    parser.add_argument("--timeout", type=int, default=0, help="Statement timeout per query in seconds; 0 = unlimited")
    args = parser.parse_args()
    try:
        numbers = parse_queries(args.query)
    except ValueError as exc:
        parser.error(str(exc))
    if args.timeout < 0:
        parser.error("--timeout cannot be negative")
    input_dir = Path(args.input)
    if not input_dir.is_dir():
        parser.error(f"Input directory does not exist: {input_dir}")
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "query_metrics.csv"
    if csv_path.exists():
        parser.error(f"Existing CSV will not be overwritten: {csv_path}. Choose a fresh output folder.")

    rows = [{"query": f"Q{n:02d}", "run_1_seconds": "", "run_2_seconds": "",
             "average_seconds": "", "run_1_status": "", "run_2_status": "", "errors": ""}
            for n in numbers]
    save_csv(csv_path, rows)
    print(f"Database: {args.database} at {args.host}:{args.port}", flush=True)
    print(f"Queries: {len(numbers)}; runs per query: 2", flush=True)
    print(f"CSV: {csv_path}", flush=True)

    try:
        conn = psycopg2.connect(host=args.host, port=args.port, user=args.user,
                                password=args.password, dbname=args.database, connect_timeout=10)
        conn.autocommit = True
        if args.timeout:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = %s", (args.timeout * 1000,))
    except psycopg2.Error as exc:
        raise SystemExit(f"Could not connect to database: {exc}") from exc

    try:
        # Like the reference script: run all queries in iteration 1, then again in iteration 2.
        for iteration in (1, 2):
            print(f"\nIteration {iteration}/2", flush=True)
            for number, row in zip(numbers, rows):
                print(f"Query {number}, run {iteration}...", flush=True)
                status, elapsed, error = execute_query(conn, input_dir / f"query_{number}.sql")
                row[f"run_{iteration}_status"] = status
                if elapsed is not None:
                    row[f"run_{iteration}_seconds"] = round(elapsed, 3)
                if error:
                    row["errors"] += f"Run {iteration}: {error} | "
                if row["run_1_status"] == "SUCCESS" and row["run_2_status"] == "SUCCESS":
                    row["average_seconds"] = round((row["run_1_seconds"] + row["run_2_seconds"]) / 2, 3)
                save_csv(csv_path, rows)
                print(f"  {status}; elapsed: {elapsed:.3f}s" if elapsed is not None else f"  {status}: {error}", flush=True)
    except KeyboardInterrupt:
        print(f"\nInterrupted. Completed results are saved in {csv_path}", flush=True)
    finally:
        conn.close()
    print(f"Results: {csv_path}", flush=True)


if __name__ == "__main__":
    main()
