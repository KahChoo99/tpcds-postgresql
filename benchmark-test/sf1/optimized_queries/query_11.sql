-- TPC-DS Query 11 optimized for PostgreSQL.
-- Aggregate each channel once, pivot the two years with FILTER, and defer the
-- customer dimension join until after the channel summaries are matched.

WITH store_yearly AS (
    SELECT
        ss.ss_customer_sk AS customer_sk,
        SUM(ss.ss_ext_list_price - ss.ss_ext_discount_amt)
            FILTER (WHERE d.d_year = 2000) AS first_year_total,
        SUM(ss.ss_ext_list_price - ss.ss_ext_discount_amt)
            FILTER (WHERE d.d_year = 2001) AS second_year_total
    FROM store_sales AS ss
    JOIN date_dim AS d ON d.d_date_sk = ss.ss_sold_date_sk
    WHERE d.d_year IN (2000, 2001)
      AND ss.ss_customer_sk IS NOT NULL
    GROUP BY ss.ss_customer_sk
    HAVING SUM(ss.ss_ext_list_price - ss.ss_ext_discount_amt)
        FILTER (WHERE d.d_year = 2000) > 0
),
web_yearly AS (
    SELECT
        ws.ws_bill_customer_sk AS customer_sk,
        SUM(ws.ws_ext_list_price - ws.ws_ext_discount_amt)
            FILTER (WHERE d.d_year = 2000) AS first_year_total,
        SUM(ws.ws_ext_list_price - ws.ws_ext_discount_amt)
            FILTER (WHERE d.d_year = 2001) AS second_year_total
    FROM web_sales AS ws
    JOIN date_dim AS d ON d.d_date_sk = ws.ws_sold_date_sk
    WHERE d.d_year IN (2000, 2001)
      AND ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk
    HAVING SUM(ws.ws_ext_list_price - ws.ws_ext_discount_amt)
        FILTER (WHERE d.d_year = 2000) > 0
)
SELECT
    c.c_customer_id AS customer_id,
    c.c_first_name AS customer_first_name,
    c.c_last_name AS customer_last_name,
    c.c_login AS customer_login
FROM store_yearly AS s
JOIN web_yearly AS w ON w.customer_sk = s.customer_sk
JOIN customer AS c ON c.c_customer_sk = s.customer_sk
WHERE w.second_year_total / w.first_year_total
        > s.second_year_total / s.first_year_total
ORDER BY
    c.c_customer_id,
    c.c_first_name,
    c.c_last_name,
    c.c_login
LIMIT 100;
