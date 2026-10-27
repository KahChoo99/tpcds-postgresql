# SF1 correctness-validation evidence package

This directory is a compact index for sharing the completed SF1 validation with
the team. Raw query outputs remain in their original parent directories so that
the package does not duplicate evidence.

## Validated team-selected versions

Q11, Q30, and Q74 were executed from `optimized_queries/`. Their SHA-1 hashes
match the corresponding files in `benchmarks/sf1/optimized_queries/`. Each query
matched its original SF1 output under Hung's normal comparison, Hung's `--strict`
comparison, and a byte-level file comparison.

The role-filtered result is recorded in
[`comparison_report_team_validated.csv`](comparison_report_team_validated.csv).

## Q4 status

The executed Q4 was Yuki's earlier candidate
`optimized_queries/query_4_optimized.sql`, not the team-selected Hung version
`benchmarks/sf1/optimized_queries/query_4.sql`. The candidate matched the original
output, but this does not validate the final team Q4. Its result is kept separate
in [`comparison_report_q4_yuki_candidate.csv`](comparison_report_q4_yuki_candidate.csv).

## Source evidence

- [Corrected validation summary](../VALIDATION_SUMMARY.md)
- [Original normal comparison report](../comparison_report.csv)
- [Original strict comparison report](../comparison_report_strict.csv)
- [Original Q11 output](../baseline/results/Q11.txt) and
  [optimized Q11 output](../optimized/results/Q11.txt)
- [Original Q30 output](../baseline/results/Q30.txt) and
  [optimized Q30 output](../optimized/results/Q30.txt)
- [Original Q74 output](../baseline/results/Q74.txt) and
  [optimized Q74 output](../optimized/results/Q74.txt)
- [Original Q4 output](../baseline/results/Q04.txt) and
  [Yuki-candidate Q4 output](../optimized/results/Q04.txt)

## Interpretation limits

The evidence covers SF1 and the exact generated query parameters used in this
run. It does not cover the selected Hung Q4, other scale factors, other `dsqgen`
substitutions, or official qualification answer files. The database-level
bidirectional `EXCEPT ALL` check did not complete. Recorded runtimes are single-run
diagnostics and are not final performance measurements.
