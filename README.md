# TPC-DS Benchmarking and Query Optimization on PostgreSQL

Course project for *Data Warehouses* (INFO-H419), Université Libre de Bruxelles.

This repository contains everything needed to run the TPC-DS 4.0.0 benchmark on PostgreSQL 16 in Docker at several scale factors, to compare the original queries with our optimized queries, and to measure the effect of secondary indexes and table clustering.

## Project Overview

This project evaluates PostgreSQL performance using the TPC-DS 4.0.0 benchmark, PostgreSQL 16, and Docker Compose.

The workflow covers:

1. Generating TPC-DS datasets at different scale factors.
2. Creating and loading separate PostgreSQL databases for each scale factor.
3. Generating SQL queries using the PostgreSQL dialect.
4. Splitting the generated SQL workload into individual queries.
5. Executing queries and collecting performance measurements.
6. Optimize slow queries and executing the optimized queries.
7. Adding indexes to the database and executing the optimized queries.
8. Creating indexes, physically clustering selected tables using their indexes, and re-executing the optimized queries to evaluate their performance.
<!-- 6. Comparing query results against reference outputs.
7. Extracting execution times and generating performance plots. -->

The target scale factors are SF1, SF2, SF5, and SF10. Each scale factor has its own data, queries, and results directories to keep experiments separate and reproducible.

**This README has two parts:**

| Part | For whom | Content |
| --- | --- | --- |
| **Part A – Reproduce the benchmark** | Reviewers / professor | One command (`python3 5_run_complete_tpcds_experiment.py`) that builds the database for a scale factor and runs our optimized queries on it. |
| **Part B – Full manual workflow** | Team members, anyone who wants every step | The step-by-step commands we used to produce all results of the report, including the baseline, the comparison script and the load test. |

---

# Part A – Reproduce the benchmark
## Running the Complete TPC-DS Benchmark with Single Script

The `5_run_complete_tpcds_experiment.py` script automates the complete TPC-DS benchmarking workflow using PostgreSQL 16 and Docker.

On the first execution for a scale factor, the script generates the dataset, creates and loads the PostgreSQL database, creates 8 indexes, clusters 4 selected tables, and executes the optimized queries. On subsequent executions, the existing database, data, and indexes are reused.

### 1. Prerequisites

Before running the experiment:

- Install and start **Docker Desktop**.
- Install **Python 3** (no additional Python packages are required).
- Run all commands from the root directory of the `tpcds-postgresql` repository.
- Ensure the repository contains the required Python scripts, SQL files, `Dockerfile.tpcds`, and TPC-DS generator source files.

The directory structure is:

```text
benchmark-test/
└── sf2/
    ├── data/
    ├── queries/
    ├── optimized_queries/
    └── results/
```

- `data/`: Stores the generated TPC-DS dataset.
- `queries/`: Stores the original SQL queries (not executed by this script).
- `optimized_queries/`: Contains the optimized SQL query files to execute.
- `results/`: Stores query execution times, logs, and benchmark results.

**Important:** The optimized SQL files must already exist in `optimized_queries/` for all selected queries. The script generates the data files automatically if needed, but it does not generate optimized SQL queries.

### 2. Execute the Experiment

To run all 99 optimized queries for SF2, execute:

```bash
python3 5_run_complete_tpcds_experiment.py \
  --sf 2 \
  --runs 1 \
  --queries 1-99 \
  --run-id sf2_test_1 \
  --postgres-port 55436
```

### Command-Line Arguments

| Argument | Description |
|---|---|
| `--sf` | **Required.** Dataset scale factor (e.g., `1`, `2`, `5`, `10`). |
| `--runs` | Number of executions per query. Default: `3`. |
| `--queries` | Queries to execute, e.g., `1-99`, `1-20`, or `4,25,30`. Default: `1-99`. |
| `--run-id` | Unique identifier for the results folder, e.g., `sf2_test_1`. If omitted, a timestamp is generated automatically. |
| `--postgres-port` | Optional localhost port for accessing PostgreSQL through pgAdmin or another client. |
| `--benchmark-root` | Directory containing the benchmark data and results. Default: `benchmark-test`. |
| `--keep-container-running` | Keeps the PostgreSQL container running after execution. By default, it is stopped automatically. |
| `--regenerate-data` | Forces regeneration of the TPC-DS dataset. If the database already exists, this must be combined with `--rebuild-database`. |
| `--rebuild-database` | Drops and recreates the experiment database, including its tables, data, indexes, and clustering. |

### 3. Benchmark Results

Each execution generates a separate folder under:

```text
benchmark-test/sf2/results/
├── sf2_test_1/
└── sf2_test_2/
```

The main output files include:

- `exec_time_details.csv`: Execution times and statuses of individual queries.
- `benchmark_summary.txt`: Overall benchmark summary.
- `verification_summary.txt`: Query success counts and sum of average execution times.
- `experiment_config.json`: Configuration and parameters used for the experiment.
- `benchmark.log`: Benchmark execution logs.
- `workflow.log`: Detailed workflow logs, including data loading, indexing, clustering, and execution.
- `index_inventory.csv`: Lists the database indexes and identifies the clustered ones.

**Note:** By default, the PostgreSQL container is stopped after execution, but the database and its Docker volume are preserved for future runs. The benchmark runs without a statement timeout, allowing slow queries to execute without a configured time limit.



### 4. Remark: In the Case of Running the Benchmark Again for the same SF

The script creates a persistent PostgreSQL database for each scale factor. Therefore, repeating the experiment for the same scale factor does not require generating or loading the data again.

To execute the same benchmark again, use a different `--run-id`:

```bash
python3 5_run_complete_tpcds_experiment.py \
  --sf 2 \
  --runs 1 \
  --queries 1-99 \
  --run-id sf2_test_2 \
  --postgres-port 55436
```

The same database and indexes are reused, while the results are saved separately.

If a PostgreSQL port was specified when the container was first created, the same port must be used for subsequent runs.

To recreate the database and repeat the complete initialization process, add:

```bash
--rebuild-database
```

To regenerate the dataset as well, use both:

```bash
--rebuild-database --regenerate-data
```


# Part B – Full manual workflow
This part is the step-by-step workflow we used to produce all results of the report. 

## 1. Environment and Project Structure

## Architecture: two containers

One Compose file starts two containers.

| Container | Job | How you use it | 
| --- | --- | --- |
| `tpcds-postgres` (image `postgres:16`) | Database: create schema, load data, run queries | `docker exec -it tpcds-postgres bash` |
| `tpcds-tools` (built from `Dockerfile.tpcds`) | Generator: `dsdgen` creates data, `dsqgen` creates queries | `docker exec -it tpcds-tools bash`, then work in `/tpcds/tools` | 

Data flow:

1. `dsdgen` (tools) writes `.dat` files to `/benchmarks/sf{i}/data`.
2. Postgres reads the same files with server-side `COPY` and fills `tpcds_sf{i}`.
3. `dsqgen` (tools) writes SQL to `/benchmarks/sf{i}/queries`.
4. 1_split_queries.py Python scripts split the single generated SQL to 99 separated queries, and save timings in `benchmarks/sf{i}/results`.

### 1.1. Benchmark directory structure

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
│   │   ├── optimized_queries/
│   │   ├── results_baseline/
│   │   ├── results_optimization/
│   │   ├── results_optimization_index/
│   │   └── results_clustered_indexes/
│   ├── sf2/
│   │   ├── data/
│   │   ├── queries/
│   │   ├── optimized_queries/
│   │   ├── results_baseline/
│   │   ├── results_optimization/
│   │   ├── results_optimization_index/
│   │   └── results_clustered_indexes/
│   ├── sf5/
│   │   ├── data/
│   │   ├── queries/
│   │   ├── optimized_queries/
│   │   ├── results_baseline/
│   │   ├── results_optimization/
│   │   ├── results_optimization_index/
│   │   └── results_clustered_indexes/
│   ├── sf10/
│   │   ├── data/
│   │   ├── queries/
│   │   ├── optimized_queries/
│   │   ├── results_baseline/
│   │   ├── results_optimization/
│   │   ├── results_optimization_index/
│   │   └── results_clustered_indexes/
└── [project scripts]
```

The directories have the following purposes:

- `data/`: Generated TPC-DS `.dat` files.
- `queries/`: Generated SQL workload, including the combined query file and individual query files.
- `results_baseline/`: Execution results of the original queries on the baseline database.
- `results_optimization/`: Execution results of the optimized queries on the baseline database.
- `results_optimization_index/`: Execution results of the optimized queries on the indexed database.
- `results_clustered_indexes/`: Execution results of the optimized queries on the database with selected tables clustered using indexes.


### 1.2. Docker volume mounts

The local `benchmarks/` directory is mounted inside both containers at `/benchmarks`.

Consequently, files created under `/benchmarks` inside the tools container are available locally under `benchmarks/` on the Mac. The PostgreSQL container can also access these files through its mount.

The PostgreSQL mount is read-only in the current configuration. This is sufficient for server-side `COPY FROM`, provided that the files are readable by the PostgreSQL operating-system user.

---

## 2. Generating TPC-DS Data

Run this in the VS Code terminal to Start the tools container

```bash
docker exec -it tpcds-tools bash
```
Inside the tools container, run:
```bash
for sf in 1 2 5 10; do
  mkdir -p /benchmarks/sf${sf}/{data,queries}
