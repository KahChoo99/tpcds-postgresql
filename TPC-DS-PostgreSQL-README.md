# TPC-DS PostgreSQL Benchmark 

## 1. Project Overview

This project evaluates PostgreSQL performance using the TPC-DS 4.0.0 benchmark, PostgreSQL 16, and Docker Compose.

The workflow covers:

1. Generating TPC-DS datasets at different scale factors.
2. Creating and loading separate PostgreSQL databases for each scale factor.
3. Generating SQL queries using the PostgreSQL dialect.
4. Splitting the generated SQL workload into individual queries.
5. Executing queries and collecting performance measurements.
<!-- 6. Comparing query results against reference outputs.
7. Extracting execution times and generating performance plots. -->

The target scale factors are SF1, SF2, SF5, and SF10. Each scale factor has its own data, queries, and results directories to keep experiments separate and reproducible.

## 2. Environment and Project Structure


## Architecture: two containers

One Compose file starts two containers.

| Container | Job | How you use it | 
| --- | --- | --- |
| `tpcds-postgres` (image `postgres:16`) | Database: create schema, load data, run queries | `docker exec tpcds-postgres psql ...` from the Mac |
| `tpcds-tools` (built from `Dockerfile.tpcds`) | Generator: `dsdgen` creates data, `dsqgen` creates queries | `docker exec -it tpcds-tools bash`, then work in `/tpcds/tools` | 

Data flow:

1. `dsdgen` (tools) writes `.dat` files to `/benchmarks/sf_i/data`.
2. Postgres reads the same files with server-side `COPY` and fills `tpcds_sf_i`.
3. `dsqgen` (tools) writes SQL to `/benchmarks/sf_i/queries`.
4. Python scripts on the Mac split the SQL, run it through `docker exec`, and save timings in `benchmarks/sf_i/results`.

### 2.1. Benchmark directory structure

The benchmark artifacts are organized by scale factor:

```text
tpcds-postgresql/
├── docker-compose.yml
├── DSGen-software-code-4.0.0/
│   ├── tools/
│   └── query_templates/
├── benchmarks/
│   ├── sf1/
│   │   ├── data/
│   │   ├── queries/
│   │   └── results/
│   ├── sf2/
│   │   ├── data/
│   │   ├── queries/
│   │   └── results/
│   ├── sf4/
│   │   ├── data/
│   │   ├── queries/
│   │   └── results/
│   └── sf7/
│       ├── data/
│       ├── queries/
│       └── results/
└── [project scripts and analysis files]
```

The directories have the following purposes:

- `data/`: Generated TPC-DS `.dat` files.
- `queries/`: Generated SQL workload, including the combined query file and individual query files.
- `results/`: Query execution outputs, plans, logs, and other benchmark artifacts.

The actual repository may contain additional scripts and files.

### 2.2. Docker volume mounts

The local `benchmarks/` directory is mounted inside both containers at `/benchmarks`.

Consequently, files created under `/benchmarks` inside the tools container are available locally under `benchmarks/` on the Mac. The PostgreSQL container can also access these files through its mount.

The PostgreSQL mount is read-only in the current configuration. This is sufficient for server-side `COPY FROM`, provided that the files are readable by the PostgreSQL operating-system user.

---

## 3. Generating TPC-DS Data

Run this in the VS Code terminal to Start the tools container

```bash
docker exec -it tpcds-tools bash
```
Inside the tools container, run:
```bash
for sf in 1 2 5 10; do
  mkdir -p /benchmarks/sf${sf}/{data,queries,results}
done
```
This creates the following directory structure:


```text
benchmarks/
├── sf1/
│   ├── data/
│   ├── queries/
│   └── results/
├── sf2/
│   ├── data/
│   ├── queries/
│   └── results/
├── sf5/
│   ├── data/
│   ├── queries/
│   └── results/
└── sf10/
    ├── data/
    ├── queries/
    └── results/
```

Navigate to the TPC-DS tools directory
```bash
cd /tpcds/tools
```
Run the following command for different scale factors separately to generate the datasets.

