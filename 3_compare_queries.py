#!/usr/bin/env python3
"""
Compare ORIGINAL vs OPTIMIZED TPC-DS queries on PostgreSQL.

For every scale factor (each SF lives in its own database, e.g. tpcds_sf10) and
every query that exists in BOTH the original and the optimized folder it:

  1. runs both versions N times (interleaved: orig, opt, orig, opt, ...) and
     records every execution time (psql \\timing),
  2. compares the result sets of the two versions (exact string equality of every
     value) and counts mismatching rows,
  3. saves the EXPLAIN (or EXPLAIN ANALYZE) plan of both versions.

Every execution is appended to runs.csv immediately and every finished query to summary.csv,
so a crash or Ctrl-C never loses finished work; --resume skips finished (SF, query) pairs.

Examples
--------
  python compare_benchmark.py --sf 1 2 10 -i benchmarks/sf{sf}/queries --optimized-dir benchmarks/sf{sf}/queries_opt
  python compare_benchmark.py --sf 1 -d tpcds_sf1 -i benchmarks/sf1/queries --optimized-dir benchmarks/sf1/queries_opt \\
      -o benchmarks/sf1/results_compare -n 3 --order suite --statement-timeout-ms 600000 \\
      --set work_mem=256MB --set hash_mem_multiplier=2 --set max_parallel_workers_per_gather=4 \\
      --set effective_cache_size=10GB --set random_page_cost=1.1 --set jit=off \\
      --no-save-results 2>&1 | tee sf1_compare.log
  python compare_benchmark.py --sf 10 --queries 4 11 -n 1 --plan analyze
  python compare_benchmark.py --run-id sf10_final --resume

Output (results/<run-id>/)
--------------------------
  summary.csv   one row per (sf, query): timings, speedup, match flag, mismatch counts, plan costs
  runs.csv      one row per individual execution (long format, ideal for pandas / pivot tables)
  plans/sf<SF>/q<NN>_original.txt, q<NN>_optimized.txt
  mismatches/sf<SF>/q<NN>_only_in_original.csv, q<NN>_only_in_optimized.csv   (only if results differ)
  config.json   settings used for the run
"""
import argparse
import csv
import io
import json
import re
import shlex
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- defaults
# Change these here or override them on the command line.
SCALE_FACTORS = [1, 2, 10]
DB_TEMPLATE = "tpcds_sf{sf}"                       # database name per scale factor
PSQL_CMD = "docker exec -i tpcds-postgres psql -U tpcds"
ORIGINAL_DIR = "queries/original"
OPTIMIZED_DIR = "queries/optimized"
RUNS = 3                                            # executions per query and version
SETTINGS = {"work_mem": "256MB"}                    # session settings (--set NAME=VALUE)
PLAN_MODE = "explain"                               # none | explain | analyze
TIMEOUT_MS = 0                                      # per statement, 0 = no timeout
ORDER = "query"                                     # query | suite
OUT_DIR = "results"
MAX_MISMATCH_ROWS_SAVED = 1000                      # cap rows written to mismatch files

NULL_MARK = "__NULL__"                              # distinguishes NULL from empty string
TIME_RE = re.compile(r"^Time: ([\d.]+) ms", re.M)
KEY_RE = re.compile(r"(\d+)([ab])?(?![A-Za-z0-9])", re.I)
VERSIONS = ("original", "optimized")

SUMMARY_FIELDS = [
    "run_id", "timestamp", "sf", "database", "query", "status", "runs", "settings",
    "orig_runs_ms", "orig_min_ms", "orig_median_ms", "orig_mean_ms", "orig_max_ms",
    "opt_runs_ms", "opt_min_ms", "opt_median_ms", "opt_mean_ms", "opt_max_ms",
    "speedup_median", "speedup_min",
    "orig_rows", "opt_rows", "results_match", "same_order",
    "mismatched_rows", "rows_only_in_original", "rows_only_in_optimized",
    "orig_plan_cost", "opt_plan_cost", "orig_plan_exec_ms", "opt_plan_exec_ms",
    "orig_planning_ms", "opt_planning_ms", "orig_plan_file", "opt_plan_file", "error",
]
RUN_FIELDS = ["run_id", "sf", "database", "query", "version", "run", "ms", "status"]


