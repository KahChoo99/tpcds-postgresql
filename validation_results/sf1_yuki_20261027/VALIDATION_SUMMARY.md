# SF1 correctness validation: Q11, Q30 and Q74

Date: 2026-10-27  
Git branch/commit: `staging` / `8aa15ee`  
Database: local `tpcds` database in `tpcds-postgres` (SF1)  
PostgreSQL: 16.15  
Session setting: `work_mem=256MB`

## Scope and version identification

The baseline files are the SF1 queries in `benchmarks/sf1/queries`. Their
contents are byte-for-byte identical to Negar's files in
`project419/1025/queries` for Q4, Q11, Q30 and Q74.

The executed optimized files were:

- `optimized_queries/query_4_optimized.sql` (`fb071ae9c3d01b6acba294d59ece060e237368ca`)
- `optimized_queries/query_11_optimized.sql` (`b81943f2d87e95a67b37a348b780e9db7235fd30`)
- `optimized_queries/query_30_optimized.sql` (`8839eff9273f14a8717ef6a4bc8a6e714dc0bca4`)
- `optimized_queries/query_74_optimized.sql` (`776dc5b313275d35f6e97663226dc1437426d604`)

The executed Q11, Q30, and Q74 files are byte-for-byte identical to the
team-selected files under `benchmarks/sf1/optimized_queries/`. The executed Q4
file is Yuki's earlier candidate. It is different from the team-selected Hung
version at `benchmarks/sf1/optimized_queries/query_4.sql`
(`0f4fdd805c95b5b63c288422f8214c093f68780f`). Consequently, the Q4 result in
this validation run must not be presented as validation of the final team Q4.

Each original and optimized query was executed once on the same database. The
saved outputs were compared with Hung's `3_compare_result.py` in both its
default normalization mode and its `--strict` mode. A separate byte-level
`cmp` check was also performed on every output pair.

## Team-selected query results

| Query | Original rows | Optimized rows | Default comparison | Strict comparison | Byte-level comparison |
|---|---:|---:|---|---|---|
| Q11 | 84 | 84 | Exact | Exact | Identical |
| Q30 | 100 | 100 | Exact | Exact | Identical |
| Q74 | 83 | 83 | Exact | Exact | Identical |

Q11, Q30, and Q74 therefore pass the SF1 serialized-output correctness check
for the current generated parameters and local dataset.

## Separate Q4 candidate result

Yuki's Q4 candidate produced four rows and matched the saved original Q4 output
in the default, strict, and byte-level comparisons. This is useful evidence for
the earlier candidate only. The selected Hung Q4 remains to be validated.

## Evidence

- `comparison_report.csv`: default comparison for all four executed candidates.
- `comparison_report_strict.csv`: strict comparison for all four executed candidates.
- `baseline/results/`: saved original outputs.
- `optimized/results/`: saved optimized outputs; `Q04.txt` belongs to Yuki's
  candidate, while `Q11.txt`, `Q30.txt`, and `Q74.txt` belong to the
  team-selected versions.
- `team_package/`: concise evidence index and role-separated CSV summaries.

The execution-time fields in the original CSV reports are diagnostic only. They
come from one local run with uncontrolled cache state; the original queries ran
before the optimized queries, and `catalog_sales` was reported as not analyzed.
They must not be used as final performance results.

## Limits of the conclusion

This result establishes equality of the saved serialized outputs only for SF1
and these exact generated SQL parameters. It does not by itself prove
equivalence for SF2, SF5, SF10, other `dsqgen` substitutions, or an official
qualification `.ans` dataset. A database-level bidirectional `EXCEPT ALL` check
was started but did not complete and produced no result artifact; it is not
claimed as completed evidence. The selected Hung Q4 also remains unvalidated by
this run. Final performance claims require repeated measurements on the team's
reference machine under a controlled index, statistics, and cache protocol.
