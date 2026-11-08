-- TPC-DS Query 75 optimized for PostgreSQL.
-- Filter the two required years and category before return joins and UNION.
-- Preserve UNION duplicate elimination on the original seven-column tuple.
-- Pivot both annual sums in one grouping instead of joining annual summaries.
-- Inline dimension filters and expose narrow, bag-preserving fact projections.
-- OFFSET 0 prevents item-driven random fact reads and parameterized return
-- lookups under the date-filter selectivity underestimate in this schema.

WITH sales_dates AS NOT MATERIALIZED (
    SELECT d_date_sk,
           d_year
    FROM date_dim
    WHERE d_year IN (2001, 2002)
),
category_items AS NOT MATERIALIZED (
    SELECT i_item_sk,
           i_brand_id,
           i_class_id,
           i_category_id,
           i_manufact_id
    FROM item
    WHERE i_category = 'Music'
      AND i_brand_id IS NOT NULL
      AND i_class_id IS NOT NULL
      AND i_category_id IS NOT NULL
      AND i_manufact_id IS NOT NULL
),
sales_detail AS (
    SELECT d.d_year,
           i.i_brand_id,
           i.i_class_id,
           i.i_category_id,
           i.i_manufact_id,
           cs.cs_quantity - COALESCE(cr.cr_return_quantity, 0) AS sales_cnt,
           cs.cs_ext_sales_price - COALESCE(cr.cr_return_amount, 0.0) AS sales_amt
    FROM (
        SELECT cs_sold_date_sk,
               cs_item_sk,
               cs_order_number,
               cs_quantity,
               cs_ext_sales_price
        FROM catalog_sales
        OFFSET 0
    ) AS cs
    JOIN category_items AS i ON i.i_item_sk = cs.cs_item_sk
    JOIN sales_dates AS d ON d.d_date_sk = cs.cs_sold_date_sk
    LEFT JOIN (
        SELECT cr_order_number,
               cr_item_sk,
               cr_return_quantity,
               cr_return_amount
        FROM catalog_returns
        OFFSET 0
    ) AS cr
      ON cr.cr_order_number = cs.cs_order_number
     AND cr.cr_item_sk = cs.cs_item_sk
    UNION
    SELECT d.d_year,
           i.i_brand_id,
           i.i_class_id,
           i.i_category_id,
           i.i_manufact_id,
           ss.ss_quantity - COALESCE(sr.sr_return_quantity, 0) AS sales_cnt,
           ss.ss_ext_sales_price - COALESCE(sr.sr_return_amt, 0.0) AS sales_amt
    FROM (
        SELECT ss_sold_date_sk,
               ss_item_sk,
               ss_ticket_number,
               ss_quantity,
               ss_ext_sales_price
        FROM store_sales
        OFFSET 0
    ) AS ss
    JOIN category_items AS i ON i.i_item_sk = ss.ss_item_sk
    JOIN sales_dates AS d ON d.d_date_sk = ss.ss_sold_date_sk
    LEFT JOIN (
        SELECT sr_ticket_number,
               sr_item_sk,
               sr_return_quantity,
               sr_return_amt
        FROM store_returns
        OFFSET 0
    ) AS sr
      ON sr.sr_ticket_number = ss.ss_ticket_number
     AND sr.sr_item_sk = ss.ss_item_sk
    UNION
    SELECT d.d_year,
           i.i_brand_id,
           i.i_class_id,
           i.i_category_id,
           i.i_manufact_id,
           ws.ws_quantity - COALESCE(wr.wr_return_quantity, 0) AS sales_cnt,
           ws.ws_ext_sales_price - COALESCE(wr.wr_return_amt, 0.0) AS sales_amt
    FROM (
        SELECT ws_sold_date_sk,
               ws_item_sk,
               ws_order_number,
               ws_quantity,
               ws_ext_sales_price
        FROM web_sales
        OFFSET 0
    ) AS ws
    JOIN category_items AS i ON i.i_item_sk = ws.ws_item_sk
    JOIN sales_dates AS d ON d.d_date_sk = ws.ws_sold_date_sk
    LEFT JOIN (
        SELECT wr_order_number,
               wr_item_sk,
               wr_return_quantity,
               wr_return_amt
        FROM web_returns
        OFFSET 0
    ) AS wr
      ON wr.wr_order_number = ws.ws_order_number
     AND wr.wr_item_sk = ws.ws_item_sk
),
year_comparison AS (
    SELECT i_brand_id,
           i_class_id,
           i_category_id,
           i_manufact_id,
           SUM(sales_cnt) FILTER (WHERE d_year = 2001) AS prev_yr_cnt,
           SUM(sales_cnt) FILTER (WHERE d_year = 2002) AS curr_yr_cnt,
           SUM(sales_amt) FILTER (WHERE d_year = 2001) AS prev_yr_amt,
           SUM(sales_amt) FILTER (WHERE d_year = 2002) AS curr_yr_amt
    FROM sales_detail
    GROUP BY i_brand_id, i_class_id, i_category_id, i_manufact_id
    HAVING COUNT(*) FILTER (WHERE d_year = 2001) > 0
       AND COUNT(*) FILTER (WHERE d_year = 2002) > 0
)
SELECT 2001 AS prev_year,
       2002 AS year,
       i_brand_id,
       i_class_id,
       i_category_id,
       i_manufact_id,
       prev_yr_cnt,
       curr_yr_cnt,
       curr_yr_cnt - prev_yr_cnt AS sales_cnt_diff,
       curr_yr_amt - prev_yr_amt AS sales_amt_diff
FROM year_comparison
WHERE CAST(curr_yr_cnt AS DECIMAL(17, 2))
        / CAST(prev_yr_cnt AS DECIMAL(17, 2)) < 0.9
ORDER BY sales_cnt_diff, sales_amt_diff
LIMIT 100;
