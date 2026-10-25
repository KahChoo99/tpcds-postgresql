# TPC-DS PostgreSQL benchmark — reproducible workflow

This README documents the **TPC-DS 4.0.0 + PostgreSQL 16 + Docker Compose** workflow for generating data and SQL queries at different scale factors (SF). It reflects the working directory layout and commands used in this project. **Steps marked PENDING must be verified against your Python scripts and actual SF 2 database setup before they are run.**

## 0. Environment and folder conventions

Run commands in one of two places:

- **Mac / VS Code Terminal:** at the root of the local `tpcds-postgresql` project, alongside `docker-compose.yml`.
- **Docker tools shell:** inside container `tpcds-tools`, in `/tpcds/tools`. Use this shell for `dsdgen` and `dsqgen`.

PostgreSQL runs in `tpcds-postgres` and is reachable on Mac port `5436` (container port `5432`). The original database is `tpcds`, with credentials from your Compose file.

Project structure:

```text
tpcds-postgresql/
├── docker-compose.yml
├── Dockerfile.tpcds
├── DSGen-software-code-4.0.0/
│   ├── tools/                      # dsdgen and dsqgen
│   └── query_templates/            # .tpl templates + templates.lst
├── benchmarks/
│   ├── sf1/{data,queries,results}/
│   ├── sf2/{data,queries,results}/
│   ├── sf4/{data,queries,results}/
│   └── sf7/{data,queries,results}/
├── data/                           # legacy mount, retained
├── data-clean/                     # legacy read-only postgres mount, retained
└── generated_queries/              # legacy mount, retained
```

The Compose configuration preserves the original mounts and adds `./benchmarks` for both services:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: tpcds-postgres
    environment:
      POSTGRES_DB: tpcds
      POSTGRES_USER: tpcds
      POSTGRES_PASSWORD: tpcds
    ports:
      - "5436:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./data-clean:/data:ro
      - ./benchmarks:/benchmarks:ro

  tpcds-tools:
    build:
      context: .
      dockerfile: Dockerfile.tpcds
    container_name: tpcds-tools
    volumes:
      - ./DSGen-software-code-4.0.0:/tpcds
      - ./data:/data
      - ./generated_queries:/generated_queries
      - ./benchmarks:/benchmarks
    command: sleep infinity

volumes:
  postgres_data:
```

The `/benchmarks` path is **inside both containers**; `benchmarks/` is the corresponding local path on the Mac. The PostgreSQL mount is read-only; that is fine for server-side `COPY FROM`, provided the file is readable by the PostgreSQL process.

### Initial setup (one time)

**Mac / VS Code Terminal** (from the project root):

```bash
mkdir -p benchmarks/{sf1,sf2,sf4,sf7}/{data,queries,results}
docker compose config --quiet
```

If you have just added the benchmark mounts, apply the configuration **only after confirming no benchmark or load is running**:

```bash
docker compose up -d --no-deps --force-recreate postgres tpcds-tools
```

This retains the declared named volume; **never run `docker compose down -v`** unless you deliberately intend to delete database storage. Check the active Docker Compose project and existing backups before recreating containers.

Verify:

```bash
docker exec tpcds-tools ls /benchmarks
docker exec tpcds-postgres ls /benchmarks
docker exec tpcds-postgres psql -U tpcds -d tpcds \
  -c "SELECT pg_size_pretty(pg_database_size('tpcds'));"
```

## 1. Generate data for a chosen scale factor

Example: **SF 2**. To use another scale factor, consistently replace `2` and `sf2` in paths and arguments.

**Mac Terminal:**

```bash
docker exec -it tpcds-tools bash
```

**Inside the tools container:**

```bash
cd /tpcds/tools
mkdir -p /benchmarks/sf2/data
./dsdgen \
  -SCALE 2 \
  -DIR /benchmarks/sf2/data \
  -TERMINATE N \
  -FORCE \
  -VERBOSE Y
