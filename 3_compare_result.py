"""
3_compare_results.py
====================
Compare TPC-DS query outputs against reference/baseline answer files to verify
that optimized queries return 100% identical data results.

Supports 3 usage modes:
  1. Single-file comparison:
     python 3_compare_results.py --actual my_output_1.txt --expected ref_Q01.txt

  2. Directory-to-directory comparison (e.g. comparing two benchmark runs):
     python 3_compare_results.py \
       --actual-dir benchmarks/sf1/results-opt/results \
       --expected-dir benchmarks/sf1/results-3runs/results \
       --baseline-csv benchmarks/sf1/results-3runs/exec_time_details.csv \
       --optimized-csv benchmarks/sf1/results-opt/exec_time_details.csv

  3. Live SQL execution + comparison (runs optimized .sql files in Docker,
     saves outputs, and compares against the reference directory & baseline CSV):
     python 3_compare_results.py \
       --sql-dir ./optimized_queries \
       --expected-dir benchmarks/sf1/results-3runs/results \
       --baseline-csv benchmarks/sf1/results-3runs/exec_time_details.csv \
       --database tpcds
"""

import argparse
import csv
import difflib
import re
import subprocess
import sys
from pathlib import Path


def extract_query_number(path_or_name):
    """Extract integer query ID from filenames like query_1.sql, Q01.txt, my_output_1.txt."""
    name = Path(path_or_name).stem
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def map_files_by_query_num(directory, extensions=(".txt", ".out", ".ans", ".sql")):
    """Map query number (1..99) -> Path inside a directory."""
    mapping = {}
    if not directory or not directory.is_dir():
        return mapping
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in extensions:
            qnum = extract_query_number(p.name)
            if qnum is not None and 1 <= qnum <= 99:
                mapping[qnum] = p
    return mapping


def normalize_cell(cell):
    """Normalize a single field value (whitespace, NULL tokens, numeric trailing zeros)."""
    val = cell.strip()
    if val.upper() in ("", "NULL", "NONE", "\\N"):
        return ""
    # Normalize numbers like .50 -> 0.5, -0.00 -> 0, 12.300 -> 12.3
    if re.match(r"^-?\d*\.\d+$", val):
        try:
            num = float(val)
            if abs(num) < 1e-12:
                return "0"
            # Format to 4 decimal places max and strip trailing zeros
            formatted = f"{num:.4f}".rstrip("0").rstrip(".")
            return formatted if formatted != "-0" else "0"
        except ValueError:
            pass
    return val


def normalize_output_lines(raw_text, strict=False):
    """
    Convert query output text into a canonical list of lines for comparison.
    If strict=False, strips psql headers/separators/row-count footers so that
    `psql -f query.sql -o out.txt` (aligned) matches `psql -A -t` (unaligned).
    """
    if strict:
        return [line.rstrip("\r\n") for line in raw_text.splitlines() if line.strip()]

    lines = raw_text.splitlines()
    cleaned = []
    # Regex patterns for psql metadata and formatting lines
    footer_re = re.compile(r"^\(\d+\s+rows?\)$", re.I)
    separator_re = re.compile(r"^[-+]+$")
    psql_noise_re = re.compile(r"^(Timing is (on|off)\.|Time:\s*[\d.]+\s*ms|SET)$", re.I)

    # Detect if this is an aligned psql table with a dashed header separator (e.g. ----+----)
    sep_indices = [idx for idx, l in enumerate(lines[:5]) if separator_re.match(l.strip())]
    start_idx = (sep_indices[0] + 1) if sep_indices else 0

    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        if footer_re.match(stripped) or separator_re.match(stripped) or psql_noise_re.match(stripped):
            continue
        # Split on pipe '|' delimiter and normalize each cell
        if "|" in stripped:
            cells = [normalize_cell(c) for c in stripped.split("|")]
            cleaned.append("|".join(cells))
        else:
            cleaned.append(normalize_cell(stripped))

    return cleaned


