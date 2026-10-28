-- TPC-DS Query 17 optimized for PostgreSQL.
-- Materialize the narrow store/return matches before considering catalog rows.
-- The distinct key set filters catalog input without removing repeated fact rows.
-- Keep the native aggregates over the complete joined multiset.

WITH store_return_rows AS MATERIALIZED (
    SELECT ss.ss_item_sk AS item_sk,
           ss.ss_store_sk AS store_sk,
           sr.sr_customer_sk AS customer_sk,
           ss.ss_quantity,
           sr.sr_return_quantity
    FROM store_sales AS ss
    JOIN date_dim AS sold_date
      ON sold_date.d_date_sk = ss.ss_sold_date_sk
    JOIN store_returns AS sr
      ON sr.sr_customer_sk = ss.ss_customer_sk
     AND sr.sr_item_sk = ss.ss_item_sk
     AND sr.sr_ticket_number = ss.ss_ticket_number
    JOIN date_dim AS return_date
      ON return_date.d_date_sk = sr.sr_returned_date_sk
    WHERE sold_date.d_quarter_name = '1998Q1'
      AND return_date.d_quarter_name IN ('1998Q1', '1998Q2', '1998Q3')
),
matching_pairs AS MATERIALIZED (
    SELECT DISTINCT customer_sk, item_sk
    FROM store_return_rows
),
catalog_rows AS (
    SELECT cs.cs_bill_customer_sk AS customer_sk,
           cs.cs_item_sk AS item_sk,
           cs.cs_quantity
    FROM catalog_sales AS cs
    JOIN date_dim AS catalog_date
      ON catalog_date.d_date_sk = cs.cs_sold_date_sk
    JOIN matching_pairs AS pairs
      ON pairs.customer_sk = cs.cs_bill_customer_sk
     AND pairs.item_sk = cs.cs_item_sk
    WHERE catalog_date.d_quarter_name IN ('1998Q1', '1998Q2', '1998Q3')
)
SELECT i.i_item_id,
       i.i_item_desc,
       s.s_state,
       COUNT(r.ss_quantity) AS store_sales_quantitycount,
       AVG(r.ss_quantity) AS store_sales_quantityave,
       STDDEV_SAMP(r.ss_quantity) AS store_sales_quantitystdev,
       STDDEV_SAMP(r.ss_quantity) / AVG(r.ss_quantity) AS store_sales_quantitycov,
       COUNT(r.sr_return_quantity) AS store_returns_quantitycount,
       AVG(r.sr_return_quantity) AS store_returns_quantityave,
       STDDEV_SAMP(r.sr_return_quantity) AS store_returns_quantitystdev,
       STDDEV_SAMP(r.sr_return_quantity) / AVG(r.sr_return_quantity) AS store_returns_quantitycov,
       COUNT(cs.cs_quantity) AS catalog_sales_quantitycount,
       AVG(cs.cs_quantity) AS catalog_sales_quantityave,
       STDDEV_SAMP(cs.cs_quantity) AS catalog_sales_quantitystdev,
       STDDEV_SAMP(cs.cs_quantity) / AVG(cs.cs_quantity) AS catalog_sales_quantitycov
FROM store_return_rows AS r
JOIN catalog_rows AS cs
  ON cs.customer_sk = r.customer_sk
 AND cs.item_sk = r.item_sk
JOIN store AS s ON s.s_store_sk = r.store_sk
JOIN item AS i ON i.i_item_sk = r.item_sk
GROUP BY i.i_item_id,
         i.i_item_desc,
         s.s_state
ORDER BY i.i_item_id,
         i.i_item_desc,
         s.s_state
LIMIT 100;
