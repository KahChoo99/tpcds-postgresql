# Optimized TPC-DS Queries Across Scale Factors

## Purpose and scope

This document explains the SQL rewrites for SF1 and their adaptations to SF2, SF5, and SF10. It covers the original query structure, the implemented changes, the parameters that differ between scale factors, and the validation completed so far.

The selected query IDs are **1, 4, 6, 11, 14, 16, 17, 25, 29, 30, 74, 75, 81, and 95**. The first batch covered ten queries; the second added **Q17, Q25, Q29, and Q75**. Each SF2/SF5/SF10 `optimized_queries` directory now contains exactly these fourteen SQL files. No original or unrelated queries were copied into those directories.

| Scale factor | Original SQL | Optimized SQL | Role |
|---|---|---|---|
| SF1 | [sf1/queries](sf1/queries/) | [sf1/optimized_queries](sf1/optimized_queries/) and [sf1/queries_optimized](sf1/queries_optimized/) | The first directory is the historical reference. The four second-batch rewrites and the latest Q14 are in `queries_optimized`. |
| SF2 | [sf2/queries](sf2/queries/) | [sf2/optimized_queries](sf2/optimized_queries/) | Fourteen adapted queries. |
| SF5 | [sf5/queries](sf5/queries/) | [sf5/optimized_queries](sf5/optimized_queries/) | Fourteen adapted queries. |
| SF10 | [sf10/queries](sf10/queries/) | [sf10/optimized_queries](sf10/optimized_queries/) | Fourteen adapted queries. |

There are **42 adapted files and 45 SQL statements** across SF2, SF5, and SF10. Query 14 contains two statements in every scale factor; each of the other selected files contains one. The second batch adds four SF1 implementations and twelve higher-SF files.

Each adaptation uses its own scale factor's original query as the semantic reference. A scale factor can change the generated SQL as well as the data volume: Q11 changes an output column; Q25, Q29, and Q74 change aggregate functions; Q74 also changes ordering; and Q16 changes its set of counties. Copying SF1 SQL without checking those differences would change the requested results.

The original query files and the existing SF1 optimized files were left unchanged. Q30 in the new scale factors includes a correction to the SF1 rewrite's early NULL-customer filter, described below.

## Rewrite overview

| Query | Original structure | Implemented rewrite |
|---|---|---|
| Q1 | Customer/store return totals with a correlated store-average lookup. | Filter stores early, calculate one average per store, and join it to the customer totals. |
| Q4 | Three channels combined into annual totals and referenced through six aliases. | Calculate both years in one aggregate per channel, then join three channel summaries. |
| Q6 | Correlated average item price for each item's category. | Calculate category averages once as a grouped relation and join by category. |
| Q11 | Store/web annual totals combined and referenced through four aliases. | Calculate two annual sums with `FILTER` per channel and join customer details afterward. |
| Q14 | Repeated three-year sales processing; separate weekly aggregates in Part 2. | Reuse materialized item summaries, calculate a weighted global average, materialize the two target weeks' date keys, and combine weekly aggregates with `FILTER`. |
| Q16 | Implicit joins, repeated county literals, and existence subqueries. | Use explicit joins and typed dates, deduplicate county values, and retain `EXISTS` / `NOT EXISTS`. |
| Q17 | Quantity statistics over a three-fact join. | Materialize narrow store/return matches, filter catalog input by candidate keys, and retain native statistics over the original joined multiset. |
| Q25 | Profit/loss aggregates over a three-fact join. | Aggregate catalog profit by candidate customer/item pair, using multiplicity-aware formulas when the SF requests AVG or SUM. |
| Q29 | Quantity aggregates over store sales, returns, and three years of catalog sales. | Reuse narrow store/return matches and filter catalog input without removing aggregate-input duplicates. |
| Q30 | Correlated average of customer return totals by return-address state. | Calculate the state average with a window function while preserving the NULL-customer group. |
| Q74 | Store/web annual aggregates referenced through four aliases. | Calculate both annual aggregates with `FILTER`, preserving each SF's aggregate function, then join customer details afterward. |
| Q75 | Distinct net-sale details from three channels, followed by an annual self-join. | Filter years and category early, preserve the seven-column `UNION`, and compare annual sums with `FILTER`. |
| Q81 | Correlated state-average lookup over customer catalog-return totals. | Calculate the state average directly over the grouped totals with a window function. |
| Q95 | Warehouse-pair self-join over web sales and repeated order-membership checks. | Filter candidate sales first and identify multi-warehouse orders with `COUNT(DISTINCT ...)`. |

These changes aim to reduce repeated aggregation, repeated correlated lookups, or the amount of intermediate data. They do not by themselves establish a measured speedup. PostgreSQL chooses the physical execution plan; explicit `JOIN` syntax and `SELECT 1` inside `EXISTS` are primarily clarity changes. The SF1 measurements for the second batch are reported below, including Q75's slower observed execution.

## Query 1: Customer returns above the store average

**Original behavior.** Calculate each customer's return amount per store for a selected year. Return customers whose amount exceeds `1.2 *` the average customer return total at that store, considering only stores in the selected state.

**Changes.**

- Join `store` inside `customer_total_return` and apply `s_state` before grouping. Other states are not needed by the final result.
- Keep the original grouping by customer and store.
- Replace the correlated average lookup with a `store_average` CTE grouped by store key.
- Join the store average and customer dimension to the grouped return totals.