done
```
This creates the following directory structure to store the generated data and the generated queries:

```text
benchmarks/
├── sf1/
│   ├── data/
│   └── queries/
├── sf2/
│   ├── data/
│   └── queries/
├── sf5/
│   ├── data/
│   └── queries/
└── sf10/
    ├── data/
    └── queries/
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

## 3. Creating PostgreSQL Databases and Loading data

Each scale factor should use a separate PostgreSQL database. This prevents data from different experiments from being mixed and makes the results easier to reproduce.

For SF2, the target database is `tpcds_sf2`.

### 3.1. Check whether the database exists

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

### 3.2. Create the schema

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

### 3.3. Test loading one table

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


### 3.4. Load the remaining tables

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

## 4. Analyzing and Preparing the Database

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

## 5. Generating SQL Queries

The TPC-DS query generator, `dsqgen`, generates SQL statements from the `DSGen-software-code-4.0.0/query_templates`. 

### 5.1. Fixing PostgreSQL Compatibility Issues in Query Templates

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

### 5.2. Fixing the `_END not defined` Error

During query generation, we also encountered the `_END not defined` error. Because the toolkit does not include a PostgreSQL template, we created `postgresql.tpl` from `netezza.tpl` and fixed syntax incompatibilities in date expressions, ORDER BY aliases, and column names.

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

### 5.3. Generate SQL Queries After Applying the Fixes

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

this command generated all 99 queries in a signle `query_0.sql`.


### 5.4. Splitting the Combined SQL file

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
python3 1_split_queries.py -i ./benchmarks/sf2/queries/query_0.sql -o ./benchmarks/sf2/queries
```
now we expect to see 99 seperate `.sql` files for each query in the `./benchmarks/sf2/queries`

## 6. Running the TPC-DS Baseline Benchmark

Run the following command from the **project root in the Mac terminal**:

```bash
python3 2_run_tpcds_benchmark.py \
  -i benchmarks/sf2/queries \
  -o benchmarks/sf2/results_baseline \
  -d tpcds_sf2 \
  -n 3 \
  --set work_mem=512MB \
  --set hash_mem_multiplier=2 \
  --set max_parallel_workers_per_gather=4 \
  --set effective_cache_size=10GB \
  --set random_page_cost=1.1 \
  --set jit=off \
  --no-save-results \
  --order suite \
  2>&1 | tee sf2_baseline.log
```

### 6.1 Explanation of the Parameters

| Parameter | Description |
|-----------|-------------|
| `-i` | Directory containing the individual SQL query files. |
| `-o` | Directory where benchmark results will be saved. |
| `-d tpcds_sf2` | PostgreSQL database containing the SF2 dataset. |
| `-n 3` | Executes the complete benchmark three times. |
| `--set work_mem=512MB` | Sets the memory available for individual query operations such as sorting and hashing. |
| `--set hash_mem_multiplier=2` | Allows hash operations to use up to twice the `work_mem` limit. |
| `--set max_parallel_workers_per_gather=4` | Allows up to four parallel workers for eligible query operations. |
| `--set effective_cache_size=10GB` | Tells the query planner how much cache memory is estimated to be available. It does not allocate 10 GB of memory. |
| `--set random_page_cost=1.1` | Sets the planner's estimated cost of random disk access. |
| `--set jit=off` | Disables Just-In-Time compilation. |
| `--no-save-results` | Avoids saving individual query result rows to reduce storage usage. |
| `--order suite` | Runs the entire query suite once before starting the next iteration. |
| `2>&1 \| tee sf2_baseline.log` | Displays the benchmark output in the terminal and saves it to a log file. |

To store the results of running optimized queries on the baseline dataset and databases with indexes we used the same script but change the input `-i` and output `-o` paths.


### 6.2 Benchmark Execution Method

The script measures the execution time of each query and records it in seconds.

We use three complete benchmark iterations (`-n 3`) to reduce the influence of variations between individual executions.

The `--order suite` option determines the execution order:

- **Run 1:** Q01 → Q02 → ... → Q99
- **Run 2:** Q01 → Q02 → ... → Q99
- **Run 3:** Q01 → Q02 → ... → Q99

This approach allows us to observe query performance across repeated complete benchmark runs instead of executing the same query three times consecutively.

Some TPC-DS query files contain multiple SQL statements. The script executes all statements in the file and sums their execution times to obtain the query's total execution time.


### 6.3 Benchmark Output Files

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

### 6.4. Resuming an Interrupted Benchmark

If the benchmark is interrupted, we can continue it using the `--resume` option.

Use the same command and settings as the original benchmark, but add:

```bash
--resume
```

The script reads the existing CSV file and continues the missing executions without repeating completed attempts. It also creates backups of the existing CSV and summary files.

Validating Original and Optimized Queries

We first optimize the TPC-DS queries on **SF1** and then apply the same optimizations to larger scale factors.

Since TPC-DS may generate different query parameters for different scale factors, we must verify that the optimized queries produce the same results as the original queries at each scale factor.

## 7. The `3_compare_queries.py` script:
- Executes both original and optimized queries on the same database.
- Compares their result sets to verify correctness.
- Measures execution times and calculates speedup.
- Saves execution plans and reports any result mismatches.

### Running the Comparison (Example: SF10)

Run from the project root:

```bash
caffeinate -i python3 3_compare_queries.py \
  --sf 10 \
  -d tpcds_sf10 \
  -i benchmarks/sf10/queries \
  --optimized-dir benchmarks/sf10/optimized_queries \
  -o benchmarks/sf10/results_compare \
  --run-id sf10_compare \
  -n 1 \
  --set work_mem=512MB \
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