def compare_texts(actual_text, expected_text, strict=False):
    """
    Compare actual vs expected output text.
    Returns (is_match, actual_row_count, expected_row_count, diff_preview_str).
    """
    act_lines = normalize_output_lines(actual_text, strict=strict)
    exp_lines = normalize_output_lines(expected_text, strict=strict)

    if act_lines == exp_lines:
        return True, len(act_lines), len(exp_lines), ""

    # Check if rows match when sorted (order-insensitive match)
    if len(act_lines) == len(exp_lines) and sorted(act_lines) == sorted(exp_lines):
        diff = list(difflib.unified_diff(
            exp_lines, act_lines, fromfile="expected", tofile="actual", lineterm="", n=2
        ))
        return False, len(act_lines), len(exp_lines), "ROW_ORDER_DIFF: " + "\n".join(diff[:20])

    diff = list(difflib.unified_diff(
        exp_lines, act_lines, fromfile="expected", tofile="actual", lineterm="", n=2
    ))
    return False, len(act_lines), len(exp_lines), "\n".join(diff[:30])


def load_timings_csv(csv_path):
    """Load avg_exec_time (in seconds) per query number from exec_time_details.csv."""
    timings = {}
    if not csv_path or not csv_path.exists():
        return timings
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qnum = extract_query_number(row.get("query", ""))
            if qnum is None:
                continue
            # Support both exec_time_details.csv (avg_exec_time in s) and timings_detailed.csv (execution_ms)
            val_s = row.get("avg_exec_time") or row.get("median_exec_time") or row.get("exec_time_run_1")
            val_ms = row.get("execution_ms")
            try:
                if val_s not in (None, ""):
                    timings[qnum] = float(val_s)
                elif val_ms not in (None, ""):
                    timings[qnum] = float(val_ms) / 1000.0
            except ValueError:
                pass
    return timings


def split_statements(raw_sql):
    """Strip -- comments and split into SQL statements."""
    cleaned = "\n".join(
        line for line in raw_sql.splitlines()
        if not line.strip().startswith("--")
    )
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def run_sql_in_docker(sql_file, args):
    """Execute a .sql file inside the PostgreSQL Docker container and return (seconds, output_text, error)."""
    raw_sql = sql_file.read_text(encoding="utf-8")
    statements = split_statements(raw_sql)
    if not statements:
        return None, "", "Empty SQL file"

    setup = []
    for item in args.set:
        key, value = item.split("=", 1)
        setup.append(f"SET {key.strip()} = '{value.strip()}';")
    setup_sql = "\n".join(setup) + ("\n" if setup else "")
    sql_in = setup_sql + "\\timing on\n" + ";\n".join(statements) + ";\n"

    cmd = [
        "docker", "exec", "-i", args.container,
        "psql", "-X", "-v", "ON_ERROR_STOP=1",
        "-U", args.user, "-d", args.database,
        "-A", "-t",
    ]
    res = subprocess.run(cmd, input=sql_in, text=True, capture_output=True, encoding="utf-8")
    times_ms = [float(m) for m in re.findall(r"^Time:\s*([\d.]+)\s*ms", res.stdout, re.M)]

    if res.returncode != 0 or len(times_ms) != len(statements):
        err = res.stderr.strip() or "psql execution failed"
        return None, "", " ".join(err.split())[:300]

    skip = re.compile(r"^(Timing is (on|off)\.|Time: .*|SET)$")
    clean_out = "\n".join(l for l in res.stdout.splitlines() if not skip.match(l)) + "\n"
    return sum(times_ms) / 1000.0, clean_out, ""