Moving the store-state filter is safe because the threshold is calculated separately for each store and `s_store_sk` is the store table's primary key. The average still includes the NULL-customer group, if present; the final customer join removes that group from the output.

| SF | Return year | Store state |
|---|---|---|
| SF1 | 1998 | `TN` |
| SF2 | 1998 | `TN` |
| SF5 | 1998 | `TN` |
| SF10 | 1998 | `SD` |

The `1.2` multiplier, customer-ID ordering, and `LIMIT 100` remain unchanged. The intended benefit is to restrict return aggregation to relevant stores and replace correlated average lookups with a grouped join.

## Query 4: Compare growth across three sales channels

**Original behavior.** Build annual customer totals for store, catalog, and web sales using `UNION ALL`. Reference the combined result six times to match the first and second years for all three channels. Select customers whose catalog growth ratio exceeds both their store and web ratios.

**Changes.**

- Replace the combined annual relation with `store_agg`, `catalog_agg`, and `web_agg`.
- Restrict each channel to the two relevant years before grouping.
- Calculate both annual totals with `SUM(CASE WHEN ... THEN ... END)`.
- Preserve the complete customer-attribute grouping used by the original query.
- Use `HAVING` to require a positive first-year total and at least one second-year row.
- Join the three channel summaries and compare the same growth ratios.

The per-row expression is preserved, including its arithmetic order:

```text
((ext_list_price - ext_wholesale_cost - ext_discount_amt) + ext_sales_price) / 2
```

The second-year existence check uses `COUNT(CASE WHEN ... THEN 1 END) > 0` rather than requiring a positive second-year amount. Missing or NULL second-year totals are not replaced with zero; they retain the original comparison behavior.

All four scale factors use **1998 and 1999**. The original Q4 files are identical across these scale factors, so the same optimized SQL applies. The output remains customer ID, first name, last name, and birth country, in the original sort order with `LIMIT 100`.

The intended benefit is to aggregate only the required years and replace six annual-result aliases with three channel summaries.

## Query 6: Item prices above their category average

**Original behavior.** Count qualifying store-sale rows by customer state for a selected month. An item qualifies when its current price exceeds `1.2 *` the average current price of all items in its category.

**Changes.**

- Add `cat_avg`, grouped by `i_category` over the complete `item` table.
- Join each sold item to its category average.
- Keep the original customer, address, sales, and date relationships.

The category average is calculated over all items in the category, including items not sold in the selected month. Calculating it only from matching sales would change the threshold.

A NULL category does not match the equality join, just as it does not match the original correlated equality predicate. `AVG` continues to ignore NULL prices.

All four scale factors use **February 2000**, `HAVING COUNT(*) >= 10`, ordering by count and state, and `LIMIT 100`. Counts represent qualifying joined sale rows, not distinct customers or orders.

The original Q6 files are identical across these scale factors. The intended benefit is to calculate category averages as one grouped relation instead of a correlated item lookup.

## Query 11: Compare store and web annual growth

**Original behavior.** Calculate annual store and web sums of `ext_list_price - ext_discount_amt`, then reference the combined annual totals four times to compare two years in both channels.

**Changes.**

- Build one grouped summary per channel, keyed by the fact table's customer surrogate key.
- Calculate both years with `SUM(...) FILTER (WHERE d_year = ...)`.
- Restrict input rows to the two selected years.
- Require a positive first-year total in each channel through `HAVING`.
- Join store and web summaries before fetching customer attributes.

The comparison remains:

```text
web_second_year / web_first_year > store_second_year / store_first_year
```

A missing or all-NULL second-year aggregate remains NULL and fails the comparison, as in the original query. NULL fact customer keys can be removed early here because the original calculation already inner-joins the customer table.

Deferring the dimension join relies on the TPC-DS customer identity: the surrogate key identifies a customer, and generated customer IDs are unique. Custom datasets that reuse customer IDs would require a separate equivalence review.

| SF | First year | Second year | Fourth output column |
|---|---|---|---|
| SF1 | 2000 | 2001 | `customer_login` |
| SF2 | 1998 | 1999 | `customer_birth_country` |
| SF5 | 1998 | 1999 | `customer_login` |
| SF10 | 1999 | 2000 | `customer_preferred_cust_flag` |

Every version orders by customer ID, first name, last name, and its own fourth output column, then applies `LIMIT 100`. Preserving that fourth column is part of the adaptation.

The intended benefit is to avoid four references to a combined annual relation and reduce the number of rows carrying customer attributes.

## Query 14: Cross-channel items, monthly rollups, and weekly comparison

Each `query_14.sql` retains **two separate SQL statements**. Both build their own CTEs. Materialization reuses data within a statement; it does not share data between the two statements.

The SF2, SF5, and SF10 versions follow the latest [SF1 rewrite](sf1/queries_optimized/query_14.sql), including its Part 2 date filtering. The older [SF1 version](sf1/optimized_queries/query_14.sql) remains a historical reference. Each adaptation retains the dates from its own original query, as listed below.

### Shared three-year preparation

Both statements use the same rewrite pattern:

