import argparse
import subprocess
import re
import csv
from pathlib import Path

def get_query_output(sql_content, container):
    clean_sql = "\n".join([line for line in sql_content.splitlines() if not line.strip().startswith("--")])
    command = ["docker", "exec", "-i", container, "psql", "-U", "tpcds", "-d", "tpcds", "-A", "-t"]
    try:
        result = subprocess.run(command, input=clean_sql, text=True, capture_output=True, encoding="utf-8")
        if result.returncode != 0 or "ERROR:" in result.stderr:
            return None
        return result.stdout.strip()
    except Exception:
        return None

def execute_for_time(sql_content, container):
    clean_sql = "\n".join([line for line in sql_content.splitlines() if not line.strip().startswith("--")])
    explain_sql = f"EXPLAIN (ANALYZE, FORMAT TEXT)\n{clean_sql}"
    command = ["docker", "exec", "-i", container, "psql", "-U", "tpcds", "-d", "tpcds"]
    try:
        result = subprocess.run(command, input=explain_sql, text=True, capture_output=True, encoding="utf-8")
        if result.returncode != 0 or "ERROR:" in result.stderr:
            return {"status": "ERROR", "time": None, "error_msg": result.stderr.strip().split('\n')[0]}
            
        match = re.search(r"Execution Time:\s+([0-9.]+)\s+ms", result.stdout)
        if match:
            return {"status": "SUCCESS", "time": float(match.group(1)), "error_msg": ""}
        return {"status": "ERROR", "time": None, "error_msg": "Could not parse time."}
    except Exception as e:
        return {"status": "ERROR", "time": None, "error_msg": str(e)}

def load_baseline(csv_path):
    baseline = {}
    if not csv_path.exists():
        return baseline
    with open(csv_path, 'r', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            baseline[row['query']] = {
                "time": float(row['execution_ms']) if row['execution_ms'] else None,
                "error": row['error_detail']
            }
    return baseline

def main():
    parser = argparse.ArgumentParser(description="Validate optimized queries using Cached Results.")
    parser.add_argument("-o", "--optimized", default="./optimized_queries", help="Dir with optimized SQL files")
    parser.add_argument("-i", "--original", default="./generated_queries", help="Dir with original SQL files")
    parser.add_argument("-b", "--baseline", default="./tpcds-results/timings_detailed.csv", help="Baseline CSV")
    parser.add_argument("-ca", "--cache", default="./cached_results", help="Directory with cached query outputs")
    parser.add_argument("-c", "--container", default="tpcds-postgres", help="PostgreSQL Docker container")
    parser.add_argument("-r", "--report", default="./optimized_results/validation_report.csv", help="Output report")
    args = parser.parse_args()

    opt_dir = Path(args.optimized)
    orig_dir = Path(args.original)
    baseline_csv = Path(args.baseline)
    cache_dir = Path(args.cache)
    report_csv = Path(args.report)

    if not opt_dir.exists():
        print(f"Error: Optimized directory '{opt_dir}' not found.")
        return

    report_csv.parent.mkdir(parents=True, exist_ok=True)
    baseline_data = load_baseline(baseline_csv)
    opt_files = list(opt_dir.glob("*.sql"))

    print(f"{'='*90}")
    print(f"{'QUERY':<12} | {'STATUS':<10} | {'DATA MATCH':<12} | {'OLD TIME':<12} | {'NEW TIME':<12} | {'IMPROVEMENT'}")
    print(f"{'-'*90}")

    report_data = []

    for opt_file in sorted(opt_files, key=lambda x: int(x.stem.split('_')[1]) if '_' in x.stem else 0):
        query_name = opt_file.stem
        opt_sql = opt_file.read_text(encoding="utf-8")
        orig_sql_file = orig_dir / f"{query_name}.sql"
        orig_sql = orig_sql_file.read_text(encoding="utf-8") if orig_sql_file.exists() else ""
        
        perf_result = execute_for_time(opt_sql, args.container)
        old_time = baseline_data.get(query_name, {}).get("time")
        old_error = baseline_data.get(query_name, {}).get("error")
        
        status = perf_result["status"]
        new_time_str = f"{perf_result['time']:.2f} ms" if perf_result["time"] else "N/A"
        old_time_str = f"{old_time:.2f} ms" if old_time else "ERROR/NA"
        
        data_match = "N/A"
        improvement = "N/A"

        if status == "SUCCESS":
            if old_time and perf_result["time"]:
                speedup = old_time / perf_result["time"]
                improvement = f"{speedup:.1f}x FASTER" if speedup > 1 else f"{1/speedup:.1f}x SLOWER"
            elif not old_time:
                improvement = "FIXED (Was Error)"

            if "ERROR" not in old_error and orig_sql:
                # Use CACHE if available, otherwise run the original query
                cached_file = cache_dir / f"{query_name}.out"
                if cached_file.exists():
                    orig_output = cached_file.read_text(encoding="utf-8").strip()
                else:
                    print(f"[{query_name}] No cache found. Running original query... (may be slow)")
                    orig_output = get_query_output(orig_sql, args.container)
                
                opt_output = get_query_output(opt_sql, args.container)
                
                if orig_output == opt_output:
                    data_match = "YES (Exact)"
                else:
                    data_match = "NO (Mismatch)"
            else:
                data_match = "SKIP (Old Err)"
        else:
            improvement = "STILL FAILING"

        print(f"{query_name:<12} | {status:<10} | {data_match:<12} | {old_time_str:<12} | {new_time_str:<12} | {improvement}")

        report_data.append({
            "query": query_name,
            "status": status,
            "data_match": data_match,
            "old_time_ms": old_time if old_time else "ERROR/NA",
            "new_time_ms": perf_result["time"] if perf_result["time"] else "ERROR/NA",
            "improvement": improvement
        })

    with open(report_csv, 'w', newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query", "status", "data_match", "old_time_ms", "new_time_ms", "improvement"])
        writer.writeheader()
        writer.writerows(report_data)
    print(f"{'='*90}")

if __name__ == "__main__":
    main()