def main():
    parser = argparse.ArgumentParser(
        description="Compare TPC-DS query outputs against reference answer files and compute speedups."
    )
    # Mode 1: Single file pair
    parser.add_argument("-a", "--actual", help="Path to a single actual output file (e.g. my_output_1.txt)")
    parser.add_argument("-e", "--expected", help="Path to a single expected reference file (e.g. Q01.txt)")

    # Mode 2 & 3: Directory comparison or Live SQL execution
    parser.add_argument("-ad", "--actual-dir", help="Directory containing actual/optimized output .txt files")
    parser.add_argument("-ed", "--expected-dir", help="Directory containing reference/baseline output .txt/.ans files")
    parser.add_argument("-sd", "--sql-dir", help="Directory with optimized .sql files to run live in Docker")
    parser.add_argument("-q", "--query", default="all", help="Query filter: all (default) | 4 | 1,4,6 | 75-99")

    # Timing CSVs (optional)
    parser.add_argument("-bc", "--baseline-csv", help="Baseline exec_time_details.csv for old runtimes")
    parser.add_argument("-oc", "--optimized-csv", help="Optimized exec_time_details.csv for new runtimes")

    # Docker / psql options for --sql-dir live mode
    parser.add_argument("-c", "--container", default="tpcds-postgres", help="Docker container name (default: tpcds-postgres)")
    parser.add_argument("-u", "--user", default="tpcds", help="PostgreSQL user (default: tpcds)")
    parser.add_argument("-d", "--database", default="tpcds", help="Database name (default: tpcds)")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="Session setting, e.g. --set work_mem=256MB")

    # Output & comparison flags
    parser.add_argument("--strict", action="store_true", help="Strict line-by-line comparison without formatting normalization")
    parser.add_argument("-r", "--report", default="comparison_report.csv", help="Path to save the CSV comparison report")
    parser.add_argument("--diff-dir", default="comparison_diffs", help="Directory to save .diff files when mismatches occur")

    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # MODE 1: Single File Comparison
    # -------------------------------------------------------------------------
    if args.actual and args.expected:
        act_path = Path(args.actual)
        exp_path = Path(args.expected)
        if not act_path.exists():
            sys.exit(f"Error: Actual file not found: {act_path}")
        if not exp_path.exists():
            sys.exit(f"Error: Expected file not found: {exp_path}")

        act_text = act_path.read_text(encoding="utf-8", errors="replace")
        exp_text = exp_path.read_text(encoding="utf-8", errors="replace")
        is_match, act_rows, exp_rows, diff_text = compare_texts(act_text, exp_text, strict=args.strict)

        print("=" * 75)
        print(f"Actual File  : {act_path}")
        print(f"Expected File: {exp_path}")
        print(f"Row Counts   : Actual={act_rows} rows | Expected={exp_rows} rows")
        print(f"Result       : {'YES (EXACT MATCH)' if is_match else 'NO (MISMATCH)'}")
        print("=" * 75)
        if not is_match and diff_text:
            print("\nFirst differences (Expected vs Actual):")
            print(diff_text)
            sys.exit(1)
        return

    # -------------------------------------------------------------------------
    # MODE 2 & 3: Batch Directory or Live SQL Execution Comparison
    # -------------------------------------------------------------------------
    if not args.expected_dir:
        parser.error("Provide either (--actual and --expected) OR --expected-dir with (--actual-dir or --sql-dir).")
    if not args.actual_dir and not args.sql_dir:
        parser.error("Provide either --actual-dir (pre-saved outputs) or --sql-dir (live SQL execution).")

    exp_dir = Path(args.expected_dir)
    exp_files = map_files_by_query_num(exp_dir, extensions=(".txt", ".out", ".ans"))
    if not exp_files:
        sys.exit(f"Error: No reference files (.txt, .out, .ans) found in {exp_dir}")

    # Parse query filter
    selected_queries = None
    if args.query and args.query.lower() != "all":
        if "," in args.query:
            selected_queries = [int(x.strip()) for x in args.query.split(",")]
        elif "-" in args.query:
            a, b = map(int, args.query.split("-"))
            selected_queries = list(range(a, b + 1))
        else:
            selected_queries = [int(args.query)]

    old_timings = load_timings_csv(Path(args.baseline_csv)) if args.baseline_csv else {}
    new_timings = load_timings_csv(Path(args.optimized_csv)) if args.optimized_csv else {}

    if args.sql_dir:
        sql_dir = Path(args.sql_dir)
        target_files = map_files_by_query_num(sql_dir, extensions=(".sql",))
        if not target_files:
            sys.exit(f"Error: No .sql files found in {sql_dir}")
        live_out_dir = sql_dir / "executed_outputs"
        live_out_dir.mkdir(parents=True, exist_ok=True)
    else:
        act_dir = Path(args.actual_dir)
        target_files = map_files_by_query_num(act_dir, extensions=(".txt", ".out", ".ans"))
        if not target_files:
            sys.exit(f"Error: No output files found in {act_dir}")

    if selected_queries is not None:
        target_files = {q: target_files[q] for q in selected_queries if q in target_files}

    diff_dir = Path(args.diff_dir)
    report_rows = []

    header = (
        f"{'QUERY':<8} | {'STATUS':<10} | {'DATA MATCH':<18} | "
        f"{'EXP ROWS':>8} | {'ACT ROWS':>8} | {'OLD TIME':>10} | {'NEW TIME':>10} | {'SPEEDUP'}"
    )
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    exact_matches = 0
    mismatches = 0
    errors_count = 0

    for qnum in sorted(target_files):
        q_label = f"Q{qnum:02d}"
        src_file = target_files[qnum]
        old_t = old_timings.get(qnum)
        new_t = new_timings.get(qnum)
        err_msg = ""

        # Get actual output text (either by running SQL live or reading saved file)
        if args.sql_dir:
            exec_secs, act_text, err_msg = run_sql_in_docker(src_file, args)
            if exec_secs is not None:
                new_t = exec_secs
                (live_out_dir / f"{q_label}.txt").write_text(act_text, encoding="utf-8")
        else:
            act_text = src_file.read_text(encoding="utf-8", errors="replace")

        if err_msg:
            status = "ERROR"
            match_label = "N/A (Exec Error)"
            exp_rows = act_rows = 0
            errors_count += 1
        elif qnum not in exp_files:
            status = "SUCCESS"
            match_label = "SKIP (No Ref File)"
            act_rows = len(normalize_output_lines(act_text, strict=args.strict))
            exp_rows = 0
        else:
            status = "SUCCESS"
            exp_text = exp_files[qnum].read_text(encoding="utf-8", errors="replace")
            is_match, act_rows, exp_rows, diff_preview = compare_texts(
                act_text, exp_text, strict=args.strict
            )
            if is_match:
                match_label = "YES (Exact)"
                exact_matches += 1
            else:
                match_label = "ORDER_DIFF" if diff_preview.startswith("ROW_ORDER_DIFF:") else "NO (Mismatch)"
                mismatches += 1
                diff_dir.mkdir(parents=True, exist_ok=True)
                (diff_dir / f"{q_label}.diff.txt").write_text(diff_preview, encoding="utf-8")

        old_t_str = f"{old_t:.3f}s" if old_t is not None else "N/A"
        new_t_str = f"{new_t:.3f}s" if new_t is not None else "N/A"

        if old_t is not None and new_t is not None and new_t > 0:
            ratio = old_t / new_t
            speedup_str = f"{ratio:.2f}x FASTER" if ratio >= 1.0 else f"{1.0 / ratio:.2f}x SLOWER"
        elif status == "SUCCESS" and old_t is None and new_t is not None:
            speedup_str = "MEASURED"
        else:
            speedup_str = "N/A"

        print(
            f"{q_label:<8} | {status:<10} | {match_label:<18} | "
            f"{exp_rows:>8} | {act_rows:>8} | {old_t_str:>10} | {new_t_str:>10} | {speedup_str}"
        )

        report_rows.append({
            "query": q_label,
            "status": status,
            "data_match": match_label,
            "expected_rows": exp_rows,
            "actual_rows": act_rows,
            "old_time_s": round(old_t, 3) if old_t is not None else "",
            "new_time_s": round(new_t, 3) if new_t is not None else "",
            "speedup": speedup_str,
            "error": err_msg,
        })

    print("=" * len(header))
    print(
        f"Summary: {len(target_files)} queries checked | "
        f"Exact Matches: {exact_matches} | Mismatches: {mismatches} | Errors: {errors_count}"
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "query", "status", "data_match", "expected_rows", "actual_rows",
            "old_time_s", "new_time_s", "speedup", "error"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)
    print(f"Saved detailed comparison report to: {report_path}")
    if mismatches > 0:
        print(f"Saved mismatch diff logs to: {diff_dir}/")


if __name__ == "__main__":
    main()