1. Select date keys for the full three-year interval in `d_3yr`.
2. Aggregate store, catalog, and web sales by item into `ss_3yr`, `cs_3yr`, and `ws_3yr`.
3. Retain both `SUM(quantity * list_price)` and `COUNT(quantity * list_price)`.
4. Build `cross_items` by intersecting brand/class/category combinations across the three channels, then map those combinations back to item keys.
5. Calculate `avg_sales` from the channel summaries.

The item summaries, `cross_items`, and `avg_sales` are explicitly `MATERIALIZED`. This makes the summaries available for reuse within each statement, with a materialization cost that must be assessed through execution plans.

The global average is calculated as:

```text
SUM(all channel/item product sums)
-----------------------------------
SUM(all channel/item non-NULL product counts)
```

This preserves the original row-weighted average across all three channels. An average of item averages or channel averages would weight groups differently. `COUNT(product)` is essential because `AVG(product)` ignores NULL products. The threshold uses all sales in the three-year interval, including items outside `cross_items`.

The cross-channel condition remains an intersection of **(brand, class, category)** combinations. It does not require one identical item key to have sales in every channel.

### Part 1: Monthly totals and rollup

The rewrite joins the selected month through `target_month_dates` in SF2, SF5, and SF10. This replaces the SF1-specific name `nov_2000_dates`.

Each channel still groups sales by brand, class, and category, applies the original threshold in `HAVING`, and contributes through `UNION ALL`. The outer `ROLLUP`, ordering, and `LIMIT 100` are preserved.

The output's `number_sales` remains `COUNT(*)`. Unlike the count used for the average denominator, it includes every qualifying sale row, including rows with a NULL price/quantity product.

### Part 2: Compare two complete weeks

The original query separately aggregates store sales for two weeks and joins the grouped results. The rewrite uses one grouped store-sales query, with separate `FILTER` expressions for this-year and last-year sums and counts.

The latest SF1 change is also applied to SF2, SF5, and SF10:

1. `target_weeks AS MATERIALIZED` resolves the two anchor dates to `ty_week` and `ly_week` once within the statement.
2. `target_dates AS MATERIALIZED` selects only `d_date_sk` and `d_week_seq` for those two complete weeks before the store-sales join.
3. The weekly aggregate joins `store_sales` to `target_dates` by the sold-date key and uses `td.d_week_seq` in its `FILTER` expressions.

This moves the week restriction into a small, explicitly materialized date input. The three-year summaries and global average still use the full three-year interval; the two-week restriction applies only to the final weekly sales calculation. Materialization does not force a particular join algorithm or guarantee a speedup.

Both weekly sums must still exceed `average_sales`. The two `HAVING` conditions preserve the eligibility imposed by the original grouped queries and their inner join.

The anchor dates below identify `d_week_seq` values. The query includes the **entire corresponding week**, which may cross a month or year boundary. Restricting sales to the anchor date or to the anchor's calendar year would change the result.

| SF | Three-year interval | Part 1 month | Part 2 this-year anchor | Part 2 last-year anchor |
|---|---|---|---|---|
| SF1 | 1998-2000 | November 2000 | 1999-12-22 | 1998-12-22 |
| SF2 | 2000-2002 | November 2002 | 2001-12-17 | 2000-12-17 |
| SF5 | 1998-2000 | November 2000 | 1999-12-24 | 1998-12-24 |
| SF10 | 2000-2002 | November 2002 | 2001-12-05 | 2000-12-05 |

The intended benefit is to reuse compact three-year summaries instead of repeating work over raw sales rows, combine the two weekly aggregations in Part 2, and expose the selected date keys before joining weekly sales. Part 1's monthly calculation, both result sets' output columns, ordering, and `LIMIT 100` remain unchanged.

## Query 16: Catalog orders shipped from different warehouses

**Original behavior.** Aggregate qualifying catalog-sale rows by a shipping-date interval, shipping-address state, and call-center county. A row's order must have another catalog-sale row from a different warehouse, and the order must have no catalog return.

**Changes.**

- Express dimension relationships with explicit joins.
- Use typed `DATE 'YYYY-MM-DD'` literals.
- Replace `SELECT *` inside existence subqueries with `SELECT 1`.
- Remove duplicate county literals. A one-value county set becomes equality.

The `EXISTS` and `NOT EXISTS` predicates remain. They test membership without multiplying the outer sale rows. The warehouse comparison remains `<>`, including its original NULL behavior.

| SF | Shipping start date | Shipping-address state | Call-center county set |
|---|---|---|---|
| SF1 | 2001-03-01 | `KY` | Williamson County |
| SF2 | 2001-02-01 | `IL` | Williamson County |
| SF5 | 2001-05-01 | `KS` | Williamson County |
| SF10 | 1999-02-01 | `KY` | Walker County, Ziebach County, Williamson County |

The date interval is inclusive: **start date through start date + 60 days**. SF10 retains all three distinct counties using `IN (...)`; reducing it to Williamson County would be incorrect.

The distinct order count, shipping-cost sum, net-profit sum, ordering, and `LIMIT 100` are unchanged. This rewrite mainly improves clarity and removes redundant literals; it should not be presented as a guaranteed execution-time improvement.

## Query 17: Quantity statistics across store sales, returns, and catalog sales

