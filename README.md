# TPC-DS PostgreSQL Benchmarking & Query Optimization Workflow

This repository contains our cross-platform automation pipeline for running the **TPC-DS benchmark** on PostgreSQL inside Docker, measuring multi-run execution times across Scale Factors ($\text{SF} \in \{1, 2, 4, 7, 10\}$), and verifying that optimized SQL queries produce **100% identical outputs** to the baseline/reference queries.

---

## Pipeline Overview

1. **Pre-Flight Database Setup:** Configure PostgreSQL memory (`work_mem = 256MB`) and update optimizer statistics (`ANALYZE`).
2. **Step 1 — Generate Queries (`dsqgen`):** Compile the 99 TPC-DS query templates using fixed qualification parameters (`-QUALIFY Y -RNGSEED 123`).
3. **Step 2 — Split Queries (`1_split_queries.py`):** Split the monolithic `query_0.sql` stream into 99 individual `query_1.sql` .. `query_99.sql` files.
4. **Step 3 — Run Benchmark (`run_tpcds_benchmark.py`):** Execute the queries sequentially across multiple iterations (`-n 3`) and log execution times (`exec_time_details.csv`) and baseline outputs.
5. **Step 4 — Optimize & Compare Results (`3_compare_results.py`):** Run refactored/optimized queries and automatically verify that their output rows match the reference answer sets while measuring speedup ratios.

---

## 0. Pre-Flight Database Tuning (Run Once)

Before running the benchmark, ensure the PostgreSQL container (`tpcds-postgres`) has `work_mem` set to `256MB` (instead of the `4MB` default, which causes hash joins and sorts to spill to disk) and up-to-date table statistics:

```bash
# 1. Permanently set work_mem to 256MB on the PostgreSQL server
docker exec -it tpcds-postgres psql -U tpcds -d tpcds -c "ALTER SYSTEM SET work_mem = '256MB';"
docker exec -it tpcds-postgres psql -U tpcds -d tpcds -c "SELECT pg_reload_conf();"

# 2. Verify that work_mem is now 256MB
docker exec -it tpcds-postgres psql -U tpcds -d tpcds -c "SHOW work_mem;"

# 3. Collect optimizer statistics on all 24 tables
docker exec -it tpcds-postgres psql -U tpcds -d tpcds -c "ANALYZE VERBOSE;"
```

*(Note: Replace `-d tpcds` with your specific database name, such as `-d tpcds_sf1`, if you named your database per Scale Factor).*

---

## Step 1: Generate the 99 Queries (`dsqgen`)

Enter the Docker container (or Linux/macOS environment) where `tpcds-kit` is located:

```bash
docker exec -it tpcds-postgres bash
cd /tpcds/tools
```

### Troubleshooting Build & Architecture Issues (Windows / macOS)
If you encounter `qemu-aarch64` architecture errors (caused by binaries compiled on Apple Silicon macOS being run on Windows x86_64) or `Segmentation fault` during `./distcomp` (caused by Windows CRLF `\r\n` line endings), run these cleanup commands inside `/tpcds/tools` first:

```bash
# Convert Windows CRLF (\r\n) to Linux LF (\n)
sed -i 's/\r$//' /tpcds/tools/*.dst /tpcds/tools/*.c /tpcds/tools/*.h /tpcds/tools/makefile*
sed -i 's/\r$//' /tpcds/query_templates/*.tpl /tpcds/query_templates/*.lst

# Clean old binaries and recompile for the container's native CPU architecture
rm -f *.o distcomp dsdgen dsqgen mkheader tpcds.idx tpcds.idx.h
make OS=LINUX
```

### Run `dsqgen`
Create the target output folder and generate `query_0.sql`:

```bash
mkdir -p /benchmarks/sf1/queries

./dsqgen \
  -DIRECTORY ../query_templates \
  -INPUT ../query_templates/templates.lst \
  -SCALE 1 \
  -DIALECT postgresql \
  -QUALIFY Y \
  -VERBOSE Y \
  -RNGSEED 123 \
  -OUTPUT_DIR /benchmarks/sf1/queries
```

---

## Step 2: Split `query_0.sql` into 99 Files (`1_split_queries.py`)

Exit the container back to your host terminal (macOS Terminal or Windows PowerShell) in the project root directory and split `query_0.sql` into `query_1.sql` through `query_99.sql`:

```bash
python3 1_split_queries.py -i ./benchmarks/sf1/queries/query_0.sql -o ./benchmarks/sf1/queries
```

*(On Windows Anaconda/PowerShell, use `python` instead of `python3`).*

---

## Step 3: Run the Benchmark (`run_tpcds_benchmark.py`)