# ---------------------------------------------------------------- helpers
def query_key(path):
    """'query_04.sql' -> '04', 'query14a.sql' -> '14a'."""
    m = KEY_RE.search(path.stem)
    return f"{int(m.group(1)):02d}{(m.group(2) or '').lower()}" if m else None


def collect(directory):
    found = {}
    for p in sorted(Path(directory).glob("*.sql")):
        k = query_key(p)
        if k:
            found[k] = p
    return found


def wanted(key, selectors):
    if not selectors:
        return True
    for s in selectors:
        m = re.fullmatch(r"[qQ]?(\d+)([ab])?", s.strip())
        if m and int(m.group(1)) == int(key[:2]) and (not m.group(2) or m.group(2).lower() == key[2:]):
            return True
    return False


def split_statements(sql):
    """Split a query file on top-level ';' (ignores -- comments and 'quoted;strings')."""
    stmts, buf, i, n, in_str = [], [], 0, len(sql), False
    while i < n:
        c = sql[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
            buf.append(c)
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        elif c == ";":
            s = "".join(buf).strip()
            if s:
                stmts.append(s)
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def prelude(settings, timeout_ms, fmt):
    lines = ["\\set ON_ERROR_STOP on"]
    for name, value in settings.items():
        lines.append("SET {} TO '{}';".format(name, value.replace("'", "''")))
    if timeout_ms:
        lines.append(f"SET statement_timeout TO '{int(timeout_ms)}';")
    if fmt == "csv":
        lines += ["\\pset format csv", f"\\pset null '{NULL_MARK}'"]
    else:
        lines.append("\\pset format unaligned")
    lines.append("\\pset tuples_only on")
    return "\n".join(lines) + "\n"


def run_psql(psql_cmd, db, script):
    cmd = shlex.split(psql_cmd) + ["-X", "-q", "-d", db]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, input=script, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr, (time.perf_counter() - t0) * 1000


def execute(args, db, sql):
    """Run a whole query file once. Returns {'ms', 'rows'} or {'error'}."""
    script = prelude(args.settings, args.statement_timeout_ms, "csv") + "\\timing on\n" + sql + "\n"
    rc, out, err, wall_ms = run_psql(args.psql_cmd, db, script)
    if rc != 0:
        return {"error": err.strip() or f"psql exit code {rc}"}
    times = TIME_RE.findall(out)
    ms = sum(float(t) for t in times) if times else wall_ms   # sums multi-statement files
    body = "\n".join(l for l in out.splitlines() if not re.match(r"Time: [\d.]+ ms", l))
    rows = [tuple(r) for r in csv.reader(io.StringIO(body, newline=""))]
    return {"ms": ms, "rows": rows}


def status_of(error):
    return "timeout" if "statement timeout" in error else "error"


def compare_rows(orig, opt):
    co, cp = Counter(orig), Counter(opt)
    only_o, only_p = co - cp, cp - co
    n_o, n_p = sum(only_o.values()), sum(only_p.values())
    return {
        "match": n_o == 0 and n_p == 0,
        "same_order": orig == opt,
        "only_o": only_o, "only_p": only_p,
        "n_only_o": n_o, "n_only_p": n_p,
        "mismatched": max(n_o, n_p),
    }


def dump_rows(path, counter, limit):
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row, count in counter.items():
            for _ in range(count):
                if written >= limit:
                    return
                w.writerow(row)
                written += 1


def get_plan(args, db, sql, mode):
    prefix = "EXPLAIN (ANALYZE, BUFFERS) " if mode == "analyze" else "EXPLAIN "
    script = prelude(args.settings, args.statement_timeout_ms, "text")
    for i, stmt in enumerate(split_statements(sql), 1):
        script += f"\\echo -- statement {i}\n{prefix}{stmt};\n"
    rc, out, err, _ = run_psql(args.psql_cmd, db, script)
    if rc != 0:
        return {"error": err.strip() or f"psql exit code {rc}"}
    parts = re.split(r"^-- statement \d+\s*$", out, flags=re.M)[1:]
    costs = [float(m.group(1)) for p in parts
             if (m := re.search(r"cost=[\d.]+\.\.([\d.]+)", p))]
    ex = re.findall(r"Execution Time: ([\d.]+) ms", out)
    pl = re.findall(r"Planning Time: ([\d.]+) ms", out)
    return {
        "text": out,
        "cost": round(sum(costs), 2) if costs else "",
        "exec_ms": round(sum(map(float, ex)), 3) if ex else "",
        "planning_ms": round(sum(map(float, pl)), 3) if pl else "",
    }


def timing_stats(prefix, values):
    keys = ("min_ms", "median_ms", "mean_ms", "max_ms")
    if not values:
        return {f"{prefix}_runs_ms": "", **{f"{prefix}_{k}": "" for k in keys}}
    return {
        f"{prefix}_runs_ms": "|".join(f"{v:.3f}" for v in values),
        f"{prefix}_min_ms": round(min(values), 3),
        f"{prefix}_median_ms": round(statistics.median(values), 3),
        f"{prefix}_mean_ms": round(statistics.mean(values), 3),
        f"{prefix}_max_ms": round(max(values), 3),
    }


def append_csv(path, fields, rows):
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def fmt_s(ms):
    return "n/a" if ms in ("", None) else f"{ms / 1000:.2f}s"


# ---------------------------------------------------------------- one query
def new_state(paths):
    return {"sqls": {v: paths[v].read_text(encoding="utf-8") for v in VERSIONS},
            "times": {v: [] for v in VERSIONS}, "rows": {}, "errors": {}}


def run_once(args, sf, db, key, st, r):
    """One round: original then optimized, once each. Returns rows for runs.csv."""
    run_rows = []
    for v in VERSIONS:
        if v in st["errors"]:
            continue
        res = execute(args, db, st["sqls"][v])
        base = {"run_id": args.run_id, "sf": sf, "database": db, "query": key,
                "version": v, "run": r}
        if "error" in res:
            st["errors"][v] = res["error"]
            run_rows.append({**base, "ms": "", "status": status_of(res["error"])})
        else:
            st["times"][v].append(res["ms"])
            st["rows"].setdefault(v, res["rows"])   # keep the first run's result for comparison
            run_rows.append({**base, "ms": round(res["ms"], 3), "status": "ok"})
    return run_rows


def finish_query(args, run_dir, sf, db, key, st):
    """Plans + result comparison + summary row, after all runs of a query are done."""
    sqls, times, rows, errors = st["sqls"], st["times"], st["rows"], st["errors"]

    # plans
    plans = {}
    if args.plan != "none":
        for v in VERSIONS:
            if args.plan == "analyze" and v in errors:
                continue                          # don't re-run something that already failed
            plan = get_plan(args, db, sqls[v], args.plan)
            plan_path = run_dir / "plans" / f"sf{sf}" / f"q{key}_{v}.txt"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan.get("text") or f"-- plan failed:\n{plan.get('error')}\n",
                                 encoding="utf-8")
            plan["file"] = str(plan_path.relative_to(run_dir))
            plans[v] = plan

    # result comparison
    cmp_ = None
    if "original" in rows and "optimized" in rows:
        cmp_ = compare_rows(rows["original"], rows["optimized"])
        if not cmp_["match"] and not args.no_save_results:
            d = run_dir / "mismatches" / f"sf{sf}"
            dump_rows(d / f"q{key}_only_in_original.csv", cmp_["only_o"], args.max_mismatch_rows)
            dump_rows(d / f"q{key}_only_in_optimized.csv", cmp_["only_p"], args.max_mismatch_rows)

    # summary row
    t_o, t_p = times["original"], times["optimized"]
    med_o = statistics.median(t_o) if t_o else None
    med_p = statistics.median(t_p) if t_p else None
    status = "ok" if not errors else "; ".join(f"{v}:{status_of(e)}" for v, e in errors.items())
    po, pp = plans.get("original", {}), plans.get("optimized", {})
    summary = {
        "run_id": args.run_id, "timestamp": datetime.now().isoformat(timespec="seconds"),
        "sf": sf, "database": db, "query": key, "status": status, "runs": args.runs,
        "settings": ";".join(f"{k}={v}" for k, v in args.settings.items()),
        **timing_stats("orig", t_o), **timing_stats("opt", t_p),
        "speedup_median": round(med_o / med_p, 3) if med_o and med_p else "",
        "speedup_min": round(min(t_o) / min(t_p), 3) if t_o and t_p else "",
        "orig_rows": len(rows["original"]) if "original" in rows else "",
        "opt_rows": len(rows["optimized"]) if "optimized" in rows else "",
        "results_match": cmp_["match"] if cmp_ else "",
        "same_order": cmp_["same_order"] if cmp_ else "",
        "mismatched_rows": cmp_["mismatched"] if cmp_ else "",
        "rows_only_in_original": cmp_["n_only_o"] if cmp_ else "",
        "rows_only_in_optimized": cmp_["n_only_p"] if cmp_ else "",
        "orig_plan_cost": po.get("cost", ""), "opt_plan_cost": pp.get("cost", ""),
        "orig_plan_exec_ms": po.get("exec_ms", ""), "opt_plan_exec_ms": pp.get("exec_ms", ""),
        "orig_planning_ms": po.get("planning_ms", ""), "opt_planning_ms": pp.get("planning_ms", ""),
        "orig_plan_file": po.get("file", ""), "opt_plan_file": pp.get("file", ""),
        "error": " | ".join(f"{v}: {e[:300]}" for v, e in errors.items()).replace("\n", " "),
    }
    return summary