```bash
./dsdgen \
  -SCALE 2 \
  -DIR /benchmarks/sf2/data \
  -TERMINATE N \
  -FORCE \
  -VERBOSE Y
```

Explanation of the main options:

- `-SCALE 2`: Generates data at scale factor 2.
- `-DIR`: Specifies the destination directory.
- `-TERMINATE N`: Prevents the generator from adding its extra record-terminating delimiter '|'.
- `-FORCE`: Allows existing generated files to be overwritten.
- `-VERBOSE Y`: Enables detailed generation output.

The qualification-only warning sometimes displayed at small scale factors is expected for this university exercise.

For other SF : Repeat the data-generation procedure with the appropriate scale factor and directory.

For example, SF5 uses `-SCALE 5` and `/benchmarks/sf5/data`.

---

## 4. Creating and Loading PostgreSQL Databases

Each scale factor should use a separate PostgreSQL database. This prevents data from different experiments from being mixed and makes the results easier to reproduce.

For SF2, the target database is `tpcds_sf2`.

### 4.1. Check whether the database exists

**Where:** Mac / VS Code Terminal.

```bash
docker exec tpcds-postgres psql -U tpcds -d postgres \
  -c "SELECT datname FROM pg_database WHERE datname = 'tpcds_sf2';"
```

If the database does not exist, create it:

```bash
docker exec tpcds-postgres psql -U tpcds -d postgres \
  -c 'CREATE DATABASE tpcds_sf2;'
```

Run the creation command only once for a database that does not already exist.

### 4.2. Create the schema

Create the tables using the project's TPC-DS schema definition:

```bash
docker exec -i tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  < DSGen-software-code-4.0.0/tools/tpcds.sql
```

Verify the tables:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "\dt"
```

### 4.3. Test loading one table

Before loading every table, test the process with `customer.dat`.

**Where:** Mac / VS Code Terminal.

```bash
docker exec tpcds-postgres \
  psql -v ON_ERROR_STOP=1 -U tpcds -d tpcds_sf2 \
  -c "COPY customer FROM '/benchmarks/sf2/data/customer.dat' WITH (FORMAT csv, DELIMITER '|', NULL '');"
```

A successful load returns a message such as `COPY 100000`. The actual row count depends on the size of dataset.

Verify the table:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "SELECT COUNT(*) FROM customer;"
```


### 4.4. Load the remaining tables

After verifying the customer load, load the other data files.

The following example skips `customer` because it assumes that table has already been loaded successfully:

```bash
for file in benchmarks/sf2/data/*.dat; do
    table=$(basename "$file" .dat)

    if [ "$table" = "customer" ]; then
        echo "Skipping customer (already loaded)"
        continue
    fi

    echo "Loading $table..."

    if ! docker exec tpcds-postgres \
        psql -v ON_ERROR_STOP=1 -U tpcds -d tpcds_sf2 \
        -c "COPY \"$table\" FROM '/benchmarks/sf2/data/$table.dat' WITH (FORMAT csv, DELIMITER '|', NULL '');"
    then
        echo "Loading failed for $table; stopping."
        break
    fi
done
```
<!-- 

### 4.5. Verify Data Loading and Database Size

Before running the benchmark, we need to make sure that all TPC-DS data has been loaded correctly into PostgreSQL. Missing or duplicated data can produce incorrect query results and unreliable execution times.

#### Step 1: Check the Data Loading

Each `.dat` file must match the structure of its corresponding PostgreSQL table.

Some databases require tables to be loaded in a specific order because of foreign-key constraints. However, if the TPC-DS schema does not enforce these constraints, the loading order usually does not matter.

**Important:** If loading fails, previously loaded tables are not automatically removed. Before restarting, check which tables already contain data to avoid inserting duplicate rows.

#### Step 2: Check the Database Size

Run the following command from the Mac terminal:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

This command shows the total disk space used by the SF2 database.

It is useful for:
- Checking whether the database size looks reasonable.
- Comparing storage requirements across different scale factors.
- Detecting possible loading problems, such as an unexpectedly small database.

#### Step 3: Check Table and Index Sizes (Optional)

