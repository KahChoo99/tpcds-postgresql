#!/usr/bin/env python3
"""
Run from the repository root on your Mac:

  caffeinate -i python3 4_load_test_independent_configured_final.py --sf 2 --run-id run1 \
    --indexes-sql indexes_nonclustered_14.sql \
    --clustered-indexes-sql indexes_clustered_8.sql \
    --cluster-sql cluster_four_tables.sql
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

TABLES = (
    "call_center", "catalog_page", "catalog_returns", "catalog_sales",
    "customer", "customer_address", "customer_demographics", "date_dim",
    "household_demographics", "income_band", "inventory", "item",
    "promotion", "reason", "ship_mode", "store", "store_returns",
    "store_sales", "time_dim", "warehouse", "web_page", "web_returns",
    "web_sales", "web_site",
)
SCENARIOS = ("baseline", "indexed_14", "clustered_8")

DB_SETTINGS = {
    "effective_cache_size": "10GB",      
    "jit": "off",
    "max_parallel_workers_per_gather": "4",
    "random_page_cost": "1.1",
    "work_mem": "524288kB",        
}
EXPECTED_POSTGRES_VERSION = "16.15"
MEMORY_SETTINGS = frozenset(("effective_cache_size", "shared_buffers", "work_mem"))
ALL_SETTINGS = tuple(DB_SETTINGS) + ("shared_buffers",)


def size_to_bytes(value: str) -> int:
    """Convert PostgreSQL size text (e.g. 10GB or 524288kB) to bytes."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|kB|MB|GB|TB)\s*",
                         value, re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported PostgreSQL size value: {value!r}")
    amount = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "mb": 1024 ** 2,
        "gb": 1024 ** 3,
        "tb": 1024 ** 4,
    }
    return int(amount * multipliers[unit])


def expected_setting_value(name: str):
    if name in MEMORY_SETTINGS:
        return size_to_bytes(DB_SETTINGS[name])
    if name == "max_parallel_workers_per_gather":
        return int(DB_SETTINGS[name])
    if name == "random_page_cost":
        return float(DB_SETTINGS[name])
    if name == "jit":
        return False
    raise KeyError(name)


def parse_json_result(output: str, description: str) -> dict:
    try:
        obj = json.loads(output.strip())
        if not isinstance(obj, dict):
            raise ValueError("Expected JSON object")
        return obj
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse {description}: {output[-500:]}") from exc


def probe_config(container: str, user: str, database: str) -> dict:
    names = ",".join("'" + name + "'" for name in ALL_SETTINGS)
    memory = ",".join("'" + name + "'" for name in sorted(MEMORY_SETTINGS))
    sql = f"""
        SELECT json_build_object(
          'database', current_database(),
          'server_version', current_setting('server_version'),
          'version', version(),
          'postmaster_started_at', pg_postmaster_start_time(),
          'settings', (
              SELECT json_agg(json_build_object(
                  'name', name,
                  'effective', current_setting(name),
                  'bytes', CASE WHEN name IN ({memory})
                          THEN pg_size_bytes(current_setting(name)) END,
                  'source', source,
                  'context', context,
                  'pending_restart', pending_restart
              ) ORDER BY name)
              FROM pg_settings WHERE name IN ({names})
          )
        )::text;
    """
    return parse_json_result(run(psql(container, user, database, sql, raw=True)),
                             "PostgreSQL configuration probe")


