import re
import csv
import argparse
import statistics
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Extract timings, errors, and SQL details into a CSV.")
    parser.add_argument("-i", "--input", default="./tpcds-results", help="Directory containing .explain.txt files")
    parser.add_argument("-q", "--queries", default="./generated_queries", help="Directory containing original .sql files")
    parser.add_argument("-o", "--output", default="./tpcds-results/timings_detailed.csv", help="Output CSV file path")
    args = parser.parse_args()

    input_dir = Path(args.input)
    queries_dir = Path(args.queries)
    output_csv = Path(args.output)

    if not input_dir.exists():
        print(f"Error: Directory {input_dir} does not exist.")
        return

    results = []
    valid_times = []

    # Process all explain.txt files in the directory
    for file_path in input_dir.glob("*.explain.txt"):
        query_name = file_path.name.replace(".explain.txt", "")
        content = file_path.read_text(encoding="utf-8")
        
        # 1. READ ORIGINAL SQL QUERY
        sql_file = queries_dir / f"{query_name}.sql"
        query_detail = sql_file.read_text(encoding="utf-8").strip() if sql_file.exists() else "SQL file not found"

        # 2. PARSE EXECUTION TIME AND ERRORS
        time_match = re.search(r"Execution Time:\s+([0-9.]+)\s+ms", content)
        
        error_detail = ""
        execution_ms = None

        if time_match:
            execution_ms = float(time_match.group(1))
            valid_times.append(execution_ms)
        else:
            # If no execution time, look for the ERROR string
            error_match = re.search(r"ERROR:(.*)", content, re.IGNORECASE | re.DOTALL)
            if error_match:
                # Capture the error message
                error_detail = "ERROR:" + error_match.group(1).strip()
            else:
                error_detail = "TIMEOUT OR UNKNOWN ERROR"

        # Store row data temporarily
        results.append({
            "query": query_name,
            "execution_ms": execution_ms,
            "error_detail": error_detail,
            "query_detail": query_detail
        })

    if not results:
        print("No execution logs found. Did you run the benchmark script?")
        return

    # 3. CALCULATE OUTLIER THRESHOLD USING IQR METHOD
    upper_bound = float('inf')
    if len(valid_times) >= 4:
        # Calculate Q1 (25th percentile) and Q3 (75th percentile)
        q1, median, q3 = statistics.quantiles(valid_times, n=4)
        iqr = q3 - q1
        upper_bound = q3 + 1.5 * iqr
        print(f"\n--- Statistical Baseline ---")
        print(f"Q1 (Fast): {q1:.2f} ms | Q3 (Slow): {q3:.2f} ms")
        print(f"IQR: {iqr:.2f} ms")
        print(f"OUTLIER THRESHOLD (Q3 + 1.5*IQR): Queries taking > {upper_bound:.2f} ms will be flagged.\n")

    # 4. FLAG OUTLIERS AND SORT RESULTS
    for row in results:
        if row["execution_ms"] is not None:
            # Flag YES if time is greater than the calculated upper bound
            row["is_outlier"] = "YES" if row["execution_ms"] > upper_bound else "NO"
        else:
            row["is_outlier"] = "N/A" # For queries that failed/errored

    # Sort numerically (e.g. query_1, query_2... query_99)
    results.sort(key=lambda x: int(x["query"].split("_")[1]) if "_" in x["query"] else 0)

    # 5. WRITE EXPORT TO CSV
    with open(output_csv, 'w', newline='', encoding="utf-8") as f:
        fieldnames = ["query", "execution_ms", "is_outlier", "error_detail", "query_detail"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"Successfully extracted {len(results)} queries with full details to {output_csv}")

if __name__ == "__main__":
    main()