```

`-TERMINATE N` prevents the *extra record-terminating* `|`, so there is normally no need to create a second `data-clean` directory. **Caution:** `-FORCE` overwrites data files already in the destination; use a new or intentionally cleared folder. The "valid for QUALIFICATION ONLY" warning is expected at small scale factors for this university exercise.

Verify data files exist:

```bash
ls -lh /benchmarks/sf2/data | head
head -n 2 /benchmarks/sf2/data/customer.dat
```

Check the `customer` table's expected **18 fields**, not simply whether a record ends with `|` (an empty final value can legitimately make that happen):

```bash
awk -F'|' '
  NF != 18 { bad++; if (bad <= 5) print "Unexpected field count on row", NR, "=", NF }
  END { if (bad) print "FAIL:", bad, "rows"; else print "PASS:", NR, "rows with 18 fields" }
' /benchmarks/sf2/data/customer.dat
```

For other `.dat` files, validate the number of fields against their **actual table definitions**, not `18` (which applies only to `customer`). Exit the tools container when done:

```bash
exit
```

## 2. Create and load the SF 2 database — PENDING VERIFICATION

Before benchmarking, create a **separate** `tpcds_sf2` database and load all SF 2 tables. Do not load new SF 2 data into the existing `tpcds` SF 1 database.

**Mac Terminal** — check if the target DB exists:

```bash
docker exec tpcds-postgres psql -U tpcds -d postgres \
  -c "SELECT datname FROM pg_database WHERE datname = 'tpcds_sf2';"
```

If absent, create it (run only once):

```bash
docker exec tpcds-postgres psql -U tpcds -d postgres \
  -c 'CREATE DATABASE tpcds_sf2;'
```

The precise schema creation and bulk-loading commands depend on your established SF 1 loading script, table list, and ordering. **These commands have not been confirmed in this conversation; do not improvise `COPY` for every table until the loading process is reviewed.** In particular, verify the schema uses the same keys and indexes as SF 1, whether rows contain `NULL` fields, and whether the `/benchmarks/sf2/data` files are readable in the PostgreSQL container.

Create the tables in:

docker exec -i tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  < DSGen-software-code-4.0.0/tools/tpcds.sql

verify :
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "\dt"


Step 5 — Load all SF 10 data files
WHERE: MacBook — VS Code Terminal
Because you generated your data with -TERMINATE N, you no longer need to remove the last delimiter from the .dat files.
First, test loading one table:
docker exec tpcds-postgres \
  psql -v ON_ERROR_STOP=1 -U tpcds -d tpcds_sf10 \
  -c "COPY customer FROM '/benchmarks/sf10/data/customer.dat' WITH (FORMAT csv, DELIMITER '|', NULL '');"
If successful, PostgreSQL returns something like:
COPY 100000
The actual number of rows depends on the generated dataset.
Now check:
docker exec tpcds-postgres \
  psql -U tpcds -d tpcds_sf10 \
  -c "SELECT COUNT(*) FROM customer;"
If that works, we can load all the other tables.
Run the following from your MacBook Terminal, inside your project directory:

for file in benchmarks/sf10/data/*.dat; do
    table=$(basename "$file" .dat)

    if [ "$table" = "customer" ]; then
        echo "Skipping customer (already loaded)"
        continue
    fi

    echo "Loading $table..."

    docker exec tpcds-postgres \
      psql -v ON_ERROR_STOP=1 -U tpcds -d tpcds_sf10 \
      -c "COPY \"$table\" FROM '/benchmarks/sf10/data/$table.dat' WITH (FORMAT csv, DELIMITER '|', NULL '');" \
      || break
done

Check the database after loading:

```bash
docker exec tpcds-postgres psql -U tpcds -d tpcds_sf2 \
  -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

For table/idx breakdown (run using pgAdmin/DataGrip connected to the correct database):

```sql
SELECT
  pg_size_pretty(SUM(pg_table_size(relid))) AS tables_size,
  pg_size_pretty(SUM(pg_indexes_size(relid))) AS indexes_size,
  pg_size_pretty(SUM(pg_total_relation_size(relid))) AS total_size
FROM pg_catalog.pg_statio_user_tables;
```

