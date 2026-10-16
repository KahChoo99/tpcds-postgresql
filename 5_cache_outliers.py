import csv
import subprocess
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Cache results of slow outlier queries to save time during validation.")
    parser.add_argument("-b", "--baseline", default="./tpcds-results/timings_detailed.csv", help="Baseline CSV file")
    parser.add_argument("-q", "--queries", default="./generated_queries", help="Dir with original SQL files")
    parser.add_argument("-c", "--cache", default="./cached_results", help="Directory to save the permanent outputs")
    parser.add_argument("-d", "--container", default="tpcds-postgres", help="PostgreSQL Docker container")
    args = parser.parse_args()

    baseline_csv = Path(args.baseline)
    queries_dir = Path(args.queries)
    cache_dir = Path(args.cache)

    if not baseline_csv.exists():
        print(f"Error: {baseline_csv} not found.")
        return

    # Create cache directory
    cache_dir.mkdir(parents=True, exist_ok=True)

    outliers = []
    with open(baseline_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('is_outlier') == 'YES':
                outliers.append(row['query'])

    print(f"Found {len(outliers)} outlier queries. Starting cache process...")

    for q in outliers:
        sql_file = queries_dir / f"{q}.sql"
        out_file = cache_dir / f"{q}.out"

        if out_file.exists():
            print(f"[{q}] Already cached. Skipping.")
            continue

        if not sql_file.exists():
            print(f"[{q}] Original SQL not found. Skipping.")
            continue

        print(f"[{q}] Running and caching result (this might take a long time)...")
        raw_sql = sql_file.read_text(encoding="utf-8")
        clean_sql = "\n".join([line for line in raw_sql.splitlines() if not line.strip().startswith("--")])

        # Run without EXPLAIN to get raw data
        command = ["docker", "exec", "-i", args.container, "psql", "-U", "tpcds", "-d", "tpcds", "-A", "-t"]
        
        try:
            result = subprocess.run(command, input=clean_sql, text=True, capture_output=True, encoding="utf-8")
            if result.returncode == 0 and "ERROR:" not in result.stderr:
                out_file.write_text(result.stdout.strip(), encoding="utf-8")
                print(f"  -> Success! Saved to {out_file.name}")
            else:
                print(f"  -> Failed: {result.stderr.strip().split(chr(10))[0]}")
        except Exception as e:
            print(f"  -> Error executing {q}: {e}")

    print(f"\nCaching complete! Results are stored permanently in {cache_dir}/")

if __name__ == "__main__":
    main()