> **Important (Windows Users):** Do **not** open `exec_time_details.csv` in Microsoft Excel while the benchmark script is running. Excel places a file lock on the CSV, which will cause a `PermissionError: [WinError 5] Access is denied` when the script updates the file after each query. Use VS Code or Notepad if you want to inspect progress live.

### A. Full 99-Query Suite (3 Runs) — Saving Reference Outputs
To save the output rows of every query (into `benchmarks/sf1/results-3runs/results/Q01.txt` .. `Q99.txt`) so you can compare your optimized queries against them later, omit `--no-save-results`:

**macOS / Linux:**
```bash
caffeinate -dims python3 run_tpcds_benchmark.py \
  -i benchmarks/sf1/queries \
  -o benchmarks/sf1/results-3runs \
  -d tpcds_sf1 \
  -n 3 \
  --set work_mem=256MB
```

**Windows (PowerShell):**
```powershell
python run_tpcds_benchmark.py -i benchmarks/sf1/queries -o benchmarks/sf1/results-3runs -d tpcds -n 3 --set work_mem=256MB
```
*(Add `--no-save-results` if you only want `exec_time_details.csv` timings without saving `.txt` result sets).*

### B. Running a Specific Subset or Single Query (e.g., Queries 75 to 99, 1 Run)
Use `-q` (`--query`) to specify a single query (`-q 4`), a comma-separated list (`-q 1,4,6,11,74`), or a range (`-q 75-99`), and `-n 1` for a single iteration:

```powershell
python run_tpcds_benchmark.py -i benchmarks/sf1/queries -o benchmarks/sf1/results-q75-99 -d tpcds -q 75-99 -n 1 --set work_mem=256MB
```

---

## Step 4: Query Optimization & Output Verification (`3_compare_results.py`)

When optimizing slow outlier queries (such as `Q04`, `Q11`, `Q74`, `Q06`, `Q01`, `Q81`, `Q14`, etc.), we must verify that the optimized SQL produces the **exact same data output** as the original query (or official reference answer file).

### Method 1: Manual Single-Query Execution & Comparison
You can execute a single query directly via `psql` inside the container and write its output to a text file:

```bash
# 1. Copy your query into the container (or reference a mounted volume path) and run it:
docker exec -it tpcds-postgres psql -U tpcds -d tpcds -f /benchmarks/sf1/queries/query_1.sql -o /benchmarks/sf1/my_output_1.txt

# Or pipe a local query file from your host machine directly into psql:
docker exec -i tpcds-postgres psql -U tpcds -d tpcds < ./optimized_queries/query_1.sql > my_output_1.txt
```

Then run `3_compare_results.py` in **Single-File Mode** to compare `my_output_1.txt` against the reference output file:

```bash
python3 3_compare_results.py \
  --actual my_output_1.txt \
  --expected benchmarks/sf1/results-3runs/results/Q01.txt
```

---

### Method 2: Automated Directory Comparison (Comparing Two Benchmark Runs)
If you ran `run_tpcds_benchmark.py` on your original queries (`results-baseline`) and again on your optimized queries (`results-optimized`), you can compare all output files and execution times at once:

```bash
python3 3_compare_results.py \
  --actual-dir benchmarks/sf1/results-optimized/results \
  --expected-dir benchmarks/sf1/results-3runs/results \
  --baseline-csv benchmarks/sf1/results-3runs/exec_time_details.csv \
  --optimized-csv benchmarks/sf1/results-optimized/exec_time_details.csv \
  --report benchmarks/sf1/comparison_report.csv
```

---

### Method 3: Live Execution of Optimized `.sql` Files + Automatic Comparison
If you placed your rewritten `.sql` files in a folder (e.g., `./optimized_queries/query_4.sql`, `query_11.sql`, `query_74.sql`), `3_compare_results.py` can automatically execute them against Docker, save their outputs, compare the rows against your baseline `results/` directory, and compute the speedup against `exec_time_details.csv`:

```bash
python3 3_compare_results.py \
  --sql-dir ./optimized_queries \
  --expected-dir benchmarks/sf1/results-3runs/results \
  --baseline-csv benchmarks/sf1/results-3runs/exec_time_details.csv \
  --database tpcds \
  --set work_mem=256MB \
  --report benchmarks/sf1/comparison_report.csv
```

### Understanding the Comparison Modes in `3_compare_results.py`
By default, `3_compare_results.py` normalizes minor formatting differences between `psql -f ... -o ...` (aligned table format with headers and `(N rows)` footers) and `psql -A -t` (unaligned tuples-only format used by `run_tpcds_benchmark.py`), as well as trailing whitespace and equivalent numeric representations (e.g., `0.00` vs `.00`).
* If you want a **strict byte-for-byte comparison**, pass the `--strict` flag.
* If any query output mismatches, the script prints the first differing lines and saves a unified diff file in `./comparison_diffs/` for debugging.