# ---------------------------------------------------------------- main
def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf", type=int, nargs="+", default=SCALE_FACTORS, help="scale factors (default: %(default)s)")
    ap.add_argument("-d", "--db-template", default=DB_TEMPLATE,
                    help="database name; {sf} is replaced by the scale factor, so a plain name like "
                         "tpcds_sf1 works for a single SF (default: %(default)s)")
    ap.add_argument("--psql-cmd", default=PSQL_CMD, help="command used to start psql (default: %(default)s)")
    ap.add_argument("-i", "--original-dir", default=ORIGINAL_DIR,
                    help="folder with the ORIGINAL .sql files; {sf} is replaced (default: %(default)s)")
    ap.add_argument("--optimized-dir", default=OPTIMIZED_DIR,
                    help="folder with the OPTIMIZED .sql files; {sf} is replaced (default: %(default)s)")
    ap.add_argument("--queries", nargs="*", help="only these queries, e.g. 4 11 14 74 (default: all present in both folders)")
    ap.add_argument("-n", "--runs", type=int, default=RUNS, help="executions per query and version (default: %(default)s)")
    ap.add_argument("--set", dest="set_", action="append", default=[], metavar="NAME=VALUE",
                    help="PostgreSQL session setting, repeatable (default: work_mem=256MB)")
    ap.add_argument("--plan", choices=["none", "explain", "analyze"], default=PLAN_MODE,
                    help="explain = estimated plan only (cheap), analyze = EXPLAIN (ANALYZE, BUFFERS), "
                         "which executes each query one extra time (default: %(default)s)")
    ap.add_argument("--statement-timeout-ms", type=int, default=TIMEOUT_MS,
                    help="per-statement timeout in milliseconds, 0 = none (default: %(default)s)")
    ap.add_argument("--order", choices=["query", "suite"], default=ORDER,
                    help="query = all runs of one query, then the next query; "
                         "suite = whole suite once, then the whole suite again, ... (default: %(default)s)")
    ap.add_argument("--no-save-results", action="store_true",
                    help="don't write the mismatching rows to mismatches/ (results are still compared)")
    ap.add_argument("-o", "--out", default=OUT_DIR, help="output folder; each run goes in <out>/<run-id>/")
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--resume", action="store_true", help="skip (sf, query) pairs already in summary.csv of this run-id")
    ap.add_argument("--max-mismatch-rows", type=int, default=MAX_MISMATCH_ROWS_SAVED)
    args = ap.parse_args()

    if len(args.sf) > 1 and "{sf}" not in args.db_template:
        ap.error("several scale factors need {sf} in --db-template, e.g. tpcds_sf{sf}")
    args.settings = dict(SETTINGS)
    for item in args.set_:
        name, sep, value = item.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][\w.]*", name.strip()):
            ap.error(f"--set expects NAME=VALUE, got {item!r}")
        args.settings[name.strip()] = value.strip()
    return args