**Original behavior.** Match store sales to store returns on customer, item, and ticket number, then match catalog sales on customer and item. Group by item ID, item description, and store state. Calculate counts, averages, sample standard deviations, and coefficients of variation for all three quantity columns.

**Changes.**

- Materialize `store_return_rows` after applying the store-sale and return quarter filters. Keep only the join keys, store key, and quantity columns needed later.
- Build `matching_pairs` as distinct customer/item keys from those matches.
- Use that key set to restrict catalog rows before the final join.
- Join the complete store/return rows back to the matching catalog rows, then fetch item/store attributes for grouping.
- Retain the original native `COUNT(column)`, `AVG`, `STDDEV_SAMP`, and `STDDEV_SAMP / AVG` expressions.

Only the catalog eligibility key set is deduplicated. No store/return or catalog fact rows are deduplicated. If two store/return matches have four matching catalog rows, the aggregate input still contains eight joined rows. Replacing those rows with unweighted per-pair statistics would change counts and sample deviations.

`COUNT(column)` continues to ignore NULL quantities. All-NULL groups retain NULL averages and deviations. No manual variance formula, zero substitution, or new division guard is introduced.

| SF | Store-sale quarter | Return quarters | Catalog-sale quarters |
|---|---|---|---|
| SF1 | 2000Q1 | 2000Q1, 2000Q2, 2000Q3 | 2000Q1, 2000Q2, 2000Q3 |
| SF2 | 2000Q1 | 2000Q1, 2000Q2, 2000Q3 | 2000Q1, 2000Q2, 2000Q3 |
| SF5 | 2000Q1 | 2000Q1, 2000Q2, 2000Q3 | 2000Q1, 2000Q2, 2000Q3 |
| SF10 | 1998Q1 | 1998Q1, 1998Q2, 1998Q3 | 1998Q1, 1998Q2, 1998Q3 |

The output aliases, grouping, sort order, and `LIMIT 100` are unchanged. The intended benefit is to make the selective store/return match explicit and restrict the catalog join to relevant customer/item pairs while preserving the original statistics.

## Query 25: Profit and loss aggregates with catalog join multiplicity

**Original behavior.** Match April store sales with returns from April through October of the same year. Join catalog sales for the same customer/item in April through October. Group by item and store attributes and aggregate store profit, return loss, and catalog profit.

**Changes.**

- Materialize the filtered store/return matches, preserving customer/item/ticket equality.
- Use `EXISTS` to restrict catalog input to customer/item pairs present in those matches.
- Summarize catalog profit by customer/item before the final item/store grouping.
- Preserve the aggregate requested by each SF rather than using the SF1 aggregate everywhere.

| SF | Year for all three date filters | Aggregate for all three output measures |
|---|---|---|
| SF1 | 2000 | `MIN` |
| SF2 | 1999 | `AVG` |
| SF5 | 1998 | `MAX` |
| SF10 | 2002 | `SUM` |

All versions use April store sales and April-October returns/catalog sales. Their output aliases, grouping, sorting, and `LIMIT 100` match their originals.

### MIN and MAX variants

SF1 and SF5 can reduce catalog rows to their per-pair minimum or maximum. Repeating a value through a join does not change its minimum or maximum. A catalog group whose profits are all NULL is still retained, so it continues to establish that a catalog match exists.

### AVG and SUM variants

SF2 and SF10 must preserve how often catalog matches repeat the store and return values. Simply joining one catalog average/sum per pair and applying unweighted outer aggregates would be incorrect.

For each customer/item pair, the catalog summary retains:

| Symbol | SQL measure | Purpose |
|---|---|---|
| `n` | `COUNT(*)` | Number of matching catalog rows, including rows with NULL profit. |
| `s` | `SUM(cs_net_profit)` | Sum of non-NULL catalog profits. |
| `k` | `COUNT(cs_net_profit)` | Number of non-NULL catalog profits; needed by AVG. |

Over the original store/return matches `m`, the equivalent aggregates are:

```text
AVG(store_profit) = SUM(m.store_profit * n)
                   / SUM(n) FILTER (WHERE m.store_profit IS NOT NULL)

AVG(return_loss)  = SUM(m.return_loss * n)
                   / SUM(n) FILTER (WHERE m.return_loss IS NOT NULL)

AVG(catalog_profit) = SUM(s) / SUM(k)

SUM(store_profit)   = SUM(m.store_profit * n)
SUM(return_loss)    = SUM(m.return_loss * n)
SUM(catalog_profit) = SUM(s)
```

Each catalog summary is joined once for every original store/return match, so `SUM(s)` and `SUM(k)` also retain that side of the join multiplicity. The AVG implementation uses `NULLIF(denominator, 0)` to return NULL for an all-NULL measure, matching native `AVG`.

Catalog rows with NULL profit still contribute to `n`: they repeat a non-NULL store profit or return loss in the original join even though they do not contribute to the catalog-profit average.

The intended benefit is to avoid expanding every catalog match when the requested aggregate can instead be represented by compact per-pair values and counts. SF2/SF5/SF10 received static review only; these variants were not executed.

## Query 29: Quantity aggregates over a three-year catalog window

**Original behavior.** Match April store sales to returns from April through July of the same year, then join catalog sales from that year and the next two years. Group by item and store attributes.

**Changes.**

