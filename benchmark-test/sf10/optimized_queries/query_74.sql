-- TPC-DS Query 74 optimized for PostgreSQL.
-- Aggregate each channel once, calculate both annual aggregates with
-- FILTER, and join the customer dimension only after the summaries are matched.

WITH store_yearly AS (
    SELECT
        ss.ss_customer_sk AS customer_sk,
        MAX(ss.ss_net_paid)
            FILTER (WHERE d.d_year = 1998) AS first_year_total,
        MAX(ss.ss_net_paid)
            FILTER (WHERE d.d_year = 1999) AS second_year_total
    FROM store_sales AS ss
    JOIN date_dim AS d ON d.d_date_sk = ss.ss_sold_date_sk
    WHERE d.d_year IN (1998, 1999)
      AND ss.ss_customer_sk IS NOT NULL
    GROUP BY ss.ss_customer_sk
    HAVING MAX(ss.ss_net_paid)
        FILTER (WHERE d.d_year = 1998) > 0
),
web_yearly AS (
    SELECT
        ws.ws_bill_customer_sk AS customer_sk,
        MAX(ws.ws_net_paid)
            FILTER (WHERE d.d_year = 1998) AS first_year_total,
        MAX(ws.ws_net_paid)
            FILTER (WHERE d.d_year = 1999) AS second_year_total
    FROM web_sales AS ws
    JOIN date_dim AS d ON d.d_date_sk = ws.ws_sold_date_sk
    WHERE d.d_year IN (1998, 1999)
      AND ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk
    HAVING MAX(ws.ws_net_paid)
        FILTER (WHERE d.d_year = 1998) > 0
)
SELECT
    c.c_customer_id AS customer_id,
    c.c_first_name AS customer_first_name,
    c.c_last_name AS customer_last_name
FROM store_yearly AS s
JOIN web_yearly AS w ON w.customer_sk = s.customer_sk
JOIN customer AS c ON c.c_customer_sk = s.customer_sk
WHERE w.second_year_total / w.first_year_total
        > s.second_year_total / s.first_year_total
ORDER BY
    c.c_last_name,
    c.c_customer_id,
    c.c_first_name
LIMIT 100;