Run the following SQL in pgAdmin or PostgreSQL:

```sql
SELECT
    pg_size_pretty(SUM(pg_table_size(relid))) AS tables_size,
    pg_size_pretty(SUM(pg_indexes_size(relid))) AS indexes_size,
    pg_size_pretty(SUM(pg_total_relation_size(relid))) AS total_size
FROM pg_catalog.pg_statio_user_tables;
```

This query shows:
- **tables_size:** Disk space used by the tables.
- **indexes_size:** Disk space used by the indexes.
- **total_size:** Combined size of tables and indexes.

This is particularly useful when evaluating indexing optimizations, since indexes can improve query performance but also increase storage usage.

#### Step 4: Verify Table Row Counts

Checking database size alone does not guarantee that all data was loaded correctly. We should also verify that the expected tables exist and compare their row counts with the generated data files.

For example, to check the `customer` table:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "SELECT COUNT(*) FROM customer;"
```

This returns the exact number of rows in the `customer` table. Repeat the check for other tables as needed. -->

## 5. Analyzing and Preparing the Database

PostgreSQL uses statistics to estimate row counts and selectivity when planning queries.

After loading a dataset, run `ANALYZE` before benchmarking so that the planner has current statistics.

For the SF2 database:

```bash
docker exec tpcds-postgres psql -v ON_ERROR_STOP=1 \
  -U tpcds -d tpcds_sf2 \
  -c "ANALYZE;"
```

Verify that the tables have been analyzed:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "SELECT relname, last_analyze, last_autoanalyze FROM pg_stat_user_tables ORDER BY relname;"
```

Repeat the process for each scale-factor database before measuring its performance.

## 6. Generating SQL Queries

The TPC-DS query generator, `dsqgen`, generates SQL statements from the `DSGen-software-code-4.0.0/query_templates`. 

### 6.1. Fixing PostgreSQL Compatibility Issues in Query Templates

Before generating the SQL queries, we need to make some modifications to the original TPC-DS query templates (`.tpl` files).

Some expressions in the original templates are not compatible with PostgreSQL and can cause errors when executing the generated queries.

We identified **three categories of compatibility issues** that must be fixed before query generation.


#### Issue 1: Invalid Date Arithmetic (`+ 30 days`)

Some query templates use date arithmetic expressions such as:

```sql
CAST('2002-08-26' AS DATE) + 30 days
```

This syntax is not supported by PostgreSQL. PostgreSQL allows adding an integer directly to a `DATE` value, so we only need to remove the word `days`:

```sql
CAST('2002-08-26' AS DATE) + 30
```

**Affected queries:**

`Q05, Q12, Q16, Q20, Q21, Q32, Q37, Q40, Q77, Q80, Q82, Q92, Q94, Q95, Q98`


#### Issue 2: Incorrect Column Reference (Query 30)

In `query30.tpl`, replace:

```sql
c_last_review_date_sk
```

with:

```sql
c_last_review_date
```

#### Issue 3: Unsupported `lochierarchy` Expressions (Queries 36, 70, and 86)

Some query templates use the expression `lochierarchy`, which is not defined in PostgreSQL.

We replace these expressions with PostgreSQL's `GROUPING()` function, which can identify the grouping level when using grouping sets or rollups.

**Query 36 — `query36.tpl`**

Replace:

```sql
,case when lochierarchy = 0 then i_category end
```

with:

```sql
,case when grouping(i_category)+grouping(i_class) = 0 then i_category end
```

**Query 70 — `query70.tpl`**

Replace:

```sql
,case when lochierarchy = 0 then s_state end
```

with:

```sql
,case when grouping(s_state)+grouping(s_county) = 0 then s_state end
```

**Query 86 — `query86.tpl`**

Replace:

```sql
case when lochierarchy = 0 then i_category end,
```

with:

```sql
case when grouping(i_category)+grouping(i_class) = 0 then i_category end,
```

### 6.2. Fixing the `_END not defined` Error

During query generation, we also encountered the `_END not defined` error.

To solve this issue without modifying the original `netezza.tpl`, we created a new dialect template named `postgresql.tpl`, based on `netezza.tpl`.