- Materialize narrow, date-filtered store/return matches.
- Deduplicate only the candidate customer/item key set.
- Restrict catalog input through those keys and the original three-year filter.
- Restore the full fact-row join before applying the SF-specific native aggregates.

| SF | Base year | Aggregate of each quantity column | Catalog years |
|---|---|---|---|
| SF1 | 1998 | `STDDEV_SAMP` | 1998, 1999, 2000 |
| SF2 | 2000 | `MIN` | 2000, 2001, 2002 |
| SF5 | 2000 | `STDDEV_SAMP` | 2000, 2001, 2002 |
| SF10 | 2000 | `MIN` | 2000, 2001, 2002 |

The catalog window includes complete years, not only April-July. The store-sale and return windows remain April and April-July respectively.

Keeping raw aggregate-input rows is particularly important for `STDDEV_SAMP`, whose sample denominator depends on the count of non-NULL values after the join. The rewrite does not replace it with a population deviation or a deviation of preaggregated means.

Output aliases, item/store grouping, ordering, and `LIMIT 100` are preserved.

## Query 30: Web returns above the return-state average

**Original behavior.** Sum web return amounts by returning customer and returning-address state. Compare each total against `1.2 *` the average of the customer totals in that return state. Finally, filter customers by their current-address state.

**Changes.**

- Calculate customer/state totals once in `customer_total_return`.
- Replace the correlated average with `AVG(total_return) OVER (PARTITION BY return_state)`.
- Fetch customer attributes and apply the current-address state filter after calculating the average.
- Remove NULL return states, which cannot pass the original correlated state-equality comparison.

The state used for the average comes from `wr_returning_addr_sk`. The final state filter comes from `c_current_addr_sk`. These addresses can differ; filtering the return-address state by the final state literal would change the result.

### NULL-customer correction in SF2, SF5, and SF10

The existing SF1 rewrite removes `wr_returning_customer_sk IS NULL` before calculating the state average. The original query includes that NULL-customer group in the average, even though the final customer join prevents it from appearing in the output.

The new versions therefore retain this group through the window calculation. The final customer join removes it afterward.

For example, consider one return state with customer totals of `200`, `190`, and `100`, plus a NULL-customer total of `0`:

| Calculation | State average | Threshold: average * 1.2 | Qualifying known-customer totals |
|---|---:|---:|---|
| Original and corrected rewrite | 122.5 | 147 | 200 and 190 |
| Early removal of NULL customer | 163.333... | 196 | 200 |

The SF1 file remains unchanged as the historical reference; SF2, SF5, and SF10 contain the corrected behavior.

| SF | Return year | Final current-address state |
|---|---|---|
| SF1 | 2002 | `TX` |
| SF2 | 2000 | `ME` |
| SF5 | 1999 | `MI` |
| SF10 | 1999 | `CO` |

All customer output attributes, the return-total output, sorting, and `LIMIT 100` are preserved. The intended benefit is to replace correlated lookups with a window calculation over the grouped totals.

## Query 74: Compare annual store and web aggregates

**Original behavior.** Calculate annual aggregates of `net_paid` for store and web sales, then match the two years for each channel through four references to the combined annual relation.

**Changes.**

- Build one grouped summary per channel.
- Calculate both annual values with `FILTER`.
- Require a positive first-year aggregate through `HAVING`.
- Join the channel summaries and fetch customer attributes afterward.
- Preserve each scale factor's aggregate function and output ordering.

This uses the same two-year summary pattern as Q11, but the aggregate function varies. Replacing every version with `SUM` or copying SF1's `STDDEV_SAMP` into SF2/SF10 would change the requested calculation.

| SF | Aggregate of `net_paid` | First / second year | Sort order |
|---|---|---|---|
| SF1 | `STDDEV_SAMP` | 2000 / 2001 | First name, customer ID, last name |
| SF2 | `AVG` | 2001 / 2002 | Customer ID, last name, first name |
| SF5 | `STDDEV_SAMP` | 2000 / 2001 | Last name, customer ID, first name |
| SF10 | `MAX` | 1998 / 1999 | Last name, customer ID, first name |

The named sort columns correspond to the original positional ordering: `2,1,3` for SF1; `1,3,2` for SF2; and `3,1,2` for SF5/SF10.

The comparison remains the web second-year/first-year ratio against the store ratio. For `STDDEV_SAMP`, groups with insufficient non-NULL observations produce NULL and retain the original eligibility behavior. The aliases `first_year_total` and `second_year_total` hold aggregate values; they are not necessarily sums.

The customer-identity assumption described for Q11 also applies here. `LIMIT 100` and the three output columns remain unchanged.

## Query 75: Compare annual net sales after returns

**Original behavior.** Calculate net quantity and net sales amount after returns for catalog, store, and web sales in one item category. Combine the detail rows with `UNION`, aggregate by year and four item classification IDs, then join current-year and previous-year totals. Keep groups whose current/previous quantity ratio is below `0.9`.

**Changes.**

- Restrict date input to the two compared years before processing the sales branches.
- Restrict item input to the selected category and non-NULL brand/class/category/manufacturer IDs.
- Preserve the original return join keys, `LEFT JOIN` relationships, and `COALESCE` expressions.
- Preserve `UNION` duplicate elimination on the exact seven-column detail tuple.
- Use `SUM(...) FILTER (WHERE d_year = ...)` to obtain both annual totals in one grouping.
- Require at least one detail row in both years with `HAVING COUNT(*) FILTER (...) > 0`.