def validate_config(probe: dict, *, database: str, baseline_start: str | None = None,
                    require_db_source: bool = True) -> list[dict]:
    if probe.get("database") != database:
        raise RuntimeError(f"Connected to wrong database: {probe.get('database')} != {database}")
    ver = str(probe.get("server_version", ""))
    if not (ver == EXPECTED_POSTGRES_VERSION or
            ver.startswith(EXPECTED_POSTGRES_VERSION + " ")):
        raise RuntimeError(f"PostgreSQL version mismatch: expected "
                           f"{EXPECTED_POSTGRES_VERSION}, got {ver!r}. "
                           "Version is a SERVER setting, not per database.")
    if baseline_start is not None and probe.get("postmaster_started_at") != baseline_start:
        raise RuntimeError("PostgreSQL server restarted during benchmark: "
                           f"was {baseline_start}, now {probe.get('postmaster_started_at')}")
    entries = probe.get("settings") or []
    by_name = {row["name"]: row for row in entries}
    rows = []
    problems = []
    for name in ALL_SETTINGS:
        got = by_name.get(name)
        if got is None:
            problems.append(f"Missing {name} from pg_settings")
            continue
        if name == "shared_buffers":
            observed = got.get("bytes")
            if observed is None:
                problems.append("Cannot read the effective shared_buffers value")
            rows.append({
                "parameter": name,
                "expected": "record actual value; unchanged",
                "effective": got.get("effective"),
                "source": got.get("source"),
                "context": got.get("context"),
                "pending_restart": got.get("pending_restart"),
                "matches": "recorded" if observed is not None else False,
            })
            continue
        expected = expected_setting_value(name)
        if name in MEMORY_SETTINGS:
            observed = got.get("bytes")
            equal = observed is not None and int(observed) == expected
            expected_print = DB_SETTINGS[name]
        elif name == "jit":
            observed = got.get("effective", "").lower() in ("on", "true", "yes")
            equal = observed == expected
            expected_print = "off"
        elif name == "max_parallel_workers_per_gather":
            observed = int(got.get("effective", -1))
            equal = observed == expected
            expected_print = str(expected)
        else:
            observed = float(got.get("effective", "nan"))
            equal = abs(observed - expected) < 1e-9
            expected_print = "1.1"
        if name in DB_SETTINGS and require_db_source and got.get("source") != "database":
            equal = False
            problems.append(f"{name} source is {got.get('source')!r}, not 'database'")
        if got.get("pending_restart"):
            equal = False
            problems.append(f"{name} is pending a restart")
        rows.append({"parameter": name, "expected": expected_print,
                     "effective": got.get("effective"), "source": got.get("source"),
                     "context": got.get("context"), "pending_restart": got.get("pending_restart"),
                     "matches": bool(equal)})
        if not equal:
            problems.append(f"{name}: expected {expected_print}, effective="
                            f"{got.get('effective')!r}, source={got.get('source')!r}")
    if problems:
        raise RuntimeError("PostgreSQL configuration verification FAILED for "
                           + database + ": " + "; ".join(problems))
    return rows


def install_db_defaults(container: str, user: str, db: str) -> None:
    for name, value in DB_SETTINGS.items():
        sql = f"ALTER DATABASE \"{db}\" SET {name} = '{value}';"
        run(psql(container, user, "postgres", sql))


def validate_server_only(probe: dict) -> None:
    ver = str(probe.get("server_version", ""))
    if not (ver == EXPECTED_POSTGRES_VERSION or
            ver.startswith(EXPECTED_POSTGRES_VERSION + " ")):
        raise RuntimeError(f"PostgreSQL server version is {ver!r}, expected "
                           f"{EXPECTED_POSTGRES_VERSION}.")
    row = next((r for r in probe.get("settings", [])
                if r["name"] == "shared_buffers"), None)
    if row is None or row.get("bytes") is None:
        raise RuntimeError("Cannot read shared_buffers from pg_settings")
    # Record the effective value and source; no fixed value is enforced.


def check_analyze(container: str, user: str, db: str) -> dict:
    """Read actual PostgreSQL analyze timestamps for all 24 TPC-DS tables."""
    sql = """
        SELECT coalesce(json_object_agg(relname,
             json_build_object(
               'analyzed', (last_analyze IS NOT NULL OR last_autoanalyze IS NOT NULL),
               'last_analyze', last_analyze,
               'last_autoanalyze', last_autoanalyze
             )), '{}'::json)::text
        FROM pg_stat_user_tables WHERE schemaname = 'public';
    """
    obj = parse_json_result(run(psql(container, user, db, sql, raw=True)),
                            "ANALYZE verification")
    missing = [name for name in TABLES if name not in obj or not obj[name]["analyzed"]]
    if missing:
        raise RuntimeError(f"ANALYZE verification failed in {db}; missing/unanalyzed: {missing}")
    return {name: obj[name] for name in TABLES}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def roundup_tenth(seconds: float) -> float:
    """TPC-DS 7.1.16: elapsed seconds rounded UP to 0.1 s."""
    return math.ceil(seconds * 10 - 1e-10) / 10


def run(command: list[str], *, data: bytes | None = None) -> str:
    result = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    output = result.stdout.decode("utf-8", errors="replace")
    if result.returncode:
        tail = "\n".join(output.splitlines()[-25:])
        raise RuntimeError(f"Command returned {result.returncode}: "
                           f"{' '.join(command)}\n{tail}")
    return output


