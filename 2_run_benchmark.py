import argparse
import subprocess
from pathlib import Path

def execute_query(query_num, input_dir, output_dir, container):
    query_file = input_dir / f"query_{query_num}.sql"
    if not query_file.exists():
        print(f"Skipping Query {query_num}: File not found.")
        return

    # Read SQL and remove commented lines
    raw_sql = query_file.read_text(encoding="utf-8")
    clean_sql = "\n".join([line for line in raw_sql.splitlines() if not line.strip().startswith("--")])
    
    # Inject EXPLAIN for Execution Plan and Timing
    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n{clean_sql}"
    output_file = output_dir / f"query_{query_num}.explain.txt"
    
    print(f"Executing Query {query_num}...")
    
    command = ["docker", "exec", "-i", container, "psql", "-U", "tpcds", "-d", "tpcds"]
    
    try:
        # Run the command
        result = subprocess.run(
            command, input=explain_sql, text=True, capture_output=True, encoding="utf-8"
        )
        
        # Combine standard output and standard error
        final_output = result.stdout
        if result.stderr:
            final_output += f"\n--- ERROR LOG ---\n{result.stderr}"
            
        output_file.write_text(final_output.strip(), encoding="utf-8")
        
        if "ERROR:" in result.stderr:
            print(f"  -> ERROR running Query {query_num}. Check {output_file.name} for details.")
        else:
            print(f"  -> Saved plan to {output_file.name}")
            
    except Exception as e:
        print(f"  -> CRITICAL SCRIPT ERROR on Query {query_num}:\n{e}")

def main():
    parser = argparse.ArgumentParser(description="Execute queries inside PostgreSQL Docker.")
    parser.add_argument("-q", "--query", required=True, help="Query number(s) to run (e.g., '1', '1-10', or 'all')")
    parser.add_argument("-i", "--input", default="./generated_queries", help="Directory with split queries")
    parser.add_argument("-o", "--output", default="./tpcds-results", help="Directory to save execution plans")
    parser.add_argument("-c", "--container", default="tpcds-postgres", help="PostgreSQL Docker container name")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    query_list = []
    if args.query.lower() == "all":
        query_list = list(range(1, 100))
    elif "-" in args.query:
        start, end = map(int, args.query.split("-"))
        query_list = list(range(start, end + 1))
    else:
        query_list = [int(args.query)]

    for q in query_list:
        execute_query(q, input_dir, output_dir, args.container)

if __name__ == "__main__":
    main()