The seven deduplication columns are **year, brand ID, class ID, category ID, manufacturer ID, net quantity, and net amount**. Identical tuples are removed within and across channels. Replacing `UNION` with `UNION ALL`, adding order/item identifiers to the tuple, or aggregating each channel before deduplication would change the result.

Early year filtering is safe because year is part of that tuple. Early removal of NULL classification IDs is safe because the original annual self-join uses equality on all four IDs; groups with any NULL ID cannot match.

The small date/item CTEs use `NOT MATERIALIZED` so PostgreSQL can inline them. Narrow sales and returns subqueries use `OFFSET 0` as planner boundaries: no row is skipped, but parameterized index-lookup paths through those subqueries are prevented. This addresses the many fact/return index lookups seen during SF1 plan investigation while keeping every input row.

| SF | Category | Previous year | Current year |
|---|---|---|---|
| SF1 | `Sports` | 2000 | 2001 |
| SF2 | `Home` | 2001 | 2002 |
| SF5 | `Shoes` | 1998 | 1999 |
| SF10 | `Music` | 2001 | 2002 |

The quantity ratio retains both `DECIMAL(17,2)` casts and the strict `< 0.9` condition. No zero-denominator guard is added. Missing or all-NULL measures retain the original behavior.

The output remains previous/current year, four classification IDs, annual quantities, quantity difference, and amount difference. Ordering stays `sales_cnt_diff, sales_amt_diff` with `LIMIT 100`. No new tie-breaker is introduced.

The rewrite reduces the years entering deduplication and removes the annual self-join. Execution-time improvement remains dependent on the physical plan and cache/I/O conditions; result equivalence is assessed separately.

## Query 81: Catalog returns above the return-state average

**Original behavior.** Calculate customer/state catalog-return totals, then use a correlated lookup to obtain the average customer total in the same return state.

**Changes.**

- Retain grouping by returning customer and returning-address state.
- Calculate the threshold using `AVG(SUM(cr_return_amt_inc_tax)) OVER (PARTITION BY ca_state)`.
- Exclude NULL return states, matching the original equality-based eligibility.
- Join customer/current-address details after the average calculation.

The window function operates on the grouped customer totals. It is not an average of individual return rows. The NULL-customer group remains in the average until the final customer join, as required by the original query.

As in Q30, the return-address state used for the average and the current-address state used for final selection are separate concepts.

| SF | Return year | Final current-address state |
|---|---|---|
| SF1 | 1999 | `ND` |
| SF2 | 1999 | `WV` |
| SF5 | 2000 | `MO` |
| SF10 | 1998 | `MO` |

The customer/address output columns, `ctr_total_return`, complete sort order, `1.2` multiplier, and `LIMIT 100` are preserved. The intended benefit is to avoid correlated scans of the grouped return totals.

## Query 95: Returned web orders supplied by multiple warehouses

**Original behavior.** Construct `ws_wh` by joining web sales to itself on order number and finding unequal warehouse keys. Aggregate sales satisfying the shipping-date, address-state, and website-company filters, provided their orders occur in both the multi-warehouse result and web returns.

**Changes.**

1. Materialize matching sale rows in `filtered_ws`, retaining order number, shipping cost, and net profit.
2. Obtain candidate order numbers from that filtered relation.
3. Inspect `web_sales` for all rows belonging to those candidate orders.
4. Group by order number and require `COUNT(DISTINCT ws_warehouse_sk) > 1`.
5. Apply membership checks for multi-warehouse orders and `web_returns` to `filtered_ws`.

The warehouse check includes all sale rows of each candidate order, including rows outside the date, address, or website filters. Counting warehouses only within `filtered_ws` would incorrectly exclude some orders.

`COUNT(DISTINCT warehouse) > 1` requires at least two distinct non-NULL warehouses, matching the original `warehouse_1 <> warehouse_2` condition. The membership predicates avoid multiplying sales rows by warehouse pairs or return records.

Shipping cost and profit remain sums over the filtered sale rows. Orders must have a return; this is positive return membership, unlike Q16's `NOT EXISTS` condition.

| SF | Shipping start date | Shipping-address state | Website company |
|---|---|---|---|
| SF1 | 2000-05-01 | `SC` | `pri` |
| SF2 | 2000-04-01 | `MS` | `pri` |
| SF5 | 1999-02-01 | `AR` | `pri` |
| SF10 | 1999-04-01 | `MT` | `pri` |

The date interval is inclusive: start date through start date + 60 days. The distinct order count, output aliases, ordering, and `LIMIT 100` are preserved.

The intended benefit is to avoid constructing warehouse-pair rows and restrict warehouse grouping to candidate orders. Actual performance depends on the plan and data distribution.

## Validation completed

### First batch: Q1, Q4, Q6, Q11, Q14, Q16, Q30, Q74, Q81, and Q95

The initial adaptation was checked at three levels:

| Check | Scope | What it establishes |
|---|---|---|
| File and parameter review | The initial 30 adapted files | The ten first-batch files per new SF had correct SF-specific parameters, aggregate functions, output columns, ordering, and statement counts. |
| PostgreSQL 16 `EXPLAIN` | 66 statements: 33 original and 33 optimized | All selected original and adapted statements parse, resolve against the TPC-DS schema, and produce plans. |
| Q30 result comparison on a synthetic fixture | SF2, SF5, and SF10 | The corrected query matches the original with NULL customer keys, NULL return amounts, and NULL return states. |

The `EXPLAIN` check used a temporary PostgreSQL 16 instance with the TPC-DS schema and no full-scale benchmark data. It did not execute the queries or measure execution time.

The Q30 fixture returned two rows from both the original and corrected query in every tested SF. Reintroducing the early NULL-customer filter returned one row, demonstrating the difference described above.

Full result equivalence on the actual SF2/SF5/SF10 datasets and measured performance comparisons for that batch remain to be run.

### Q14 refresh from the latest SF1 rewrite

The revised SF2/SF5/SF10 Q14 files retain two statements and the original per-SF year/month/day parameters. Static review covers the materialized `target_weeks`/`target_dates` structure, complete-week filtering, the unchanged three-year average, and the output clauses. The first-batch `EXPLAIN` results above describe the earlier Q14 versions; they do not validate this refresh. Full-data result equivalence and performance of the refreshed versions remain to be measured.

### Second batch: Q17, Q25, Q29, and Q75

The four original queries were executed against the existing SF1 dataset in database `tpcds` using PostgreSQL 16.15 and `work_mem=256MB`. A fresh, one-run baseline was saved under [validation_q17_q25_q29_q75/original](sf1/validation_q17_q25_q29_q75/original/).

The generated result rows were copied to [sf1/ans_from_original](sf1/ans_from_original/) as `17.ans`, `25.ans`, `29.ans`, and `75.ans`. Other answer files were retained. The rewritten SQL was then executed from `sf1/queries_optimized` with the same database and memory setting through `3_compare_result.py -sd ... -ed ... -bc ...`.

Both the normal comparison and a separate `--strict` comparison of the saved final outputs passed:

| Query | Original rows | Rewritten rows | Normal comparison | Strict comparison |
|---|---:|---:|---|---|
| Q17 | 1 | 1 | Match | Match |
| Q25 | 0 | 0 | Match | Match |
| Q29 | 1 | 1 | Match | Match |
| Q75 | 100 | 100 | Match | Match |

Reports and execution evidence:

- [Final combined comparison](sf1/validation_q17_q25_q29_q75/comparison_report.csv)
- [Strict comparison](sf1/validation_q17_q25_q29_q75/comparison_report_strict.csv)
- [Fresh original timing CSV](sf1/validation_q17_q25_q29_q75/original/exec_time_details.csv)
- [Final rewritten timing CSV](sf1/validation_q17_q25_q29_q75/optimized_exec_time_details.csv)
- [Saved rewritten outputs](sf1/queries_optimized/executed_outputs/)

Q25's real-data comparison is empty on both sides, so it alone cannot demonstrate the behavior of nonempty groups. Q17 and Q29 also return only one group on this dataset. Additional [SF1 fixture checks](sf1/validation_q17_q25_q29_q75/sf1_fixture_checks.sql) were therefore executed for all three queries.

The fixture uses temporary tables inside a transaction that is rolled back. It compares typed results with `EXCEPT ALL` in both directions and asserts expected values for two output groups. Coverage includes eight joined rows from two store/return matches and four catalog rows, repeated projected catalog values, NULL quantities/profits, an all-NULL group, missing catalog matches, mismatched tickets/customers, NULL customer keys, and excluded dates. All checks passed; see the [fixture log](sf1/validation_q17_q25_q29_q75/sf1_fixture_checks.log). Public data was not modified.

### Observed SF1 times for the second batch

| Query | Original execution, seconds | Final rewritten execution, seconds | Ratio reported by comparison |
|---|---:|---:|---|
| Q17 | 20.687 | 14.478 | 1.43x faster |
| Q25 | 3.314 | 0.981 | 3.38x faster |
| Q29 | 1.719 | 0.728 | 2.36x faster |
| Q75 | 3.719 | 4.436 | 1.19x slower |

These are individual validation executions, not a repeated benchmark under controlled cache conditions. Q75 was investigated and revised using SF1 execution plans; its final output remained identical, but its final measured execution was still slower than the recorded baseline. The implementation is retained as a semantics-preserving rewrite, without claiming a Q75 speedup.

The final combined report uses the first successful live comparison for unchanged Q17/Q25/Q29 and the final live comparison for revised Q75. The rewritten timing CSV records those per-query observations. The final normal and strict reports were generated from those saved outputs without re-executing unchanged queries.

**SF2, SF5, and SF10 were not executed for this second batch, including no `EXPLAIN` runs.** Their twelve new files received static review of the original-query differences, date/category parameters, aggregate variants, join keys, duplicate/NULL semantics, and output clauses. Runtime equivalence and performance for these files remain unmeasured.

### Reproducing the four-query SF1 comparison

The following PowerShell example generates fresh original results, writes the four expected answer files, and uses the requested live-comparison workflow. Run it from the repository root against the database containing SF1. The timestamped run directory preserves earlier measurement reports.