def psql(container: str, user: str, database: str, statement: str,
         raw: bool = False) -> list[str]:
    cmd = ["docker", "exec", container, "psql", "-X", "-v", "ON_ERROR_STOP=1",
           "-U", user, "-d", database]
    if raw:
        cmd.append("-At")
    return cmd + ["-c", statement]


def schema_command(container: str, user: str, database: str) -> list[str]:
    return ["docker", "exec", "-i", container, "psql", "-X", "-v",
            "ON_ERROR_STOP=1", "-U", user, "-d", database, "-f", "-"]


def log_line(logpath: Path, line: str) -> None:
    msg = f"[{now()}] {line}"
    print(msg, flush=True)
    with logpath.open("a", encoding="utf-8") as stream:
        stream.write(msg + "\n")


def get_sql(path: Path, kind: str) -> list[tuple[str, str, str]]:
    if not path.is_file():
        raise RuntimeError(f"Cannot find {kind} SQL file: {path}")
    content = path.read_text(encoding="utf-8-sig")
    content = re.sub(r"(?m)^[ \t]*--[^\n]*(?:\n|$)", "", content)
    statements = [piece.strip() + ";" for piece in content.split(";")
                  if piece.strip()]
    parsed: list[tuple[str, str, str]] = []
    for statement in statements:
        if kind == "index":
            match = re.fullmatch(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+"
                r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]\w*)\s+ON\s+"
                r"(?:public\.)?([a-z_]\w*)\s*\(.+?\)\s*"
                r"(?:INCLUDE\s*\(.+?\)\s*)?;",
                statement, re.I | re.S,
            )
            if not match:
                raise RuntimeError(f"Expected simple CREATE INDEX statement in {path}: {statement}")
            name, table = (part.lower() for part in match.groups())
        elif kind == "cluster":
            match = re.fullmatch(
                r"CLUSTER\s+(?:public\.)?([a-z_]\w*)\s+USING\s+"
                r"([a-z_]\w*)\s*;", statement, re.I | re.S)
            if not match:
                raise RuntimeError(f"Expected CLUSTER ... USING ... in {path}: {statement}")
            table, name = (part.lower() for part in match.groups())
        else:
            raise ValueError(kind)
        parsed.append((name, table, statement))
    if not parsed:
        raise RuntimeError(f"No SQL found in {path}")
    return parsed


def validate_sql(index14: list[tuple[str, str, str]],
                 index8: list[tuple[str, str, str]],
                 clusters: list[tuple[str, str, str]]) -> None:
    if len(index14) != 14 or len(index8) != 8 or len(clusters) != 4:
        raise RuntimeError("Expected 14 non-clustered indexes, 8 clustered-scenario "
                           "indexes and 4 CLUSTER statements")
    for group in (index14, index8):
        names = [name for name, _, _ in group]
        if len(set(names)) != len(names):
            raise RuntimeError("Duplicate index names found")
        if any(table not in TABLES for _, table, _ in group):
            raise RuntimeError("An index references an unknown TPC-DS table")
    by_name = {name: table for name, table, _ in index8}
    clustered_tables: set[str] = set()
    for name, table, _ in clusters:
        if by_name.get(name) != table:
            raise RuntimeError(f"Invalid CLUSTER: {table} USING {name} "
                               "(must match a defined 8-index CREATE INDEX)")
        if table in clustered_tables:
            raise RuntimeError(f"CLUSTER specified twice for {table}")
        clustered_tables.add(table)


def get_indexes(container: str, user: str, database: str) -> set[str]:
    result = run(psql(container, user, database,
                      "SELECT indexname FROM pg_indexes "
                      "WHERE schemaname='public' ORDER BY indexname;", raw=True))
    return set(result.strip().splitlines()) if result.strip() else set()


def get_clustered(container: str, user: str, database: str) -> set[str]:
    result = run(psql(container, user, database,
                      "SELECT tbl.relname || ':' || idx.relname "
                      "FROM pg_index i "
                      "JOIN pg_class idx ON idx.oid = i.indexrelid "
                      "JOIN pg_class tbl ON tbl.oid = i.indrelid "
                      "JOIN pg_namespace ns ON ns.oid = tbl.relnamespace "
                      "WHERE ns.nspname='public' AND i.indisclustered;",
                      raw=True))
    return set(result.strip().splitlines()) if result.strip() else set()