## 3. Correct SQL templates once, then generate SF 2 queries

The project's original successful SF 1 generator uses **`-dialect postgresql`**. Keep that dialect for every scale factor to maintain comparable workloads.

### 3a. PostgreSQL date arithmetic fix (one-time template adjustment)

The generated SQL previously contained invalid PostgreSQL syntax, e.g.:

```sql
CAST('2002-08-26' AS DATE) + 30 days
```

For a PostgreSQL `DATE`, the compatible form is:

```sql
CAST('2002-08-26' AS DATE) + 30
```

Apply equivalent targeted changes in the relevant `DSGen-software-code-4.0.0/query_templates/*.tpl` files, keeping template variables intact. **Do not** change column aliases such as `AS "30 days"` or numeric comparisons like `<= 30`; they are not this syntax error. Do not make blanket replacements inside interval literals. Back up original templates and record changes in version control before changing them.

To find remaining literal variants (**Mac Terminal**):

```bash
grep -RnEi '\+[[:space:]]*[0-9]+[[:space:]]+days\b' \
  DSGen-software-code-4.0.0/query_templates/ --include='*.tpl'
```

This does not catch every parameterized template form, so also inspect references to `days` if necessary:

```bash
grep -RnEi 'days' DSGen-software-code-4.0.0/query_templates/ --include='*.tpl'
```

### 3b. Delete only old SF 2 generated SQL

**Mac / VS Code Terminal, from the project root:**

```bash
find benchmarks/sf2/queries -maxdepth 1 -type f -name 'query_*.sql' -print
```

Review the filenames, stop any active SF 2 query processing, and **only if you deliberately want to regenerate them**, delete:

```bash
find benchmarks/sf2/queries -maxdepth 1 -type f -name 'query_*.sql' -delete
```

This leaves SF 1 SQL and data untouched.

### 3c. Regenerate using your PostgreSQL dialect

**Mac Terminal:**

```bash
docker exec -it tpcds-tools bash
```

**Inside Docker:**

```bash
cd /tpcds/tools
mkdir -p /benchmarks/sf1/queries_ordered

./dsqgen \
  -DIRECTORY ../query_templates \
  -INPUT ../query_templates/templates.lst \
  -SCALE 1 \
  -DIALECT netezza \
  -QUALIFY Y \
  -VERBOSE Y \
  -OUTPUT_DIR /benchmarks/sf1/queries_ordered
```
Better option:
./dsqgen   -DIRECTORY ../query_templates   -INPUT ../query_templates/templates.lst   -SCALE 1   -DIALECT postgresql   -QUALIFY Y   -VERBOSE Y -RNGSEED 123  -OUTPUT_DIR /benchmarks/sf1/queries

Verify:

```bash
ls -lh /benchmarks/sf2/queries
head -n 25 /benchmarks/sf2/queries/query_0.sql
if grep -nEi '\+[[:space:]]*[0-9]+[[:space:]]+days\b' \
  /benchmarks/sf2/queries/query_0.sql; then
  echo 'FAIL: invalid + N days syntax found'
else
  echo 'PASS: no literal + N days syntax found'
fi
exit
```

`dsqgen` in this setup produces a **combined** `query_0.sql`. It does not automatically create separate `query_1.sql` through `query_99.sql` files.

## 4. Split the combined query file — PENDING SCRIPT REVIEW

Use your existing `1_split_queries.py` locally, not in the PostgreSQL container. The intended input/output are:

```text
Input:  benchmarks/sf2/queries/query_0.sql
Output: benchmarks/sf2/queries/query_1.sql, query_2.sql, ...
```

**Mac / VS Code Terminal:**

```bash
find . -name '1_split_queries.py'
```

Read the script's command-line arguments before invoking it. **Do not assume** it takes `--input` and `--output`, or run it with hard-coded SF 1 paths. If supported, configure it so it reads the SF 2 combined file and writes SF 2 individual files. Check its numbering and delimiters against the actual generated SQL. Keep `query_0.sql` for reproducibility.