We added the following definition at the end of the new file:

```text
define _END = "";
```

The new dialect template is saved in:

```text
DSGen-software-code-4.0.0/query_templates/postgresql.tpl
```

From this point onward, we use our custom PostgreSQL dialect when generating queries:

```bash
-DIALECT postgresql
```

### 6.3. Generate SQL Queries After Applying the Fixes

After applying all the changes above, we can generate the SQL queries using `dsqgen`.

Start the tools container:

```bash
docker exec -it tpcds-tools bash
```

Inside the container:

```bash
cd /tpcds/tools
mkdir -p /benchmarks/sf2/queries

./dsqgen \
  -DIRECTORY ../query_templates \
  -INPUT ../query_templates/templates.lst \
  -SCALE 2 \
  -DIALECT postgresql \
  -QUALIFY Y \
  -VERBOSE Y \
  -RNGSEED 123 \
  -OUTPUT_DIR /benchmarks/sf2/queries
```

The options specify the template directory, template list, scale factor, SQL dialect, qualification setting, verbosity, random seed, and output directory.

The `-QUALIFY Y` option is important because it helps keep the generated queries in a consistent order matching the template list. This allows us to compare the same queries across different scale factors (SF1, SF2, SF5, and SF10) and analyze how their execution times change as the dataset size increases.


### 6.4. Splitting the Combined SQL file

The combined SQL file must be split into individual query files if the benchmark runner expects one SQL statement or query per file.

The intended structure is:

```text
benchmarks/sf2/queries/
├── query_0.sql
├── query_1.sql
├── query_2.sql
├── ...
└── query_99.sql
```
run the command below in the tpcds-postgresl folder not it the docker containers

```bash
python3 1_split_queries.py -i ./benchmarks/sf1/queries/query_0.sql -o ./benchmarks/sf1/queries
```
now we expect to see 99 seperate `.sql` files for each query in the `./benchmarks/sf1/queries`

## 7. Running the TPC-DS Baseline Benchmark

Run the following command from the **project root in the Mac terminal**:

```bash
python3 2_run_benchmark.py \
  -i benchmarks/sf2/queries \
  -o benchmarks/sf2/results_baseline \
  -d tpcds_sf2 \
  -n 3 \
  --set work_mem=256MB \
  --set hash_mem_multiplier=2 \
  --set max_parallel_workers_per_gather=4 \
  --set effective_cache_size=10GB \
  --set random_page_cost=1.1 \
  --set jit=off \
  --statement-timeout-ms 600000 \
  --no-save-results \
  --order suite \
  2>&1 | tee sf2_baseline.log
```

### 7.2. Explanation of the Parameters

| Parameter | Description |
|-----------|-------------|
| `-i` | Directory containing the individual SQL query files. |
| `-o` | Directory where benchmark results will be saved. |
| `-d tpcds_sf2` | PostgreSQL database containing the SF2 dataset. |
| `-n 3` | Executes the complete benchmark three times. |
| `--set work_mem=256MB` | Sets the memory available for individual query operations such as sorting and hashing. |
| `--set hash_mem_multiplier=2` | Allows hash operations to use up to twice the `work_mem` limit. |
| `--set max_parallel_workers_per_gather=4` | Allows up to four parallel workers for eligible query operations. |
| `--set effective_cache_size=10GB` | Tells the query planner how much cache memory is estimated to be available. It does not allocate 10 GB of memory. |
| `--set random_page_cost=1.1` | Sets the planner's estimated cost of random disk access. |
| `--set jit=off` | Disables Just-In-Time compilation. |
| `--statement-timeout-ms 600000` | Sets a 10-minute timeout for each SQL statement. |
| `--no-save-results` | Avoids saving individual query result rows to reduce storage usage. |
| `--order suite` | Runs the entire query suite once before starting the next iteration. |
| `2>&1 \| tee sf2_baseline.log` | Displays the benchmark output in the terminal and saves it to a log file. |

### 7.3. Benchmark Execution Method

The benchmark uses **plain SQL execution with PostgreSQL's `psql \timing`**, rather than `EXPLAIN ANALYZE`.