def persist(report: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "load_results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with (outdir / "scenario_totals.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = ["scenario", "database", "status", "schema_s", "copy_s",
                   "indexes_s", "cluster_s", "analyze_s", "sum_phase_times_s",
                   "measured_total_s", "tload_rounded_up_0_1_s", "rows_loaded"]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for name in SCENARIOS:
            item = report["scenarios"].get(name)
            if item:
                writer.writerow({k: item.get(k, "") for k in columns})

    with (outdir / "phase_times.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = ["scenario", "database", "phase", "operation", "duration_s",
                   "rows_loaded", "status"]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report["steps"])

    with (outdir / "config_verification.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = ["scenario", "database", "when", "parameter", "expected",
                   "effective", "source", "context", "pending_restart", "matches"]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report.get("config_checks", []))

    with (outdir / "analyze_verification.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = ["scenario", "database", "table", "analyzed", "last_analyze", "last_autoanalyze"]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for scenario_name, scenario_data in report["scenarios"].items():
            for table, info in scenario_data.get("analyze_verification", {}).items():
                writer.writerow({"scenario": scenario_name,
                                 "database": scenario_data["database"],
                                 "table": table,
                                 "analyzed": info["analyzed"],
                                 "last_analyze": info.get("last_analyze"),
                                 "last_autoanalyze": info.get("last_autoanalyze")})

    with (outdir / "index_times.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = ["scenario", "database", "index_name", "duration_s"]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report["indexes"])

    shared_buffers_actual = "unavailable"
    for setting in report.get("server_preflight", {}).get("settings", []):
        if setting.get("name") == "shared_buffers":
            shared_buffers_actual = setting.get("effective", "unavailable")
            break

    lines = [
        "TPC-DS PostgreSQL: independent fresh-database load tests",
        f"SF: {report['scale_factor']}, run ID: {report['run_id']}",
        f"Status: {report['status']}",
        f"Started: {report['started_at']}",
        f"Finished: {report['finished_at'] or 'INCOMPLETE'}", "",
        "Scenario          Database                                  Measured TLOAD (s)",
        "--------------------------------------------------------------------------",
    ]
    for scenario in SCENARIOS:
        item = report["scenarios"].get(scenario)
        if item:
            measured = item.get("measured_total_s")
            result = f"{measured:.3f} (ceil 0.1s: {item['tload_rounded_up_0_1_s']:.1f})" if measured is not None else "INCOMPLETE"
            lines.append(f"{scenario:<17} {item['database']:<41} {result}")
    lines += [
        "", "Each result is measured independently from a fresh empty database.",
        "CREATE DATABASE takes place BEFORE the load timer.",
        "Start timer: immediately before creating the 24 tables.",
        "Stop timer: immediately after the scenario's ANALYZE completes.",
        "dsdgen is neither run nor timed. COPY occurs separately in EACH database.",
        "The sum of phase times may differ slightly from wall-clock load time",
        "because wall-clock includes driver/logging overhead between phases.",
        "Baseline retains only schema-created indexes (e.g. primary keys).",
        "Indexed scenario adds exactly 14 regular indexes.",
        "Clustered scenario adds exactly 8 regular indexes and clusters 4 tables.",
        "Indexed vs clustered comparisons also vary the index count.",
        "ANALYZE is executed independently on ALL 24 tables in EVERY scenario.",
        "Database session defaults set before timing and verified before + after:",
        *[f"  {name} = {value}" for name, value in DB_SETTINGS.items()],
        f"shared_buffers = {shared_buffers_actual} (actual server value; recorded, not modified).",
        f"Server PostgreSQL version must equal {EXPECTED_POSTGRES_VERSION}.",
        "Effective values and their sources saved in config_verification.csv.",
        "Actual ANALYZE timestamps saved in analyze_verification.csv and load_results.json.",
        "This is an academic load-time comparison, not a certified TPC-DS result.",
        f"Error: {report.get('error') or 'none'}",
    ]
    (outdir / "load_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def timed_sql(report: dict, logpath: Path, scenario: str, db: str,
              phase: str, operation: str, command: list[str],
              input_data: bytes | None = None) -> float:
    log_line(logpath, f"{scenario}: START {phase} {operation}")
    begin = time.perf_counter()
    status = "SUCCESS"
    rows: int | str = ""
    try:
        output = run(command, data=input_data)
        if phase == "copy":
            match = re.search(r"(?m)^COPY\s+(\d+)\s*$", output)
            if not match:
                raise RuntimeError(f"No COPY row count for {db}.{operation}: {output[-300:]}")
            rows = int(match.group(1))
        return time.perf_counter() - begin
    except BaseException:
        status = "FAILED"
        raise
    finally:
        seconds = time.perf_counter() - begin
        report["steps"].append({
            "scenario": scenario, "database": db, "phase": phase,
            "operation": operation, "duration_s": round(seconds, 6),
            "rows_loaded": rows, "status": status,
        })
        log_line(logpath, f"{scenario}: END   {phase} {operation}: "
                          f"{seconds:.3f}s [{status}]"
                          + (f" ({rows} rows)" if rows != "" else ""))


def load_scenario(args: argparse.Namespace, scenario: str, db: str,
                  container_dir: str, schema: bytes,
                  index14: list[tuple[str, str, str]],
                  index8: list[tuple[str, str, str]],
                  clusters: list[tuple[str, str, str]],
                  report: dict, logpath: Path) -> None:
    log_line(logpath, f"Creating fresh database {db} (not timed)")
    run(psql(args.container, args.user, "postgres", f'CREATE DATABASE "{db}";'))
    # Per-DB settings, as well as their verification, are done BEFORE TLOAD.
    # Every subsequent psql call opens a fresh DB session and inherits them.
    install_db_defaults(args.container, args.user, db)
    config_before = probe_config(args.container, args.user, db)
    before_rows = validate_config(config_before, database=db,
                                  baseline_start=report["server_preflight"]["postmaster_started_at"])
    report["config_checks"].extend([
        {"scenario": scenario, "database": db, "when": "before", **row}
        for row in before_rows
    ])
    log_line(logpath, f"{scenario}: VERIFIED settings before load: "
             + ", ".join(f"{r['parameter']}={r['effective']}" for r in before_rows))
    item: dict = {
        "scenario": scenario, "database": db, "status": "RUNNING",
        "schema_s": 0.0, "copy_s": 0.0, "indexes_s": 0.0,
        "cluster_s": 0.0, "analyze_s": 0.0,
        "rows_loaded": 0,
        "load_start_at": None, "load_end_at": None,
    }
    report["scenarios"][scenario] = item
    selected = index14 if scenario == "indexed_14" else (index8 if scenario == "clustered_8" else [])

    # TLOAD is measured independently for each fresh DB from the start of DDL
    # through completion of ANALYZE.  No dsdgen, resets or other scenarios.
    start = time.perf_counter()
    item["load_start_at"] = now()
    try:
        item["schema_s"] += timed_sql(
            report, logpath, scenario, db, "schema", "CREATE TABLE statements",
            schema_command(args.container, args.user, db), input_data=schema) or 0

        for table in TABLES:
            sql = (f'COPY "{table}" FROM \'{container_dir}/{table}.dat\' '
                   "WITH (FORMAT csv, DELIMITER '|', NULL '');")
            before = time.perf_counter()
            timed_sql(report, logpath, scenario, db, "copy", table,
                      psql(args.container, args.user, db, sql))
            item["copy_s"] += time.perf_counter() - before
            # The exact row count is recorded in the last phase row.
            item["rows_loaded"] += int(report["steps"][-1]["rows_loaded"])

        for index_name, table, sql in selected:
            before = time.perf_counter()
            timed_sql(report, logpath, scenario, db, "index", index_name,
                      psql(args.container, args.user, db, sql))
            seconds = time.perf_counter() - before
            item["indexes_s"] += seconds
            report["indexes"].append({"scenario": scenario, "database": db,
                                      "index_name": index_name,
                                      "duration_s": report["steps"][-1]["duration_s"]})

        if scenario == "clustered_8":
            for index_name, table, sql in clusters:
                before = time.perf_counter()
                timed_sql(report, logpath, scenario, db, "cluster", table,
                          psql(args.container, args.user, db, sql))
                item["cluster_s"] += time.perf_counter() - before

        before = time.perf_counter()
        timed_sql(report, logpath, scenario, db, "analyze", "ANALYZE",
                  psql(args.container, args.user, db, "ANALYZE;"))
        item["analyze_s"] += time.perf_counter() - before

        elapsed = time.perf_counter() - start
        item["load_end_at"] = now()
        item["measured_total_s"] = round(elapsed, 6)
        item["tload_rounded_up_0_1_s"] = roundup_tenth(elapsed)
        phases = ("schema_s", "copy_s", "indexes_s", "cluster_s", "analyze_s")
        item["sum_phase_times_s"] = round(sum(item[name] for name in phases), 6)

        # configuration again and checks that every table was analyzed.
        config_after = probe_config(args.container, args.user, db)
        after_rows = validate_config(config_after, database=db,
                                     baseline_start=report["server_preflight"]["postmaster_started_at"])
        report["config_checks"].extend([
            {"scenario": scenario, "database": db, "when": "after", **row}
            for row in after_rows
        ])
        item["settings_verified_before_after"] = True
        item["analyze_verification"] = check_analyze(args.container, args.user, db)
        item["analyzed_tables_count"] = sum(x["analyzed"] for x in item["analyze_verification"].values())
        log_line(logpath, f"{scenario}: VERIFIED settings after load and "
                 f"ANALYZE on {item['analyzed_tables_count']} tables")

        all_manual_names = {x[0] for x in index14} | {x[0] for x in index8}
        expected_manual = {x[0] for x in selected}
        actual = get_indexes(args.container, args.user, db)
        if (actual & all_manual_names) != expected_manual:
            raise RuntimeError(f"Unexpected manual indexes for {db}: "
                               f"expected={sorted(expected_manual)}, "
                               f"actual={sorted(actual & all_manual_names)}")
        expected_clustering = ({f"{table}:{name}" for name, table, _ in clusters}
                               if scenario == "clustered_8" else set())
        actual_clustering = get_clustered(args.container, args.user, db)
        if actual_clustering != expected_clustering:
            raise RuntimeError(f"Unexpected clustering state for {db}: "
                               f"expected={expected_clustering}, "
                               f"actual={actual_clustering}")
        size_raw = run(psql(args.container, args.user, db,
                            "SELECT pg_database_size(current_database());", raw=True))
        item["database_size_bytes"] = int(size_raw.strip())
        item["status"] = "SUCCESS"
        log_line(logpath, f"{scenario}: load completed: {elapsed:.3f}s "
                          f"(rounded up: {roundup_tenth(elapsed):.1f}s), "
                          f"{item['rows_loaded']} rows")
    except BaseException:
        item["status"] = "FAILED"
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sf", type=int, required=True, help="e.g. 2 for SF2")
    parser.add_argument("--run-id", default="run1", help="unique suffix for all 3 database names")
    parser.add_argument("--schema", type=Path,
                        default=Path("DSGen-software-code-4.0.0/tools/tpcds.sql"))
    parser.add_argument("--data-dir", type=Path,
                        help="default: ./benchmarks/sf<sf>/data")
    parser.add_argument("--indexes-sql", type=Path,
                        default=Path("indexes_nonclustered_14.sql"))
    parser.add_argument("--clustered-indexes-sql", type=Path,
                        default=Path("indexes_clustered_8.sql"))
    parser.add_argument("--cluster-sql", type=Path,
                        default=Path("cluster_four_tables.sql"))
    parser.add_argument("--output-dir", type=Path,
                        help="default: ./benchmarks/sf<sf>/results_load_independent/<run-id>")
    parser.add_argument("--container", default="tpcds-postgres")
    parser.add_argument("--user", default="tpcds", help="PostgreSQL user")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sf < 1:
        raise SystemExit("--sf must be >= 1")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.run_id):
        raise SystemExit("--run-id must contain lowercase letters, numbers, underscores and start with a letter")
    db_names = {
        "baseline": f"tpcds_sf{args.sf}_load_baseline_{args.run_id}",
        "indexed_14": f"tpcds_sf{args.sf}_load_indexed14_{args.run_id}",
        "clustered_8": f"tpcds_sf{args.sf}_load_clustered8_{args.run_id}",
    }
    if any(len(db.encode("utf-8")) > 63 for db in db_names.values()):
        raise SystemExit("Database names exceed PostgreSQL's 63-byte identifier limit; shorten --run-id")

    data_dir = args.data_dir or Path(f"benchmarks/sf{args.sf}/data")
    output_dir = args.output_dir or Path(f"benchmarks/sf{args.sf}/results_load_independent/{args.run_id}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output folder is not empty: {output_dir}. Choose another --run-id.")
    output_dir.mkdir(parents=True, exist_ok=True)
    logpath = output_dir / "run.log"
    report: dict = {
        "status": "PREFLIGHT", "scale_factor": args.sf, "run_id": args.run_id,
        "started_at": now(), "finished_at": None,
        "database_names": db_names, "scenarios": {},
        "steps": [], "indexes": [], "config_checks": [], "error": None,
        "requested_config": {**DB_SETTINGS, "shared_buffers": "record actual server value; do not modify",
                             "server_version": EXPECTED_POSTGRES_VERSION},
        "files": {"schema": str(args.schema), "data_dir": str(data_dir),
                  "indexes_sql": str(args.indexes_sql),
                  "clustered_indexes_sql": str(args.clustered_indexes_sql),
                  "cluster_sql": str(args.cluster_sql)},
    }
    try:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI not found")
        if not args.schema.is_file():
            raise RuntimeError(f"Cannot find schema: {args.schema}")
        schema = args.schema.read_bytes()
        if not schema.strip():
            raise RuntimeError("Schema is empty")
        index14 = get_sql(args.indexes_sql, "index")
        index8 = get_sql(args.clustered_indexes_sql, "index")
        clusters = get_sql(args.cluster_sql, "cluster")
        validate_sql(index14, index8, clusters)

        running = run(["docker", "inspect", "--format", "{{.State.Running}}", args.container])
        if running.strip() != "true":
            raise RuntimeError(f"Docker container is not running: {args.container}")

        server_preflight = probe_config(args.container, args.user, "postgres")
        validate_server_only(server_preflight)
        report["server_preflight"] = server_preflight
        recorded = next(r for r in server_preflight["settings"] if r["name"] == "shared_buffers")
        log_line(logpath, f"VERIFIED PostgreSQL version; observed shared_buffers="
                          f"{recorded['effective']} (recorded, not modified). "
                          "Per-database settings will be set on each fresh DB.")

        missing = [str(data_dir / f"{table}.dat") for table in TABLES
                   if not (data_dir / f"{table}.dat").is_file()
                   or (data_dir / f"{table}.dat").stat().st_size == 0]
        if missing:
            raise RuntimeError("Missing/non-empty pre-generated .dat files: " + ", ".join(missing))
        try:
            rel_dir = data_dir.resolve().relative_to((Path.cwd() / "benchmarks").resolve())
        except ValueError as exc:
            raise RuntimeError("The .dat directory must be inside ./benchmarks (Docker shared mount)") from exc
        container_dir = "/benchmarks/" + rel_dir.as_posix()
        for table in TABLES:
            run(["docker", "exec", "-u", "postgres", args.container,
                 "test", "-r", f"{container_dir}/{table}.dat"])

        for db in db_names.values():
            existing = run(psql(args.container, args.user, "postgres",
                                f"SELECT 1 FROM pg_database WHERE datname='{db}';", raw=True))
            if existing.strip():
                raise RuntimeError(f"Database already exists: {db}. "
                                   "Choose a new --run-id; existing DBs are never overwritten.")
        report["status"] = "RUNNING"
        log_line(logpath, "Preflight passed. Each scenario will load all 24 files into its OWN database.")
        for scenario in SCENARIOS:
            load_scenario(args, scenario, db_names[scenario], container_dir,
                          schema, index14, index8, clusters, report, logpath)
            persist(report, output_dir)

        report["status"] = "SUCCESS"
        report["finished_at"] = now()
        persist(report, output_dir)
        log_line(logpath, f"SUCCESS — results: {output_dir}")
        for scenario in SCENARIOS:
            result = report["scenarios"][scenario]
            log_line(logpath, f"{scenario:<12}: {result['measured_total_s']:.3f} sec ")
        return 0
    except (RuntimeError, OSError, ValueError, KeyboardInterrupt) as exc:
        report["status"] = "FAILED"
        report["finished_at"] = now()
        report["error"] = "Interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc)
        persist(report, output_dir)
        log_line(logpath, "FAILED: " + report["error"])
        log_line(logpath, "Any database already created is left untouched. "
                          "Do not rerun with the same run-id.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