def report(args, run_dir, sf, db, key, st):
    summary = finish_query(args, run_dir, sf, db, key, st)
    append_csv(run_dir / "summary.csv", SUMMARY_FIELDS, [summary])
    match = {True: "MATCH", False: f"MISMATCH ({summary['mismatched_rows']} rows)",
             "": "n/a"}[summary["results_match"]]
    print(f"[SF{sf}] Q{key}: orig {fmt_s(summary['orig_median_ms'])} | "
          f"opt {fmt_s(summary['opt_median_ms'])} | speedup {summary['speedup_median'] or 'n/a'}x | "
          f"{match} | {summary['status']}")


def log_runs(sf, key, r, run_rows):
    parts = " | ".join(f"{x['version']} {fmt_s(x['ms'])}{'' if x['status'] == 'ok' else ' ' + x['status']}"
                       for x in run_rows)
    print(f"  [SF{sf}] Q{key} run {r}: {parts}")


def main():
    sys.stdout.reconfigure(line_buffering=True)      # so `| tee log` shows progress live
    args = parse_args()
    run_dir = Path(args.out) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(
        {k: v for k, v in vars(args).items() if k != "set_"}, indent=2), encoding="utf-8")

    summary_path, runs_path = run_dir / "summary.csv", run_dir / "runs.csv"
    done = set()
    if args.resume and summary_path.exists():
        with summary_path.open(newline="", encoding="utf-8") as f:
            done = {(r["sf"], r["query"]) for r in csv.DictReader(f)}

    print(f"Run {args.run_id}: SF {args.sf}, {args.runs} run(s) each, order={args.order}, "
          f"settings {args.settings}, plan={args.plan}, statement_timeout_ms={args.statement_timeout_ms}")

    for sf in args.sf:
        db = args.db_template.replace("{sf}", str(sf))
        odir = args.original_dir.replace("{sf}", str(sf))
        pdir = args.optimized_dir.replace("{sf}", str(sf))
        orig, opt = collect(odir), collect(pdir)
        if not orig or not opt:
            print(f"[SF{sf}] no .sql files in {odir} and/or {pdir}, skipping")
            continue
        missing = sorted(orig.keys() ^ opt.keys())
        if missing:
            print(f"[SF{sf}] no counterpart in the other folder for: {', '.join(missing)} (skipped)")
        keys = [k for k in sorted(orig.keys() & opt.keys()) if wanted(k, args.queries)]
        rc, _, err, _ = run_psql(args.psql_cmd, db, "SELECT 1;\n")
        if rc != 0:
            print(f"[SF{sf}] cannot connect to database {db!r}, skipping: {err.strip()[:200]}")
            continue

        todo = [k for k in keys if (str(sf), k) not in done]
        states = {k: new_state({"original": orig[k], "optimized": opt[k]}) for k in todo}
        print(f"[SF{sf}] database {db}, {len(todo)} queries")

        if args.order == "suite":
            for r in range(1, args.runs + 1):
                print(f"[SF{sf}] pass {r}/{args.runs}")
                for k in todo:
                    rr = run_once(args, sf, db, k, states[k], r)
                    append_csv(runs_path, RUN_FIELDS, rr)
                    log_runs(sf, k, r, rr)
            for k in todo:
                report(args, run_dir, sf, db, k, states[k])
        else:
            for k in todo:
                for r in range(1, args.runs + 1):
                    rr = run_once(args, sf, db, k, states[k], r)
                    append_csv(runs_path, RUN_FIELDS, rr)
                    log_runs(sf, k, r, rr)
                report(args, run_dir, sf, db, k, states[k])

    print(f"\nDone. Results in {run_dir}/ (summary.csv, runs.csv, plans/, mismatches/)")


if __name__ == "__main__":
    main()