## 8. Index Creation and Table Clustering SQL Files

The following SQL files define the indexes and clustering operations used in the benchmark experiments. 

- **`indexes_nonclustered_14.sql`**: Creates 14 regular (non-clustered) indexes on frequently accessed columns, including date, customer, and item attributes. These indexes aim to improve query performance without changing the physical order of table rows.

- **`indexes_clustered_8.sql`**: Creates 8 regular indexes used in the clustered scenario. Four of these indexes are also used to determine the physical ordering of selected tables.

- **`cluster_four_tables.sql`**: Uses PostgreSQL's `CLUSTER` command to physically reorder four tables (`catalog_sales`, `catalog_returns`, `store_sales`, and `web_sales`) based on their selected indexes. This aims to improve data locality and potentially reduce query execution time.


They are used by the load test script to measure the additional time required for index creation and table clustering, and to support comparisons of query execution performance across database configurations.

PostgreSQL does not have a separate `CREATE CLUSTERED INDEX` command. Instead, regular indexes are created first, and the `CLUSTER` command is then used to physically reorder the corresponding tables.

After creating the indexes and clustering the selected tables, we reran the complete TPC-DS benchmark using `2_run_tpcds_benchmark.py` for each configuration. This allowed us to compare query execution times across the baseline, indexed, and clustered database configurations and evaluate the impact of these optimization techniques on query performance.

## 9. Database Load Test

The `4_load_test_independent_configured.py` script measures and compares database loading times under three different scenarios. Each scenario creates a separate PostgreSQL database using the same pre-generated TPC-DS data.

The three scenarios are:
- **Baseline:** Loads the database without additional indexes.
- **Indexed:** Loads the database and creates  non-clustered indexes.
- **Clustered:** Loads the database, creates 8 indexes, and clusters 4 tables.

For each scenario, the script measures the total time required for schema creation, data loading (`COPY`), index creation, clustering (if applicable), and `ANALYZE`. Data generation is excluded from the measurement.

### Running the Script

Ensure the PostgreSQL Docker container is running and the TPC-DS data files have already been generated.

From the project root directory, execute:

```bash
caffeinate -dims python3 4_load_test_independent_configured.py \
  --sf 2 \
  --run-id run1 \
  --indexes-sql indexes_nonclustered_14.sql \
  --clustered-indexes-sql indexes_clustered_8.sql \
  --cluster-sql cluster_four_tables.sql
```

- `--sf`: Specifies the TPC-DS scale factor.
- `--run-id`: Unique identifier for the experiment.
- `--indexes-sql`: SQL file defining the non-clustered indexes.
- `--clustered-indexes-sql`: SQL file defining the 8 indexes used in the clustered scenario.
- `--cluster-sql`: SQL file containing the clustering commands.



The execution results are automatically saved in:

`benchmarks/sf{i}/results_load_independent/<run-id>/`

This folder contains the total loading times, individual phase execution times, index creation times, configuration verification, and execution logs in CSV, JSON, and TXT formats.
Each run requires a unique `run-id`, since the script creates new databases without overwriting existing ones.