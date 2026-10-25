"""
TPC-DS query performance test on PostgreSQL in Docker. No extra installs.

Two measurement modes:
  default            plain execution, time from psql's \\timing
                     (statement sent -> full result received)
  --explain-analyze  runs EXPLAIN (ANALYZE, BUFFERS) and uses the server's
                     "Execution Time"; the plan of every run is saved

The whole suite is repeated for the number of runs given with -n / --runs
(default 3). Input folder, output folder and database come from the command
line.
"""
import argparse
import csv
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_queries(spec):
    if spec is None or spec.lower() == "all":
        return None
    if "," in spec:
        return [int(q.strip()) for q in spec.split(",")]
    if "-" in spec:
        a, b = map(int, spec.split("-"))
        return list(range(a, b + 1))
    return [int(spec)]


def find_query_files(input_dir, selection):
    """Map query number -> file. Accepts query_4.sql, query-04.sql, Q04.sql..."""
    files = {}
    for path in input_dir.glob("*.sql"):
        m = re.search(r"(\d+)", path.stem)
        if m:
            files[int(m.group(1))] = path
    if selection is not None:
        return ({n: files[n] for n in selection if n in files},
                [n for n in selection if n not in files], [])
    # "all" means queries 1-99. Anything else (e.g. query_0.sql, the combined
    # stream file that dsqgen can create) is skipped so it is not run by accident.
    skipped = [files[n].name for n in sorted(files) if not 1 <= n <= 99]
    return ({n: files[n] for n in sorted(files) if 1 <= n <= 99}, [], skipped)


def split_statements(raw_sql):
    """Strip -- comments and split into statements (queries 14, 23, 24 and 39
    contain two statements per file)."""
    cleaned = "\n".join(
        line for line in raw_sql.splitlines()
        if not line.strip().startswith("--")
    )
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def psql_command(args):
    return [
        "docker", "exec", "-i", args.container,
        "psql", "-X",
        "-v", "ON_ERROR_STOP=1",
        "-U", args.user,
        "-d", args.database,
        "-A", "-t",
    ]


def extract_timing_lines(output):
    """'Time: X ms' values printed by psql \\timing (one per statement)."""
    return [float(m) for m in re.findall(r"^Time:\s*([\d.]+)\s*ms", output, re.M)]


def extract_execution_times(output):
    """'Execution Time: X ms' values printed by EXPLAIN ANALYZE."""
    return [float(m) for m in re.findall(r"Execution Time:\s*([\d.]+)\s*ms", output)]


def clean_output(output):
    """Remove psql's own messages."""
    skip = re.compile(r"^(Timing is (on|off)\.|Time: .*|SET)$")
    return "\n".join(l for l in output.splitlines() if not skip.match(l)) + "\n"


