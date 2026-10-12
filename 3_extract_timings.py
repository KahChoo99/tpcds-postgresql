import re
import csv
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Extract execution times from EXPLAIN logs into a CSV.")
    parser.add_argument("-i", "--input", default="./tpcds-results", help="Directory containing .explain.txt files")
    parser.add_argument("-o", "--output", default="./tpcds-results/timings.csv", help="Output CSV file path")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_csv = Path(args.output)

    if not input_dir.exists():
        print(f"Error: Directory {input_dir} does not exist.")
        return

    results = []
    # Process all explain.txt files in the directory
    for file_path in input_dir.glob("*.explain.txt"):
        query_name = file_path.name.replace(".explain.txt", "")
        content = file_path.read_text(encoding="utf-8")
        
        # Regex to find the Execution Time metric
        match = re.search(r"Execution Time:\s+([0-9.]+)\s+ms", content)
        
        if match:
            results.append({"query": query_name, "execution_ms": float(match.group(1))})
        else:
            results.append({"query": query_name, "execution_ms": "ERROR/TIMEOUT"})

    if not results:
        print("No execution times found. Did you run the benchmark script?")
        return

    # Sort results numerically by query number
    results.sort(key=lambda x: int(x["query"].split("_")[1]) if "_" in x["query"] else 0)

    # Write to CSV
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["query", "execution_ms"])
        writer.writeheader()
        writer.writerows(results)

    print(f"Successfully extracted {len(results)} timings to {output_csv}")

if __name__ == "__main__":
    main()