After splitting, count files:

```bash
find benchmarks/sf2/queries -maxdepth 1 -type f \
  -name 'query_*.sql' ! -name 'query_0.sql' | wc -l
```

Expect 99 individual queries **only if** `templates.lst` contains the full 99-query workload and your script splits it accordingly.

## 5. Run benchmarks and collect execution times — PENDING SCRIPT REVIEW

The previously mentioned execution script is `2_run_benchmark.py`. Before running it, verify:

- It reads **only** `benchmarks/sf2/queries/query_1.sql` ... (not the combined `query_0.sql`).
- It connects to **`tpcds_sf2`** in container **`tpcds-postgres`**, not the old `tpcds` database.
- It saves EXPLAIN outputs in **`benchmarks/sf2/results/`**, and doesn't overwrite SF 1 results.
- `psql` is called with `-v ON_ERROR_STOP=1` so SQL failures return an unsuccessful exit code.
- It captures **both** `stdout` and `stderr`, and checks `result.returncode` rather than treating empty output as a successful query.
- It uses the same measurement method, database configuration, and repetitions as SF 1. `EXPLAIN (ANALYZE, BUFFERS)` **executes** SQL and can take a long time.

To help prevent macOS idle sleep during a long local Python process, use `caffeinate -i` when you have the **verified** script command and arguments. Keep the laptop lid open, and Docker running. Example shape (NOT a confirmed invocation):

```bash
caffeinate -i python3 PATH_TO/2_run_benchmark.py [VERIFIED_ARGUMENTS]
```

Then use the project's existing time-extraction/CSV script (name and arguments need to be confirmed) to save a separate SF 2 CSV. Record individual failed queries as failures, not zero-second executions.

## 6. Repeat for later scale factors

The intended scale-factor series is **1, 2, 4, 7**. For each new scale, consistently update:

| Setting | SF 2 | SF 4 | SF 7 |
|---|---|---|---|
| Data generator | `-SCALE 2` | `-SCALE 4` | `-SCALE 7` |
| Query generator | `-scale 2` | `-scale 4` | `-scale 7` |
| Local data path | `benchmarks/sf2/data` | `benchmarks/sf4/data` | `benchmarks/sf7/data` |
| Query path | `benchmarks/sf2/queries` | `benchmarks/sf4/queries` | `benchmarks/sf7/queries` |
| Results path | `benchmarks/sf2/results` | `benchmarks/sf4/results` | `benchmarks/sf7/results` |
| DB name | `tpcds_sf2` | `tpcds_sf4` | `tpcds_sf7` |

Benchmark the same intended logical workload, indexing strategy, PostgreSQL settings, and timing procedure at each scale factor. TPC-DS query parameters may vary with SF. Do not assume execution time grows linearly or exponentially; measure it.

## 7. Storage management and safety

- Keep Python code, query templates, individual SQL queries, results, and CSV files.
- After validating a loaded database and saving needed artifacts, consider deleting no-longer-needed raw `.dat` files **only from the intended SF data folder**. First verify the pathname with `ls`/`find`.
- Data on bind mounts consumes your Mac's disk space; PostgreSQL's named volume consumes Docker-managed disk space as well.
- **Do not delete** `postgres_data` or execute `docker compose down -v` to reclaim space.
- The original SF 1 measurements in this project were approximately **1.25 GB raw files, 2.35 GB user tables+indexes**, and **33 minutes total query execution**; these are observed SF 1 values, not guaranteed projections to larger SFs.

## 8. Remaining information needed to finalize this README

1. The exact content/arguments of `1_split_queries.py`.
2. The schema creation and SF 2 data loading commands actually used.
3. The exact content/arguments of `2_run_benchmark.py`.
4. The name and arguments of the execution-time-to-CSV extraction script.
5. Verification that all generated SF 2 queries run successfully, including any additional PostgreSQL compatibility fixes.

Once those stages are completed and tested, replace the PENDING sections with the precise working commands. This makes the README reproducible rather than guessing command-line options.