def run_query(args, statements):
    """Execute all statements of one query once; return (seconds, output text)."""
    setup = []
    if args.statement_timeout_ms:
        setup.append(f"SET statement_timeout = {args.statement_timeout_ms};")
    for item in args.set:
        key, value = item.split("=", 1)
        setup.append(f"SET {key.strip()} = '{value.strip()}';")
    setup_sql = "\n".join(setup) + "\n"

    if args.explain_analyze:
        options = "ANALYZE, BUFFERS" + (", TIMING OFF" if args.no_timing else "")
        body = ";\n".join(f"EXPLAIN ({options})\n{s}" for s in statements) + ";\n"
        sql_in = setup_sql + body
    else:
        # \timing is switched on AFTER the SET commands so they are not counted
        sql_in = setup_sql + "\\timing on\n" + ";\n".join(statements) + ";\n"

    result = subprocess.run(
        psql_command(args),
        input=sql_in,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if args.explain_analyze:
        times = extract_execution_times(result.stdout)
    else:
        times = extract_timing_lines(result.stdout)

    if result.returncode != 0 or len(times) != len(statements):
        err = result.stderr.strip() or "No timing returned by psql"
        raise RuntimeError(" ".join(err.split()))
    return sum(times) / 1000.0, clean_output(result.stdout)


def get_metadata(args):
    query = (
        "SELECT 'version=' || version();"
        "SELECT 'setting ' || name || '=' || setting || coalesce(unit, '') "
        "FROM pg_settings WHERE name IN ('shared_buffers','work_mem',"
        "'effective_cache_size','max_parallel_workers_per_gather',"
        "'random_page_cost','jit');"
        "SELECT 'analyzed ' || relname || '=' || "
        "(coalesce(last_analyze, last_autoanalyze) IS NOT NULL) "
        "FROM pg_stat_user_tables "
        "WHERE relname IN ('store_sales','catalog_sales','web_sales');"
    )
    result = subprocess.run(
        psql_command(args), input=query, text=True,
        capture_output=True, encoding="utf-8",
    )
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    if result.returncode != 0:
        lines.append(f"metadata error: {result.stderr.strip()[:300]}")
    return lines


def build_fields(runs):
    return (["query", "status"]
            + [f"exec_time_run_{i}" for i in range(1, runs + 1)]
            + ["avg_exec_time", "median_exec_time", "min_exec_time",
               "max_exec_time", "error"])


def build_row(number, times, errors, runs):
    row = {"query": f"Q{number:02d}", "status": "",
           "error": " | ".join(errors)[:1500]}
    ok = [t for t in times if t is not None]
    for i in range(1, runs + 1):
        t = times[i - 1] if i <= len(times) else None
        row[f"exec_time_run_{i}"] = "" if t is None else round(t, 3)
    if ok:
        row["avg_exec_time"] = round(statistics.mean(ok), 3)
        row["median_exec_time"] = round(statistics.median(ok), 3)
        row["min_exec_time"] = round(min(ok), 3)
        row["max_exec_time"] = round(max(ok), 3)
    attempted = len(times)
    if attempted == 0:
        row["status"] = ""
    elif attempted < runs:
        row["status"] = "IN_PROGRESS"
    elif len(ok) == attempted:
        row["status"] = "SUCCESS"
    elif ok:
        row["status"] = "PARTIAL"
    else:
        row["status"] = "FAILED"
    return row


def write_csv(csv_file, rows, runs):
    """Rewrite the summary CSV (written to a temp file first, then swapped in,
    so the file is never left half-written)."""
    fields = build_fields(runs)
    tmp = csv_file.with_name(csv_file.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
    tmp.replace(csv_file)



def main():
    p = argparse.ArgumentParser(description="Run TPC-DS queries on PostgreSQL in Docker.")
    p.add_argument("-i", "--input", required=True, help="folder with the .sql query files")
    p.add_argument("-o", "--output", required=True, help="folder for results (must be new)")
    p.add_argument("-d", "--database", required=True, help="database name, e.g. tpcds_sf1")
    p.add_argument("-q", "--query", default="1-99", help="1-99 (default) | all | 4 | 1,4,7 | 1-10")
    p.add_argument("-n", "-r", "--runs", "--iterations", dest="iterations",
                   type=int, default=3,
                   help="how many times the whole suite is run (default 3)")
    p.add_argument("--explain-analyze", action="store_true",
                   help="use EXPLAIN (ANALYZE, BUFFERS) and save every plan")
    p.add_argument("--order", choices=["query", "suite"], default="query",
                   help="query (default): all runs of a query back to back, then the "
                        "next query; suite: run every query once, then repeat the suite")
    p.add_argument("--no-timing", action="store_true",
                   help="with --explain-analyze: add TIMING OFF (less overhead)")
    p.add_argument("-c", "--container", default="tpcds-postgres")
    p.add_argument("-u", "--user", default="tpcds")
    p.add_argument("--statement-timeout-ms", type=int, default=0,
                   help="abort any query running longer than this (0 = off)")
    p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                   help="session setting, e.g. --set work_mem=256MB")
    p.add_argument("--no-save-results", action="store_true",
                   help="do not save result rows / plans")
    args = p.parse_args()

    if args.iterations < 1:
        p.error("--runs must be at least 1")
    if args.no_timing and not args.explain_analyze:
        p.error("--no-timing only works together with --explain-analyze")

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    if not input_dir.is_dir():
        p.error(f"Input directory not found: {input_dir}")
    csv_file = output_dir / "exec_time_details.csv"
    summary_file = output_dir / "benchmark_summary.txt"
    if csv_file.exists() or summary_file.exists():
        p.error("Results already exist in this directory. "
                "Use a new output directory to preserve them.")
    output_dir.mkdir(parents=True, exist_ok=True)
    save_dir = output_dir / ("plans" if args.explain_analyze else "results")
    if not args.no_save_results:
        save_dir.mkdir(exist_ok=True)

    files, missing, skipped = find_query_files(input_dir, parse_queries(args.query))
    if not files:
        p.error("No query files found for that selection.")
    numbers = list(files)
    statements = {n: split_statements(files[n].read_text(encoding="utf-8"))
                  for n in numbers}

    if args.explain_analyze:
        method = ("EXPLAIN (ANALYZE, BUFFERS"
                  + (", TIMING OFF" if args.no_timing else "")
                  + "), server 'Execution Time'")
    else:
        method = "plain execution via psql \\timing (no EXPLAIN)"

    metadata = get_metadata(args)
    print(f"Database: {args.database}")
    print(f"Method: {method}")
    for line in metadata:
        print("  " + line)
    if any(l.startswith("analyzed") and l.endswith("=false") for l in metadata):
        print("WARNING: some big tables have no statistics. "
              "Run VACUUM ANALYZE before benchmarking.")
    if missing:
        print(f"WARNING: no file found for queries {missing}")
    if skipped:
        print(f"NOTE: skipped files that are not queries 1-99: {skipped}")

    times = {n: [] for n in numbers}
    errors = {n: [] for n in numbers}
    saved = set()

    # The CSV is created right away and updated after every query
    def snapshot():
        write_csv(csv_file,
                  [build_row(n, times[n], errors[n], args.iterations)
                   for n in numbers], args.iterations)

    snapshot()
    start_ts = datetime.now(timezone.utc)
    start = time.perf_counter()
    if args.order == "query":
        schedule = [(it, n) for n in numbers for it in range(1, args.iterations + 1)]
    else:
        schedule = [(it, n) for it in range(1, args.iterations + 1) for n in numbers]
    run_seconds = [0.0] * args.iterations

    try:
        last_it = last_n = None
        for it, n in schedule:
            if args.order == "suite" and it != last_it:
                print(f"\nRun {it} of {args.iterations}\n")
            elif args.order == "query" and n != last_n:
                print()
            last_it, last_n = it, n

            secs, err = None, ""
            q_start = time.perf_counter()
            try:
                secs, text = run_query(args, statements[n])
                print(f"Q{n:02d} run {it}/{args.iterations}: Success, "
                      f"Execution Time: {secs:.2f}s", flush=True)
            except Exception as exc:
                err = str(exc)[:300]
                print(f"Q{n:02d} run {it}/{args.iterations}: ERROR - {err}", flush=True)
            run_seconds[it - 1] += time.perf_counter() - q_start

            if secs is not None:
                times[n].append(secs)
                if not args.no_save_results:
                    try:
                        if args.explain_analyze:
                            (save_dir / f"Q{n:02d}.run{it}.explain.txt").write_text(
                                text, encoding="utf-8")
                        elif n not in saved:
                            (save_dir / f"Q{n:02d}.txt").write_text(
                                text, encoding="utf-8")
                            saved.add(n)
                    except OSError as exc:
                        print(f"Q{n:02d}: could not save output: {exc}")
            else:
                times[n].append(None)
                errors[n].append(f"run{it}: {err}")

            # saved immediately, so a cancelled run keeps everything so far
            snapshot()

            if args.order == "suite" and n == numbers[-1]:
                print(f"\nRun {it}: total run time for {len(numbers)} queries: "
                      f"{run_seconds[it - 1] / 3600:.2f}hr ({run_seconds[it - 1]:.1f}s)")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving what has been measured so far...")
    finally:
        rows = [build_row(n, times[n], errors[n], args.iterations)
                for n in numbers]
        write_csv(csv_file, rows, args.iterations)

        end_ts = datetime.now(timezone.utc)
        done = min(len(times[n]) for n in numbers)
        total = time.perf_counter() - start
        good = [r for r in rows if r["status"] == "SUCCESS"]
        bad = [r["query"] for r in rows if r["status"] != "SUCCESS"]
        sum_avg = sum(r.get("avg_exec_time", 0) or 0 for r in rows)

        summary = (
            f"Database: {args.database}\n"
            f"Method: {method}\n"
            f"Started UTC: {start_ts.isoformat()}\n"
            f"Finished UTC: {end_ts.isoformat()}\n"
            f"Runs requested: {args.iterations}, completed for every query: {done}\n"
            f"Run order: {'all runs of a query back to back' if args.order == 'query' else 'whole suite repeated'}\n"
            f"Session settings applied: {args.set or 'none'}\n"
            f"Statement timeout (ms): {args.statement_timeout_ms or 'off'}\n"
            f"Queries: {len(numbers)}\n"
            f"Fully successful queries: {len(good)}\n"
            f"Queries with errors or not completed: {bad or 'none'}\n"
            f"Time spent per run number (s): {[round(x, 1) for x in run_seconds]}\n"
            f"Total benchmark wall time (min): {total / 60:.3f}\n"
            f"Sum of average query times (s): {sum_avg:.3f}\n"
            f"\nServer info:\n" + "\n".join(metadata) + "\n"
        )
        summary_file.write_text(summary, encoding="utf-8")
        print("\n" + summary)


if __name__ == "__main__":
    main()
