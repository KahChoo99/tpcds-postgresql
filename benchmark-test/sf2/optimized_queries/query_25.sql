-- TPC-DS Query 25 optimized for PostgreSQL.
-- Match the filtered store sale and return first, then summarize only catalog
-- customer/item pairs that can join. Weight all averages by the original
-- catalog join multiplicity, counting NULL profits only in the row count.

WITH matched_store_returns AS MATERIALIZED (
    SELECT ss.ss_item_sk AS item_sk,
           ss.ss_store_sk AS store_sk,
           ss.ss_customer_sk AS customer_sk,
           ss.ss_net_profit AS store_profit,
           sr.sr_net_loss AS return_loss
    FROM store_sales AS ss
    JOIN date_dim AS sold_date
      ON sold_date.d_date_sk = ss.ss_sold_date_sk
    JOIN store_returns AS sr
      ON sr.sr_customer_sk = ss.ss_customer_sk
     AND sr.sr_item_sk = ss.ss_item_sk
     AND sr.sr_ticket_number = ss.ss_ticket_number
    JOIN date_dim AS return_date
      ON return_date.d_date_sk = sr.sr_returned_date_sk
    WHERE sold_date.d_year = 1999
      AND sold_date.d_moy = 4
      AND return_date.d_year = 1999
      AND return_date.d_moy BETWEEN 4 AND 10
),
catalog_profit AS (
    SELECT cs.cs_bill_customer_sk AS customer_sk,
           cs.cs_item_sk AS item_sk,
           COUNT(*) AS catalog_row_count,
           SUM(cs.cs_net_profit) AS catalog_profit_sum,
           COUNT(cs.cs_net_profit) AS catalog_profit_count
    FROM catalog_sales AS cs
    JOIN date_dim AS sold_date
      ON sold_date.d_date_sk = cs.cs_sold_date_sk
    WHERE sold_date.d_year = 1999
      AND sold_date.d_moy BETWEEN 4 AND 10
      AND EXISTS (
          SELECT 1
          FROM matched_store_returns AS m
          WHERE m.customer_sk = cs.cs_bill_customer_sk
            AND m.item_sk = cs.cs_item_sk
      )
    GROUP BY cs.cs_bill_customer_sk, cs.cs_item_sk
)
SELECT i.i_item_id,
       i.i_item_desc,
       s.s_store_id,
       s.s_store_name,
       SUM(m.store_profit * c.catalog_row_count)
           / NULLIF(SUM(c.catalog_row_count)
               FILTER (WHERE m.store_profit IS NOT NULL), 0) AS store_sales_profit,
       SUM(m.return_loss * c.catalog_row_count)
           / NULLIF(SUM(c.catalog_row_count)
               FILTER (WHERE m.return_loss IS NOT NULL), 0) AS store_returns_loss,
       SUM(c.catalog_profit_sum)
           / NULLIF(SUM(c.catalog_profit_count), 0) AS catalog_sales_profit
FROM matched_store_returns AS m
JOIN catalog_profit AS c
  ON c.customer_sk = m.customer_sk
 AND c.item_sk = m.item_sk
JOIN item AS i ON i.i_item_sk = m.item_sk
JOIN store AS s ON s.s_store_sk = m.store_sk
GROUP BY i.i_item_id, i.i_item_desc, s.s_store_id, s.s_store_name
ORDER BY i.i_item_id, i.i_item_desc, s.s_store_id, s.s_store_name
LIMIT 100;