```powershell
$databaseName = 'tpcds'
$selectedQueries = '17,25,29,75'
$runTag = Get-Date -Format 'yyyyMMdd-HHmmss'
$validationRun = "benchmarks/sf1/validation-four-queries-$runTag"

python 2_run_tpcds_benchmark.py `
  -i benchmarks/sf1/queries `
  -o "$validationRun/original" `
  -d $databaseName `
  -q $selectedQueries `
  -n 1 `
  --set work_mem=256MB

New-Item -ItemType Directory -Force `
  -Path benchmarks/sf1/ans_from_original | Out-Null

foreach ($queryNumber in @(17, 25, 29, 75)) {
    $sourceAnswer = "$validationRun/original/results/Q{0:D2}.txt" -f $queryNumber
    $targetAnswer = "benchmarks/sf1/ans_from_original/{0}.ans" -f $queryNumber
    Copy-Item -LiteralPath $sourceAnswer -Destination $targetAnswer
}

$baseCsv = "$validationRun/original/exec_time_details.csv"

python 3_compare_result.py `
  -sd benchmarks/sf1/queries_optimized `
  -ed benchmarks/sf1/ans_from_original `
  -bc "$baseCsv" `
  -d $databaseName `
  -q $selectedQueries `
  --set work_mem=256MB `
  --report "$validationRun/comparison_report.csv" `
  --diff-dir "$validationRun/diffs"

python 3_compare_result.py `
  --actual-dir benchmarks/sf1/queries_optimized/executed_outputs `
  -ed benchmarks/sf1/ans_from_original `
  -q $selectedQueries `
  --strict `
  --report "$validationRun/comparison_report_strict.csv" `
  --diff-dir "$validationRun/strict_diffs"
```

## Running result and performance comparisons

Run the following PowerShell commands from the repository root. Set the database name to the database that actually contains the chosen SF's data. Change `$sf` and the database name together for SF5 or SF10.

The example below is for future validation of all fourteen selected queries in a higher SF. It uses fresh, timestamped output directories and saves result rows for comparison. It does not indicate that the four new queries have already been executed in SF2/SF5/SF10.

```powershell
$sf = 2
$databaseName = 'REPLACE_WITH_DATABASE_CONTAINING_SF2'
$selectedQueries = '1,4,6,11,14,16,17,25,29,30,74,75,81,95'
$runTag = Get-Date -Format 'yyyyMMdd-HHmmss'
$originalRun = "benchmarks/sf$sf/verification-original-$runTag"
$optimizedRun = "benchmarks/sf$sf/verification-optimized-$runTag"

python 2_run_tpcds_benchmark.py `
  -i "benchmarks/sf$sf/queries" `
  -o $originalRun `
  -d $databaseName `
  -q $selectedQueries `
  -n 3

python 2_run_tpcds_benchmark.py `
  -i "benchmarks/sf$sf/optimized_queries" `
  -o $optimizedRun `
  -d $databaseName `
  -q $selectedQueries `
  -n 3

python 3_compare_result.py `
  --actual-dir "$optimizedRun/results" `
  --expected-dir "$originalRun/results" `
  --baseline-csv "$originalRun/exec_time_details.csv" `
  --optimized-csv "$optimizedRun/exec_time_details.csv" `
  --query $selectedQueries `
  --report "benchmarks/sf$sf/verification-comparison-$runTag.csv" `
  --diff-dir "benchmarks/sf$sf/verification-diffs-$runTag"
```

These commands use the scripts' default container `tpcds-postgres` and user `tpcds`. If the environment differs, supply `-c` and `-u` consistently to both benchmark runs. The directory-comparison command reads saved files and does not connect to the database.

Use the same database snapshot, server settings, measurement mode, and cache policy for each original/optimized pair. Choose new output directories for subsequent runs. Query 14's two statement times are summed into a single query time by the benchmark runner.

Default benchmark mode saves result rows under `results/Qnn.txt`. For a separate plan investigation, `--explain-analyze` executes `EXPLAIN (ANALYZE, BUFFERS)` and saves plans under `plans/`; those plan files do not replace the result rows needed for equivalence checking.

The comparison script's actual filename is [3_compare_result.py](../3_compare_result.py), with singular `result`. The runner is [2_run_tpcds_benchmark.py](../2_run_tpcds_benchmark.py).

### Interpreting comparison results

The default comparison normalizes formatting and decimal representations. Decimal normalization uses Python `float` and rounds to at most four decimal places. Consequently, an "exact match" label means equality after that normalization, not proof of exact SQL numeric equality.

`--strict` disables numeric/format normalization but still ignores blank lines and newline differences. It is a strict comparison of nonblank lines, not a byte-for-byte comparison. Row-order differences are reported as mismatches.

Inspect the report for every selected query. Missing reference files may be marked as skipped, and batch mode does not necessarily exit with a nonzero status for mismatches. A successful command exit alone does not establish equivalence.

For stronger value and duplicate-row checks, compare typed results inside PostgreSQL with `EXCEPT ALL` in both directions. Check ordering separately where it is part of the expected output, and keep both Q14 result sets separate.

## Repository tracking

The current root `.gitignore` contains `optimized_queries/`, which also ignores the per-SF optimized directories. The SQL files exist locally, but ordinary `git status` will not list them as new files.

The SF1 `queries_optimized` directory uses a different name and is not covered by that rule. This README is stored outside the ignored directories so it can be tracked independently. The ignore configuration has not been changed.