The script measures the execution time of each query and records it in seconds.

We use three complete benchmark iterations (`-n 3`) to reduce the influence of variations between individual executions.

The `--order suite` option determines the execution order:

- **Run 1:** Q01 → Q02 → ... → Q99
- **Run 2:** Q01 → Q02 → ... → Q99
- **Run 3:** Q01 → Q02 → ... → Q99

This approach allows us to observe query performance across repeated complete benchmark runs instead of executing the same query three times consecutively.

Some TPC-DS query files contain multiple SQL statements. The script executes all statements in the file and sums their execution times to obtain the query's total execution time.

### 7.4. Statement Timeout

We set a maximum execution time of **10 minutes (600 seconds)** per SQL statement:

```bash
--statement-timeout-ms 600000
```

If a statement exceeds this limit, PostgreSQL cancels its execution and the script records the attempt as failed.

This prevents extremely slow queries from running indefinitely.

### 7.5. Benchmark Output Files

The script creates the following files:

```text
benchmarks/sf2/results_baseline/
├── exec_time_details.csv
└── benchmark_summary.txt

sf2_baseline.log
```

**`exec_time_details.csv`**

Contains the execution time of each query across the three iterations, including:

- Query identifier (Q01–Q99).
- Execution status (`SUCCESS`, `PARTIAL`, or `FAILED`).
- Execution time for each run.
- Average, median, minimum, and maximum execution times.
- Error messages for failed executions.

All execution times are recorded in **seconds**.

The CSV file is updated after each query execution, so completed measurements are preserved even if the benchmark is interrupted.

**`benchmark_summary.txt`**

Contains an overview of the experiment, including the database name, execution method, PostgreSQL settings, number of queries, successful and failed queries, and total benchmark runtime.

**`sf2_baseline.log`**

Contains the terminal output of the benchmark, including query execution messages, errors, and progress information.

### 7.6. Resuming an Interrupted Benchmark

If the benchmark is interrupted, we can continue it using the `--resume` option.

Use the same command and settings as the original benchmark, but add:

```bash
--resume
```

The script reads the existing CSV file and continues the missing executions without repeating completed attempts. It also creates backups of the existing CSV and summary files.

Validating Original and Optimized Queries

We first optimize the TPC-DS queries on **SF1** and then apply the same optimizations to larger scale factors.

Since TPC-DS may generate different query parameters for different scale factors, we must verify that the optimized queries produce the same results as the original queries at each scale factor.

## 8. The `compare_benchmark.py` script:
- Executes both original and optimized queries on the same database.
- Compares their result sets to verify correctness.
- Measures execution times and calculates speedup.
- Saves execution plans and reports any result mismatches.

### Running the Comparison (Example: SF10)

Run from the project root:

```bash
caffeinate -i python3 compare_benchmark.py \
  --sf 10 \
  -d tpcds_sf10 \
  -i benchmarks/sf10/queries \
  --optimized-dir benchmarks/sf10/optimized_queries \
  -o benchmarks/sf10/results_compare \
  --run-id sf10_compare \
  -n 1 \
  --set work_mem=256MB \
  --set hash_mem_multiplier=2 \
  --set max_parallel_workers_per_gather=4 \
  --set effective_cache_size=10GB \
  --set random_page_cost=1.1 \
  --set jit=off \
  2>&1 | tee sf10_compare.log
```

The command executes each query version once (`-n 1`) using the same PostgreSQL settings. The `caffeinate -i` option prevents macOS from entering idle sleep during the benchmark.

Results are saved in: `benchmarks/sf10/results_compare/sf10_compare/`

The main output files are:

- `summary.csv`: Query execution times, speedup, and result-matching status.
- `runs.csv`: Individual execution times for both query versions.
- `plans/`: Execution plans for original and optimized queries.
- `mismatches/`: Differences between result sets, if any.
- `config.json`: Configuration used for the comparison.

**Important:** In `summary.csv`, `results_match=True` confirms that the original and optimized queries returned identical result sets, including duplicate rows, regardless of row order. A missing value means the comparison could not be completed.

