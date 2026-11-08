#!/usr/bin/env python3
"""Reproduce the optimized + clustered TPC-DS/PostgreSQL benchmark.

Run from the tpcds-postgresql project root:
    python3 5_run_complete_tpcds_experiment.py --sf 1

Requires Docker Desktop/Engine, Dockerfile.tpcds, the TPC-DS source tree,
optimized query files under benchmark-test/sf<sf>/optimized_queries/, and the
existing 2_run_tpcds_benchmark.py. Uses only Python's standard library.

All test-only data, query inputs, and results live under ./benchmark-test by
default (configurable with --benchmark-root). The user must create the scale
factor directory structure and place queries/optimized_queries in it before
running the script. The script does NOT create the benchmark root or its
standard folders. It only generates data into the existing data/ folder when
no valid generation manifest exists (or --regenerate-data is supplied), then
creates one persistent PostgreSQL container, volume, and database per scale
factor. The first run initializes its schema, data, indexes, and clustering.
Later runs for that scale factor reuse the same database and indexes. Each run
gets a separate results folder under the pre-existing results/ folder.

Index creation and physical clustering always use the two supplied SQL files:
indexes_clustered_8.sql creates exactly eight custom indexes, then
cluster_four_tables.sql physically clusters exactly four selected tables.
There are no alternative or hard-coded index profiles in this script.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTGRES_IMAGE = "postgres:16"
TOOLS_IMAGE = "tpcds-tools-benchmark-test:latest"
PG_USER = "tpcds"
SCHEMA_FILE = ROOT / "DSGen-software-code-4.0.0" / "tools" / "tpcds.sql"
RUNNER = ROOT / "2_run_tpcds_benchmark.py"

TABLES = {
    "call_center", "catalog_page", "catalog_returns", "catalog_sales",
    "customer", "customer_address", "customer_demographics", "date_dim",
    "household_demographics", "income_band", "inventory", "item",
    "promotion", "reason", "ship_mode", "store", "store_returns",
    "store_sales", "time_dim", "warehouse", "web_page", "web_returns",
    "web_sales", "web_site",
}

# Physically cluster four tables; this does NOT mean every index is clustered.
EXPECTED_CLUSTERED = {
    "catalog_sales": "idx_catalog_sales_cs_sold_date_sk",
    "catalog_returns": "idx_catalog_returns_cr_returned_date_sk",
    "store_sales": "idx_ss_date_item",
    "web_sales": "idx_ws_date_item",
}


SETTINGS = [
    "work_mem=512MB",
    "hash_mem_multiplier=2",
    "max_parallel_workers_per_gather=4",
    "effective_cache_size=10GB",
    "random_page_cost=1.1",
    "jit=off",
]


POSTGRES_SERVER_SETTINGS = [
    "shared_buffers=4GB",
    "work_mem=512MB",
    "hash_mem_multiplier=2",
    "max_parallel_workers_per_gather=4",
    "effective_cache_size=10GB",
    "random_page_cost=1.1",
    "jit=off",
]

STATEMENT_TIMEOUT_MS = 0


class ExperimentError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_name(value: str, description: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ExperimentError(f"Invalid {description}: {value!r}")
    return value


def query_selection(spec: str) -> set[int]:
    if spec.lower() == "all":
        return set(range(1, 100))
    numbers: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if re.fullmatch(r"\d+-\d+", part):
            first, last = map(int, part.split("-"))
            if last < first:
                raise ExperimentError(f"Invalid query range: {part}")
            numbers.update(range(first, last + 1))
        elif part.isdigit():
            numbers.add(int(part))
        else:
            raise ExperimentError(f"Invalid query selection: {part!r}")
    if not numbers or min(numbers) < 1 or max(numbers) > 99:
        raise ExperimentError("Queries must be between 1 and 99.")
    return numbers


class Runner:
    def __init__(self, directory: Path, postgres_container: str):
        self.directory = directory
        self.pg_container = postgres_container
        self.log_path = directory / "workflow.log"
        self.directory.mkdir(parents=True, exist_ok=False)

    def say(self, message: str) -> None:
        line = f"[{utc_now()}] {message}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as out:
            out.write(line + "\n")

    def command(self, args: list[str], *, stdin_file: Path | None = None,
                extra_log: Path | None = None) -> str:
        """Run a command; stream output to terminal and logs; fail on nonzero exit."""
        self.say("$ " + shlex.join(args))
        output: list[str] = []
        input_handle = stdin_file.open("rb") if stdin_file else None
        extra_handle = extra_log.open("w", encoding="utf-8") if extra_log else None
        try:
            with subprocess.Popen(
                args,
                cwd=ROOT,
                stdin=input_handle if input_handle else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            ) as proc:
                assert proc.stdout is not None
                with self.log_path.open("a", encoding="utf-8") as workflow:
                    for line in proc.stdout:
                        print(line, end="", flush=True)
                        workflow.write(line)
                        workflow.flush()
                        if extra_handle:
                            extra_handle.write(line)
                            extra_handle.flush()
                        output.append(line)
                status = proc.wait()
        finally:
            if input_handle:
                input_handle.close()
            if extra_handle:
                extra_handle.close()
        if status != 0:
            raise ExperimentError(f"Command failed with exit code {status}: {shlex.join(args)}")
        return "".join(output)

    def psql(self, database: str, sql: str) -> str:
        return self.command([
            "docker", "exec", "-i", self.pg_container,
            "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", PG_USER,
            "-d", database, "-A", "-t", "-c", sql,
        ])

    def sql_file(self, database: str, sql_path: Path) -> str:
        return self.command([
            "docker", "exec", "-i", self.pg_container,
            "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", PG_USER,
            "-d", database, "-f", "-",
        ], stdin_file=sql_path)


def require_inputs(sf: int, selection: set[int],
                   sf_dir: Path) -> tuple[Path, dict[int, Path], list[Path]]:
    needed = [
        ROOT / "Dockerfile.tpcds",
        SCHEMA_FILE,
        RUNNER,
        ROOT / "verify_load_configuration.sql",
        ROOT / "indexes_clustered_8.sql",
        ROOT / "cluster_four_tables.sql",
    ]
    sql_files = [
        ROOT / "indexes_clustered_8.sql",
        ROOT / "cluster_four_tables.sql",
    ]
    for file in needed:
        if not file.is_file():
            raise ExperimentError(f"Required file missing: {file}")

    query_dir = sf_dir / "optimized_queries"
    if not query_dir.is_dir():
        raise ExperimentError(
            f"Missing optimized queries: {query_dir}\n"
            "Custom optimized SQL cannot be recreated by dsdgen/dsqgen. "
            "Commit the optimized_queries folders to the repository."
        )
    queries: dict[int, Path] = {}
    for file in sorted(query_dir.glob("*.sql")):
        match = re.search(r"(\d+)", file.stem)
        if match and 1 <= int(match.group(1)) <= 99:
            number = int(match.group(1))
            if number in queries:
                raise ExperimentError(f"Duplicate SQL for Q{number:02d}: {file}")
            queries[number] = file
    missing = sorted(selection - queries.keys())
    if missing:
        raise ExperimentError(f"Missing optimized query files for: {missing}")
    empty = [queries[n] for n in selection if not queries[n].read_text(encoding="utf-8").strip()]
    if empty:
        raise ExperimentError(f"Empty query SQL file(s): {empty}")
    return query_dir, queries, sql_files

def ensure_persistent_postgres(
    runner: Runner,
    sf: int,
    host_port: int | None,
    benchmark_root: Path,
) -> tuple[str, bool]:
    """Create one PostgreSQL container per SF, then start and reuse it.

    Stable resources:
      container: tpcds-pg-sf<sf>
      volume:    tpcds_pg_sf<sf>

    Returns (volume_name, container_was_created_this_run).
    """
    if shutil.which("docker") is None:
        raise ExperimentError("Docker is not installed or is not on PATH.")
    engine = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if engine.returncode != 0:
        raise ExperimentError(
            "Docker Engine is not available. Start Docker Desktop/Engine. "
            + engine.stderr.strip()[:400]
        )

    container = runner.pg_container
    volume = f"tpcds_pg_sf{sf}"
    benchmark_root = benchmark_root.resolve()
    if not benchmark_root.is_dir():
        raise ExperimentError(f"Cannot bind mount missing test directory: {benchmark_root}")

    inspect_container = subprocess.run(
        ["docker", "container", "inspect", container],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    inspect_volume = subprocess.run(
        ["docker", "volume", "inspect", volume],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    volume_exists = inspect_volume.returncode == 0

    def wait_until_ready() -> None:
        runner.say("Waiting for PostgreSQL to accept connections ...")
        for _ in range(90):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", PG_USER, "-d", "postgres"],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            if ready.returncode == 0:
                runner.say("Persistent PostgreSQL is ready.")
                return
            time.sleep(2)
        subprocess.run(
            ["docker", "stop", container], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        raise ExperimentError(
            f"PostgreSQL in {container} did not become ready. The container has "
            f"been stopped but its volume is preserved. Inspect: docker logs {container}"
        )

    if inspect_container.returncode == 0:
        try:
            info = __import__("json").loads(inspect_container.stdout)[0]
        except (ValueError, IndexError, TypeError) as exc:
            raise ExperimentError(f"Could not inspect existing container {container}.") from exc

        mounts = info.get("Mounts", [])
        pg_mount = next(
            (m for m in mounts if m.get("Destination") == "/var/lib/postgresql/data"),
            None,
        )
        if not volume_exists or not pg_mount or pg_mount.get("Type") != "volume" or pg_mount.get("Name") != volume:
            raise ExperimentError(
                f"Existing container {container} is not attached to expected persistent "
                f"volume {volume}. It will not be modified automatically."
            )
        benchmark_mount = next(
            (m for m in mounts if m.get("Destination") == "/benchmark-test"), None
        )
        if not benchmark_mount or benchmark_mount.get("Type") != "bind":
            raise ExperimentError(
                f"Existing container {container} lacks the /benchmark-test bind mount. "
                "Recreate only the container while preserving its database volume."
            )

        if host_port is not None:
            bindings = (info.get("HostConfig", {}).get("PortBindings") or {}).get("5432/tcp") or []
            bound_ports = {str(item.get("HostPort")) for item in bindings}
            if str(host_port) not in bound_ports:
                raise ExperimentError(
                    f"Persistent container {container} was created with host port(s) "
                    f"{sorted(bound_ports) or 'none'}, not {host_port}. Docker cannot "
                    "change a published port in place. Use the original port, or "
                    f"recreate only the container while preserving volume {volume}."
                )

        if info.get("State", {}).get("Running"):
            runner.say(f"Reusing existing running PostgreSQL container: {container}")
        else:
            runner.say(f"Starting existing PostgreSQL container: {container}")
            runner.command(["docker", "start", container])
        wait_until_ready()
        return volume, False

    if volume_exists:
        runner.say(
            f"Container {container} is missing, but volume {volume} exists. "
            "Recreating only the container and reattaching the existing database volume."
        )
    else:
        runner.say(
            f"No persistent PostgreSQL environment exists for SF{sf}. "
            "Creating it for the first time."
        )

    cmd = [
        "docker", "run", "-d", "--name", container,
        "--shm-size", "2g",
        "--env", "POSTGRES_DB=tpcds",
        "--env", f"POSTGRES_USER={PG_USER}",
        "--env", "POSTGRES_PASSWORD=tpcds",
        "--volume", f"{volume}:/var/lib/postgresql/data",
        "--mount", f"type=bind,source={benchmark_root},target=/benchmark-test,readonly",
    ]
    data_clean = ROOT / "data-clean"
    if data_clean.is_dir():
        cmd.extend(["--mount", f"type=bind,source={data_clean.resolve()},target=/data,readonly"])
    if host_port is not None:
        cmd.extend(["--publish", f"127.0.0.1:{host_port}:5432"])

    cmd.extend([POSTGRES_IMAGE, "postgres"])
    for setting in POSTGRES_SERVER_SETTINGS:
        name, value = setting.split("=", 1)
        cmd.extend(["-c", f"{name}={value}"])

    runner.say(f"Creating persistent PostgreSQL container for SF{sf}: {container}")
    runner.say(f"Persistent data volume: {volume}")
    try:
        runner.command(cmd)
    except Exception:
        runner.say(f"Container creation failed. Removing only partial container {container}.")
        subprocess.run(
            ["docker", "rm", "--force", container], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        # Preserve a volume that existed before this attempt: it may contain the DB.
        if not volume_exists:
            subprocess.run(
                ["docker", "volume", "rm", volume], cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        raise

    wait_until_ready()
    return volume, True


def verify_server_startup_settings(runner: Runner, output_dir: Path) -> None:
    """Fail immediately if PostgreSQL did not start with the required -c values."""
    checks = {
        "SERVER_SHARED_BUFFERS": ("shared_buffers", "4GB"),
        "SERVER_WORK_MEM": ("work_mem", "512MB"),
        "SERVER_HASH_MEM_MULTIPLIER": ("hash_mem_multiplier", "2"),
        "SERVER_PARALLEL_WORKERS": ("max_parallel_workers_per_gather", "4"),
        "SERVER_EFFECTIVE_CACHE": ("effective_cache_size", "10GB"),
        "SERVER_RANDOM_PAGE_COST": ("random_page_cost", "1.1"),
        "SERVER_JIT": ("jit", "off"),
        "SERVER_STATEMENT_TIMEOUT": ("statement_timeout", "0"),
    }
    sql = "\n".join(
        f"SELECT '{label}=' || current_setting('{setting}');"
        for label, (setting, _expected) in checks.items()
    )
    output = runner.psql("postgres", sql)
    (output_dir / "effective_server_settings.txt").write_text(
        output, encoding="utf-8"
    )
    for label, (_setting, expected) in checks.items():
        if not re.search(
            rf"(?m)^\s*{re.escape(label)}={re.escape(expected)}\s*$", output
        ):
            raise ExperimentError(
                f"PostgreSQL startup configuration was not applied: expected "
                f"{label}={expected}. Actual settings are in "
                "effective_server_settings.txt. The script will stop before "
                "generating/loading data."
            )
    runner.say(
        "Verified PostgreSQL startup configuration before data generation: "
        "shared_buffers=4GB, work_mem=512MB, effective_cache_size=10GB, "
        "max_parallel_workers_per_gather=4, random_page_cost=1.1, jit=off, "
        "statement_timeout=off."
    )


def start_tools_container(runner: Runner, sf: int, run_id: str,
                          benchmark_root: Path) -> str:
    """Build and start an isolated dsdgen container with the test folder mounted.

    This uses its own /benchmark-test bind mount and does not touch the regular
    benchmarks/ directory or the existing Compose tools container.
    """
    source_dir = ROOT / "DSGen-software-code-4.0.0"
    if not (source_dir / "tools").is_dir():
        raise ExperimentError(f"TPC-DS generator source is missing: {source_dir / 'tools'}")

    tools_container = f"tpcds-tools-test-sf{sf}-{run_id}"
    existing = subprocess.run(
        ["docker", "container", "inspect", tools_container], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if existing.returncode == 0:
        raise ExperimentError(
            f"Temporary generator container already exists: {tools_container}. "
            "Remove that stale helper container with docker rm -f before retrying."
        )


    with tempfile.TemporaryDirectory(prefix="tpcds-tools-build-") as temp_context:
        context = Path(temp_context)
        dockerfile_copy = context / "Dockerfile.tpcds"
        shutil.copy2(ROOT / "Dockerfile.tpcds", dockerfile_copy)
        runner.say(f"Building the dedicated TPC-DS tools image: {TOOLS_IMAGE}")
        runner.command([
            "docker", "build", "--tag", TOOLS_IMAGE,
            "--file", str(dockerfile_copy), str(context),
        ])

    runner.say(f"Starting temporary data-generator container: {tools_container}")
    runner.command([
        "docker", "run", "--detach", "--name", tools_container,
        "--mount", f"type=bind,source={source_dir.resolve()},target=/tpcds",
        "--mount", f"type=bind,source={benchmark_root.resolve()},target=/benchmark-test",
        "--workdir", "/tpcds/tools",
        TOOLS_IMAGE, "sleep", "infinity",
    ])
    ready = subprocess.run(
        ["docker", "exec", tools_container, "test", "-d", "/tpcds/tools"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )
    if ready.returncode != 0:
        subprocess.run(["docker", "rm", "--force", tools_container], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        raise ExperimentError(
            f"Tools container {tools_container!r} is not ready or the source "
            "is not mounted at /tpcds/tools."
        )
    return tools_container


def remove_tools_container(runner: Runner, tools_container: str) -> None:
    """Remove the temporary generator container; generated files are on the host."""
    result = subprocess.run(
        ["docker", "rm", "--force", tools_container], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    if result.returncode == 0:
        runner.say(f"Removed temporary generator container: {tools_container}")
    elif result.stderr.strip():
        runner.say(
            f"WARNING: Could not remove temporary generator container "
            f"{tools_container}: {result.stderr.strip()}"
        )


def ensure_data(
    runner: Runner,
    sf: int,
    data_dir: Path,
    *,
    run_id: str,
    benchmark_root: Path,
    force_regenerate: bool = False,
    require_existing: bool = False,
) -> bool:
    """Generate once, then reuse verified files for the future runs."""
    if not data_dir.is_dir():
        raise ExperimentError(
            f"Required data directory does not exist: {data_dir}. "
            "Create the benchmark-test folder structure before running this script."
        )
    manifest_path = data_dir / ".tpcds_generation_manifest.json"
    expected_names = {f"{table}.dat" for table in TABLES}

    # Reuse only files created by this workflow and verified against its manifest.
    if manifest_path.is_file() and not force_regenerate:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentError(
                f"Cannot read the TPC-DS data manifest: {manifest_path}. "
                "Inspect it or rerun with --regenerate-data."
            ) from exc
        if manifest.get("scale_factor") != sf:
            raise ExperimentError(
                f"The data manifest at {manifest_path} is for SF"
                f"{manifest.get('scale_factor')}, not SF{sf}."
            )
        recorded_files = manifest.get("files")
        if not isinstance(recorded_files, dict) or set(recorded_files) != expected_names:
            raise ExperimentError(
                f"The data manifest at {manifest_path} does not list exactly "
                "the 24 expected TPC-DS data files. Rerun with --regenerate-data."
            )
        actual_files = {
            name: (data_dir / name).stat().st_size
            for name in expected_names
            if (data_dir / name).is_file() and (data_dir / name).stat().st_size > 0
        }
        if actual_files != recorded_files:
            changed = sorted(
                name for name in expected_names
                if actual_files.get(name) != recorded_files.get(name)
            )
            raise ExperimentError(
                "The generated SF dataset is incomplete or changed: "
                f"{changed}. Rerun with --regenerate-data."
            )
        runner.say(
            f"Reusing the validated SF{sf} dataset generated on "
            f"{manifest.get('generated_utc', 'unknown date')}: {data_dir}"
        )
        runner.say("All 24 .dat files match the generation manifest; dsdgen will be skipped.")
        return False

    if require_existing:
        raise ExperimentError(
            f"The persistent SF{sf} database already exists, but its generated-data "
            f"manifest is missing or invalid in {data_dir}. The script will not "
            "generate replacement data because that would no longer match the "
            "existing database. Restore the original data/manifest or use "
            "--rebuild-database (and optionally --regenerate-data) deliberately."
        )

    existing_dat = sorted(data_dir.glob("*.dat"))
    if force_regenerate:
        runner.say(f"--regenerate-data specified: generating a fresh SF{sf} dataset.")
    elif existing_dat:
        runner.say(
            f"No generation manifest exists for SF{sf}; existing untracked .dat files "
            "in benchmark-test will be replaced after a fresh generation succeeds."
        )
    else:
        runner.say(
            f"The isolated SF{sf} data folder is empty and has no manifest; "
            "generating fresh TPC-DS data now."
        )

    staging_dir = Path(tempfile.mkdtemp(
        prefix=f".tpcds_sf{sf}_generation_", dir=str(data_dir.parent)
    ))
    tools_container: str | None = None
    try:
        tools_container = start_tools_container(runner, sf, run_id, benchmark_root)
        generator_dir = f"/benchmark-test/sf{sf}/{staging_dir.name}"
        generator_command = [
            "./dsdgen", "-SCALE", str(sf), "-DIR", generator_dir,
            "-TERMINATE", "N", "-FORCE", "-VERBOSE", "Y",
        ]

        result = subprocess.run(
            ["docker", "exec", "-w", "/tpcds/tools", tools_container,
             "sh", "-c", "test -x ./dsdgen"],
            cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            runner.say("No compiled dsdgen found; compiling with make OS=LINUX ...")
            runner.command([
                "docker", "exec", "-w", "/tpcds/tools", tools_container,
                "make", "OS=LINUX",
            ])
            result = subprocess.run(
                ["docker", "exec", "-w", "/tpcds/tools", tools_container,
                 "sh", "-c", "test -x ./dsdgen"],
                cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                raise ExperimentError("Generator build finished without a runnable ./dsdgen.")

        runner.say(
            f"Generating all 24 SF{sf} data files into staging directory "
            f"{staging_dir.name} under {data_dir.parent}."
        )
        runner.command([
            "docker", "exec", "-w", "/tpcds/tools", tools_container,
            *generator_command,
        ])

        missing = sorted(
            name for name in expected_names
            if not (staging_dir / name).is_file()
            or (staging_dir / name).stat().st_size == 0
        )
        if missing:
            raise ExperimentError(
                f"dsdgen finished but staged files are missing or empty: {missing}. "
                "The previous data files were not replaced."
            )

        # Replace the active dataset only after all 24 newly generated files validate.
        for name in sorted(expected_names):
            (staging_dir / name).replace(data_dir / name)

        manifest = {
            "manifest_version": 1,
            "scale_factor": sf,
            "generated_utc": utc_now(),
            "generator": "TPC-DS dsdgen from DSGen-software-code-4.0.0",
            "generator_command": generator_command,
            "files": {
                name: (data_dir / name).stat().st_size
                for name in sorted(expected_names)
            },
        }
        temp_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
        temp_manifest.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        temp_manifest.replace(manifest_path)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if tools_container is not None:
            remove_tools_container(runner, tools_container)

    runner.say(f"Successfully generated fresh SF{sf} data. Manifest: {manifest_path}")
    return True


def database_exists(runner: Runner, db: str) -> bool:
    output = runner.psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{db}';")
    return bool(re.search(r"(?m)^1$", output))


def create_database(runner: Runner, db: str) -> None:
    runner.psql("postgres", f'CREATE DATABASE "{db}";')


def drop_database(runner: Runner, db: str) -> None:
    """Drop only the experiment database; keep the persistent container and volume."""
    runner.psql("postgres", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);')


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def database_fingerprint(
    sf: int, db: str, profile: str, profile_files: list[Path], data_manifest: Path
) -> dict:
    profile_hashes = {path.name: sha256(path) for path in profile_files}
    return {
        "format_version": 1,
        "scale_factor": sf,
        "database": db,
        "index_profile": profile,
        "data_manifest_sha256": sha256(data_manifest),
        "schema_sql_sha256": sha256(SCHEMA_FILE),
        "index_profile_files_sha256": profile_hashes,
        "expected_clustered_indexes": EXPECTED_CLUSTERED,
        "postgres_server_settings": POSTGRES_SERVER_SETTINGS,
        "database_settings": SETTINGS,
    }

def read_database_metadata(runner: Runner, db: str) -> dict | None:
    relation = runner.psql(db, "SELECT to_regclass('experiment_meta.initialization');").strip()
    if not relation:
        return None
    output = runner.psql(
        db, "SELECT metadata::text FROM experiment_meta.initialization WHERE id = 1;"
    ).strip()
    if not output:
        return None
    try:
        metadata = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"Initialization metadata in {db} is not valid JSON.") from exc
    if not isinstance(metadata, dict):
        raise ExperimentError(f"Initialization metadata in {db} has an invalid format.")
    return metadata


def write_database_metadata(runner: Runner, db: str, metadata: dict) -> None:
    payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    sql = (
        "CREATE SCHEMA IF NOT EXISTS experiment_meta;\n"
        "CREATE TABLE IF NOT EXISTS experiment_meta.initialization ("
        "id integer PRIMARY KEY CHECK (id = 1), metadata jsonb NOT NULL);\n"
        "INSERT INTO experiment_meta.initialization (id, metadata) VALUES "
        f"(1, {sql_literal(payload)}::jsonb);"
    )
    runner.psql(db, sql)


def validate_database_metadata(metadata: dict, expected: dict, db: str) -> dict[str, int]:
    mismatches = [key for key, value in expected.items() if metadata.get(key) != value]
    if mismatches:
        raise ExperimentError(
            f"Persistent database {db} was initialized with different settings or inputs: "
            f"{mismatches}. Use --rebuild-database only if you intentionally want to "
            "recreate its schema, data, and indexes."
        )
    row_counts = metadata.get("row_counts")
    if not isinstance(row_counts, dict) or set(row_counts) != TABLES:
        raise ExperimentError(
            f"Persistent database {db} has incomplete saved row-count metadata. "
            "Use --rebuild-database to recreate it."
        )
    try:
        parsed = {str(k): int(v) for k, v in row_counts.items()}
    except (TypeError, ValueError) as exc:
        raise ExperimentError(f"Invalid row-count metadata in {db}.") from exc
    if any(value < 0 for value in parsed.values()):
        raise ExperimentError(f"Negative row count recorded in {db}.")
    return parsed


def write_row_counts_csv(output_dir: Path, row_counts: dict[str, int]) -> None:
    with (output_dir / "loaded_row_counts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "loaded_rows"])
        writer.writerows(sorted(row_counts.items()))


def load_data(runner: Runner, db: str, sf: int, output_dir: Path) -> dict[str, int]:
    table_output = runner.psql(db,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
    schema_tables = set(line.strip() for line in table_output.splitlines() if line.strip() in TABLES)
    if schema_tables != TABLES:
        raise ExperimentError(
            "Schema does not contain the expected 24 TPC-DS tables; missing: "
            + repr(sorted(TABLES - schema_tables))
        )

    counts: dict[str, int] = {}
    for i, table in enumerate(sorted(TABLES), start=1):
        runner.say(f"Loading {i}/24: {table}")
        # The isolated PostgreSQL container mounts benchmark-test read-only at /benchmark-test.
        # Table names are from the fixed, trusted TABLES constant.
        output = runner.psql(
            db,
            f"COPY public.\"{table}\" FROM '/benchmark-test/sf{sf}/data/{table}.dat' "
            "WITH (FORMAT csv, DELIMITER '|', NULL '');",
        )
        match = re.search(r"(?m)^COPY (\d+)\s*$", output)
        if not match:
            raise ExperimentError(f"Cannot verify loaded row count for table {table}")
        counts[table] = int(match.group(1))

    write_row_counts_csv(output_dir, counts)
    runner.say(f"Loaded all {len(counts)} tables; row counts saved.")
    return counts


def apply_index_profile(runner: Runner, db: str) -> list[Path]:
    """Run the supplied 8-index SQL file, then the supplied 4-table CLUSTER file."""
    index_file = ROOT / "indexes_clustered_8.sql"
    cluster_file = ROOT / "cluster_four_tables.sql"

    runner.say("Creating exactly 8 custom indexes from indexes_clustered_8.sql ...")
    runner.sql_file(db, index_file)

    runner.say("Physically clustering exactly 4 tables using cluster_four_tables.sql ...")
    runner.sql_file(db, cluster_file)

    runner.say("Updating PostgreSQL query planner statistics ...")
    runner.psql(db, "ANALYZE;")
    return [index_file, cluster_file]

def verify_indexes(runner: Runner, db: str, output_dir: Path) -> None:
    sql = (
        "SELECT tbl.relname, idx.relname, pi.indisprimary, pi.indisclustered "
        "FROM pg_index AS pi "
        "JOIN pg_class AS idx ON idx.oid = pi.indexrelid "
        "JOIN pg_class AS tbl ON tbl.oid = pi.indrelid "
        "JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace "
        "WHERE ns.nspname = 'public' "
        "ORDER BY tbl.relname, idx.relname;"
    )
    output = runner.psql(db, sql)
    clustered: dict[str, str] = {}
    rows: list[list[str]] = []
    for line in output.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4:
            continue
        table, index, primary, clustered_flag = parts
        rows.append(parts)
        if clustered_flag == "t":
            clustered[table] = index

    with (output_dir / "index_inventory.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "index", "is_primary", "is_clustered"])
        writer.writerows(rows)

    if clustered != EXPECTED_CLUSTERED:
        raise ExperimentError(
            f"Clustering validation failed. Expected {EXPECTED_CLUSTERED}, "
            f"got {clustered}. Inspect index_inventory.csv and the two supplied SQL files."
        )

    expected_custom = {
        "idx_store_sales_ss_customer_sk",
        "idx_ss_date_item",
        "idx_web_sales_ws_bill_customer_sk",
        "idx_ws_date_item",
        "idx_catalog_sales_cs_sold_date_sk",
        "idx_cs_date_customer",
        "idx_cs_date_item",
        "idx_catalog_returns_cr_returned_date_sk",
    }
    observed_custom = {index for _, index, _, _ in rows if index.startswith("idx_")}
    if observed_custom != expected_custom:
        raise ExperimentError(
            f"Index inventory mismatch. Expected exactly 8 custom indexes, "
            f"found {len(observed_custom)}. "
            f"Missing: {sorted(expected_custom - observed_custom)}; "
            f"extra: {sorted(observed_custom - expected_custom)}."
        )

    runner.say(
        f"Verified exactly {len(observed_custom)} custom indexes, "
        f"4 clustered tables, and {len(rows)} total indexes."
    )

def set_database_defaults(runner: Runner, db: str) -> None:
    """Persist benchmark defaults on the actual experiment database.

    These ALTER DATABASE settings are loaded automatically by every new
    connection to this database. The benchmark runner also passes explicit
    --set options per query, so both ordinary connections and timed query
    sessions use the requested values.
    """
    statements = []
    for assignment in SETTINGS:
        name, value = assignment.split("=", 1)
        statements.append(f"ALTER DATABASE \"{db}\" SET {name} TO '{value}';")
    runner.psql("postgres", "\n".join(statements))
    runner.say(
        f"Applied database-level defaults to {db}: "
        + ", ".join(SETTINGS)
        + ". statement_timeout remains off (PostgreSQL default)."
    )


def effective_settings(runner: Runner, db: str, output_dir: Path) -> None:
    """Verify startup defaults, target-database defaults, and query-session SETs."""
    server_checks = {
        "SERVER_SHARED_BUFFERS": ("shared_buffers", "4GB"),
        "SERVER_WORK_MEM": ("work_mem", "512MB"),
        "SERVER_HASH_MEM_MULTIPLIER": ("hash_mem_multiplier", "2"),
        "SERVER_PARALLEL_WORKERS": ("max_parallel_workers_per_gather", "4"),
        "SERVER_EFFECTIVE_CACHE": ("effective_cache_size", "10GB"),
        "SERVER_RANDOM_PAGE_COST": ("random_page_cost", "1.1"),
        "SERVER_JIT": ("jit", "off"),
        "SERVER_STATEMENT_TIMEOUT": ("statement_timeout", "0"),
    }
    server_sql = "\n".join(
        f"SELECT '{label}=' || current_setting('{setting}');"
        for label, (setting, _expected) in server_checks.items()
    )
    server_output = runner.psql("postgres", server_sql)
    (output_dir / "effective_server_settings.txt").write_text(
        server_output, encoding="utf-8"
    )
    for label, (_setting, expected_value) in server_checks.items():
        if not re.search(
            rf"(?m)^\s*{re.escape(label)}={re.escape(expected_value)}\s*$",
            server_output,
        ):
            raise ExperimentError(
                f"Expected PostgreSQL server startup setting {label}={expected_value}. "
                "The container was not started with the requested -c settings. "
                "Inspect effective_server_settings.txt and workflow.log."
            )

    # Verify defaults actually stored on the newly created experiment database.
    database_checks = {
        "DATABASE_WORK_MEM": ("work_mem", "512MB"),
        "DATABASE_HASH_MEM_MULTIPLIER": ("hash_mem_multiplier", "2"),
        "DATABASE_PARALLEL_WORKERS": ("max_parallel_workers_per_gather", "4"),
        "DATABASE_EFFECTIVE_CACHE": ("effective_cache_size", "10GB"),
        "DATABASE_RANDOM_PAGE_COST": ("random_page_cost", "1.1"),
        "DATABASE_JIT": ("jit", "off"),
    }
    database_sql = "\n".join(
        f"SELECT '{label}=' || current_setting('{setting}');"
        for label, (setting, _expected) in database_checks.items()
    ) + "\nSELECT 'DATABASE_STATEMENT_TIMEOUT_MS=' || setting " \
        "FROM pg_settings WHERE name = 'statement_timeout';"
    database_output = runner.psql(db, database_sql)
    (output_dir / "effective_database_settings.txt").write_text(
        database_output, encoding="utf-8"
    )
    for label, (_setting, expected_value) in database_checks.items():
        if not re.search(
            rf"(?m)^\s*{re.escape(label)}={re.escape(expected_value)}\s*$",
            database_output,
        ):
            raise ExperimentError(
                f"Expected target-database default {label}={expected_value}. "
                "The ALTER DATABASE settings did not take effect. "
                "Inspect effective_database_settings.txt."
            )
    if not re.search(
        rf"(?m)^\s*DATABASE_STATEMENT_TIMEOUT_MS={STATEMENT_TIMEOUT_MS}\s*$",
        database_output,
    ):
        raise ExperimentError(
            "The target database did not inherit statement_timeout=0 (off). "
            "Inspect effective_database_settings.txt."
        )

    # Finally, explicitly SET the same values in a fresh session. This mirrors
    # what 2_run_tpcds_benchmark.py sends before every measured query.
    prefix = "\n".join(
        f"SET {name} = '{value}';"
        for name, value in (item.split("=", 1) for item in SETTINGS)
    )
    verification_source = (ROOT / "verify_load_configuration.sql").read_text(
        encoding="utf-8"
    )
    assert_sql = "\n".join([
        "SELECT 'ASSERT_WORK_MEM=' || current_setting('work_mem');",
        "SELECT 'ASSERT_HASH_MULTIPLIER=' || current_setting('hash_mem_multiplier');",
        "SELECT 'ASSERT_PARALLEL_WORKERS=' || current_setting('max_parallel_workers_per_gather');",
        "SELECT 'ASSERT_EFFECTIVE_CACHE=' || current_setting('effective_cache_size');",
        "SELECT 'ASSERT_RANDOM_PAGE_COST=' || current_setting('random_page_cost');",
        "SELECT 'ASSERT_JIT=' || current_setting('jit');",
        "SELECT 'ASSERT_STATEMENT_TIMEOUT_MS=' || setting FROM pg_settings WHERE name = 'statement_timeout';",
    ])
    executed = output_dir / "effective_settings_check.sql"
    executed.write_text(
        prefix + "\n" + verification_source + "\n" + assert_sql + "\n",
        encoding="utf-8",
    )
    observed = runner.sql_file(db, executed)
    (output_dir / "effective_session_settings.txt").write_text(
        observed, encoding="utf-8"
    )
    expected = {
        "ASSERT_WORK_MEM": "512MB",
        "ASSERT_HASH_MULTIPLIER": "2",
        "ASSERT_PARALLEL_WORKERS": "4",
        "ASSERT_EFFECTIVE_CACHE": "10GB",
        "ASSERT_RANDOM_PAGE_COST": "1.1",
        "ASSERT_JIT": "off",
        "ASSERT_STATEMENT_TIMEOUT_MS": str(STATEMENT_TIMEOUT_MS),
    }
    for name, value in expected.items():
        if not re.search(rf"(?m)^\s*{re.escape(name)}={re.escape(value)}\s*$", observed):
            raise ExperimentError(
                f"Expected benchmark-session setting {name}={value}. "
                "Inspect effective_session_settings.txt."
            )
    runner.say(
        "Verified PostgreSQL startup settings, target-database defaults, "
        "benchmark-session settings, and statement_timeout=off."
    )


def benchmark(runner: Runner, sf: int, db: str, input_dir: Path, out: Path,
              runs: int, selection: str) -> tuple[dict[str, int], float]:
    cmd = [
        sys.executable, str(RUNNER),
        "-i", str(input_dir), "-o", str(out), "-d", db,
        "-q", ",".join(str(q) for q in sorted(query_selection(selection))),
        "-n", str(runs),
    ]
    if STATEMENT_TIMEOUT_MS:
        cmd.extend(["--statement-timeout-ms", str(STATEMENT_TIMEOUT_MS)])
    for setting in SETTINGS:
        cmd.extend(["--set", setting])
    cmd.extend(["--no-save-results", "--order", "suite", "--container", runner.pg_container])
    runner.say("Starting original benchmark runner (unchanged) ...")
    runner.command(cmd, extra_log=out / "benchmark.log")

    csv_path = out / "exec_time_details.csv"
    summary_path = out / "benchmark_summary.txt"
    if not csv_path.is_file() or not summary_path.is_file():
        raise ExperimentError("Benchmark runner finished without producing CSV and summary files.")
    with csv_path.open(newline="", encoding="utf-8") as infile:
        rows = list(csv.DictReader(infile))
    selection_size = len(query_selection(selection))
    if len(rows) != selection_size:
        raise ExperimentError(f"Expected {selection_size} query rows; found {len(rows)}")
    status_counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    total_seconds = sum(float(row["avg_exec_time"] or 0) for row in rows)
    report = (
        f"Scale factor: SF{sf}\nDatabase: {db}\n"
        f"Results: {out}\nRuns per query: {runs}\n"
        f"Queries requested: {selection_size}\n"
        f"Query status counts: {status_counts}\n"
        f"Sum of average query execution times (s): {total_seconds:.3f}\n"
    )
    (out / "verification_summary.txt").write_text(report, encoding="utf-8")
    runner.say("\n" + report)
    if status_counts != {"SUCCESS": selection_size}:
        raise ExperimentError(
            "At least one query did not succeed in all runs. "
            "Inspect exec_time_details.csv, benchmark.log and verification_summary.txt."
        )
    return status_counts, total_seconds


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create one persistent PostgreSQL database per scale factor. The first "
            "run initializes data, schema, indexes, and clustering; later runs reuse "
            "that same database and only execute the selected benchmark queries."
        )
    )
    parser.add_argument("--sf", type=int, required=True, help="Scale factor, e.g. 1, 2, 5, 10")
    parser.add_argument("--runs", type=int, default=3, help="Benchmark suite iterations (default: 3)")
    parser.add_argument("--queries", default="1-99", help="Query selection (default: 1-99)")
    parser.add_argument("--run-id", help="Unique label for this result folder (letters/numbers/underscore)")
    parser.add_argument(
        "--benchmark-root", default="benchmark-test",
        help="Pre-created test-only data/query/results root relative to the repository (default: benchmark-test)",
    )
    parser.add_argument(
        "--postgres-port", type=int, metavar="PORT", default=None,
        help="Optional localhost port for pgAdmin. Choose it on the first run for an SF and reuse that port.",
    )
    parser.add_argument(
        "--keep-container-running", action="store_true",
        help="Leave the persistent PostgreSQL container running after the benchmark; default is to stop it but preserve the DB.",
    )
    parser.add_argument(
        "--regenerate-data", action="store_true",
        help="Regenerate the 24 .dat files. If the database exists, --rebuild-database is also required.",
    )
    parser.add_argument(
        "--rebuild-database", action="store_true",
        help="Explicitly drop/recreate the persistent database and indexes for this SF. The Docker container and volume are preserved.",
    )
    args = parser.parse_args()
    if args.sf <= 0 or args.runs <= 0:
        parser.error("--sf and --runs must be positive")
    if args.postgres_port is not None and not (1 <= args.postgres_port <= 65535):
        parser.error("--postgres-port must be between 1 and 65535")

    runner: Runner | None = None
    pg_container: str | None = None
    container_should_stop = False
    database_created_this_run = False
    database_initialized = False
    db = ""

    try:
        selection = query_selection(args.queries)
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,30}", run_id):
            raise ExperimentError("--run-id must be 1-30 letters, digits, or underscores")
        run_id = run_id.lower()

        benchmark_root_arg = Path(args.benchmark_root)
        if benchmark_root_arg.is_absolute():
            raise ExperimentError("--benchmark-root must be a relative path inside the repository.")
        benchmark_root = (ROOT / benchmark_root_arg).resolve()
        try:
            benchmark_root.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ExperimentError("--benchmark-root must stay inside the repository root.") from exc
        if benchmark_root == ROOT.resolve():
            raise ExperimentError("--benchmark-root cannot be the repository root itself.")

        sf_dir = benchmark_root / f"sf{args.sf}"
        (sf_dir / "data").mkdir(parents=True, exist_ok=True)
        required_dirs = {
            "scale-factor directory": sf_dir,
            "data directory": sf_dir / "data",
            "reference queries directory": sf_dir / "queries",
            "optimized queries directory": sf_dir / "optimized_queries",
            "results parent directory": sf_dir / "results",
        }
        missing_dirs = [f"{description}: {path}" for description, path in required_dirs.items() if not path.is_dir()]
        if missing_dirs:
            raise ExperimentError(
                "The required benchmark-test folder structure is incomplete. "
                "Create these folders yourself before running the script:\n- "
                + "\n- ".join(missing_dirs)
            )

        input_dir, query_files, profile_files = require_inputs(
            args.sf, selection, sf_dir
        )

        # run-id is only for the output folder. The DB/container/volume are stable per SF.
        db = check_name(f"tpcds_sf{args.sf}_test", "database name")
        pg_container = f"tpcds-pg-sf{args.sf}"
        pg_volume = f"tpcds_pg_sf{args.sf}"
        output_dir = sf_dir / "results" / run_id
        if output_dir.exists():
            raise ExperimentError(f"Results directory already exists: {output_dir}. Choose a new --run-id.")

        runner = Runner(output_dir, postgres_container=pg_container)
        runner.say(f"Starting SF{args.sf} benchmark run against persistent database {db}")
        runner.say(f"Results folder: {output_dir}")
        runner.say(f"Data directory: {sf_dir / 'data'}")
        runner.say(f"Reference queries folder (not executed): {sf_dir / 'queries'}")
        runner.say(f"Optimized query input: {input_dir}")
        runner.say(f"Persistent container: {pg_container}; persistent volume: {pg_volume}")
        runner.say("Index setup: exactly 8 custom indexes + 4 clustered tables (the supplied SQL files)")

        used_files = [ROOT / "Dockerfile.tpcds", ROOT / "verify_load_configuration.sql",
                      SCHEMA_FILE, RUNNER, Path(__file__).resolve()]
        used_files.extend(query_files[n] for n in sorted(selection))
        used_files.extend(profile_files)
        config = {
            "started_utc": utc_now(), "sf": args.sf, "database": db,
            "postgres_container": pg_container, "postgres_volume": pg_volume,
            "postgres_image": POSTGRES_IMAGE, "postgres_shm_size": "2g",
            "postgres_host_port_requested": args.postgres_port,
            "benchmark_root": str(benchmark_root.relative_to(ROOT)),
            "data_directory": str((sf_dir / "data").relative_to(ROOT)),
            "data_generation_manifest": str((sf_dir / "data" / ".tpcds_generation_manifest.json").relative_to(ROOT)),
            "regenerate_data_requested": args.regenerate_data,
            "rebuild_database_requested": args.rebuild_database,
            "runs": args.runs, "query_selection": args.queries,
            "optimized_queries": str(input_dir.relative_to(ROOT)),
            "index_profile": "clustered4-files",
            "index_setup_description": "8 custom indexes from indexes_clustered_8.sql; 4 clustered tables from cluster_four_tables.sql",
            "session_settings": SETTINGS,
            "postgres_database_settings": SETTINGS,
            "postgres_server_settings": POSTGRES_SERVER_SETTINGS,
            "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "statement_timeout": "off", "query_order": "suite",
            "explain_analyze": False, "save_query_results": False,
            "input_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in used_files},
        }
        config_path = output_dir / "experiment_config.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        actual_volume, container_created = ensure_persistent_postgres(
            runner, args.sf, args.postgres_port, benchmark_root
        )
        container_should_stop = True
        if actual_volume != pg_volume:
            raise ExperimentError("Unexpected PostgreSQL data volume returned.")
        verify_server_startup_settings(runner, output_dir)

        db_exists_before = database_exists(runner, db)
        if db_exists_before and args.regenerate_data and not args.rebuild_database:
            raise ExperimentError(
                "The persistent database already exists. --regenerate-data would make "
                "the host .dat files differ from the rows already loaded in PostgreSQL. "
                "Use --rebuild-database --regenerate-data together only if you intend "
                "to replace both the database and its data."
            )

        if db_exists_before and args.rebuild_database:
            runner.say(
                f"--rebuild-database specified: dropping only database {db}. "
                f"Container {pg_container} and volume {pg_volume} are preserved."
            )
            drop_database(runner, db)
            db_exists_before = False

        data_manifest = sf_dir / "data" / ".tpcds_generation_manifest.json"
        generated = ensure_data(
            runner, args.sf, sf_dir / "data",
            run_id=run_id, benchmark_root=benchmark_root,
            force_regenerate=args.regenerate_data,
            require_existing=db_exists_before,
        )
        config["generated_data_this_run"] = generated
        config["reused_existing_data"] = not generated
        config["postgres_container_created_this_run"] = container_created

        fingerprint = database_fingerprint(
            args.sf, db, "clustered4-files", profile_files, data_manifest
        )

        if db_exists_before:
            runner.say(
                f"Existing database {db} found. Reusing loaded data and indexes; "
                "skipping CREATE DATABASE, schema creation, COPY, CREATE INDEX, CLUSTER, and ANALYZE."
            )
            metadata = read_database_metadata(runner, db)
            if metadata is None:
                raise ExperimentError(
                    f"Database {db} exists but has no initialization metadata. It may be "
                    "from an older script or an interrupted setup. Use --rebuild-database "
                    "if you intentionally want to initialize it again."
                )
            row_counts = validate_database_metadata(metadata, fingerprint, db)
            table_output = runner.psql(
                db,
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;",
            )
            schema_tables = {line.strip() for line in table_output.splitlines() if line.strip() in TABLES}
            if schema_tables != TABLES:
                raise ExperimentError(
                    f"Persistent database {db} has an incomplete TPC-DS schema. "
                    f"Missing tables: {sorted(TABLES - schema_tables)}. Use --rebuild-database."
                )
            write_row_counts_csv(output_dir, row_counts)
            verify_indexes(runner, db, output_dir)
            effective_settings(runner, db, output_dir)
            database_initialized = True
            config["database_setup_action"] = "reused_existing_database"
            config["database_initialized_utc"] = metadata.get("initialized_utc")
        else:
            runner.say(
                f"First initialization for SF{args.sf}: creating database {db}, "
                "loading data, running indexes_clustered_8.sql (8 indexes), "
                "then cluster_four_tables.sql (4 clustered tables)."
            )
            create_database(runner, db)
            database_created_this_run = True
            set_database_defaults(runner, db)
            runner.sql_file(db, SCHEMA_FILE)
            row_counts = load_data(runner, db, args.sf, output_dir)
            apply_index_profile(runner, db)
            verify_indexes(runner, db, output_dir)
            effective_settings(runner, db, output_dir)

            metadata = dict(fingerprint)
            metadata["row_counts"] = row_counts
            metadata["initialized_utc"] = utc_now()
            metadata["postgres_version"] = runner.psql(db, "SHOW server_version;").strip()
            write_database_metadata(runner, db, metadata)
            database_initialized = True
            config["database_setup_action"] = "created_and_initialized"
            config["database_initialized_utc"] = metadata["initialized_utc"]

        config["database_reused"] = config["database_setup_action"] == "reused_existing_database"
        config["finished_preparation_utc"] = utc_now()
        config["postgres_version"] = runner.psql(db, "SHOW server_version;").strip()
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        benchmark(runner, args.sf, db, input_dir, output_dir, args.runs, args.queries)
        runner.say(f"SUCCESS. Results saved under: {output_dir}")
        runner.say(f"Persistent database: {db}")
        runner.say(f"Persistent container: {pg_container}; volume: {pg_volume}")
        if args.keep_container_running:
            runner.say("Container left running because --keep-container-running was specified.")
        else:
            runner.say("Container will be stopped automatically; its database and volume are preserved.")
        runner.say("Use a new --run-id for each separate results folder; the database name stays the same for this SF.")
        return 0

    except (ExperimentError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print(
            "\nInterrupted. The persistent PostgreSQL container will be stopped automatically; "
            "its database volume and generated files are preserved.",
            file=sys.stderr, flush=True,
        )
        return 130
    finally:
        if database_created_this_run and not database_initialized and runner is not None and container_should_stop:
            try:
                runner.say(f"Initialization did not complete; dropping partial database {db}.")
                drop_database(runner, db)
            except Exception as cleanup_error:
                runner.say(f"WARNING: Could not remove partial database {db}: {cleanup_error}")

        if container_should_stop and pg_container and not args.keep_container_running:
            stop_result = subprocess.run(
                ["docker", "stop", pg_container],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            if stop_result.returncode == 0:
                message = (
                    f"Automatically stopped persistent PostgreSQL container {pg_container}. "
                    "Its database and Docker volume are preserved."
                )
                if runner is not None:
                    runner.say(message)
                else:
                    print(message, flush=True)
            elif stop_result.returncode != 0:
                message = (
                    f"WARNING: Could not automatically stop {pg_container}: "
                    f"{stop_result.stderr.strip() or stop_result.stdout.strip()}"
                )
                if runner is not None:
                    runner.say(message)
                else:
                    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
