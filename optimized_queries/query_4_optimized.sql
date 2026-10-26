-- TPC-DS Query 4 optimized for PostgreSQL.
--
-- FILTER deliberately has no ELSE 0. If a customer has no qualifying row in
-- 1999, the second-year total stays NULL and the ratio predicate rejects it,
-- matching the inner-join semantics of the original query.

WITH store_yearly AS (
    SELECT
        ss.ss_customer_sk AS customer_sk,
        SUM(
            ((ss.ss_ext_list_price - ss.ss_ext_wholesale_cost
              - ss.ss_ext_discount_amt) + ss.ss_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1998) AS first_year_total,
        SUM(
            ((ss.ss_ext_list_price - ss.ss_ext_wholesale_cost
              - ss.ss_ext_discount_amt) + ss.ss_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1999) AS second_year_total
    FROM store_sales AS ss
    JOIN date_dim AS d ON d.d_date_sk = ss.ss_sold_date_sk
    WHERE d.d_year IN (1998, 1999)
      AND ss.ss_customer_sk IS NOT NULL
    GROUP BY ss.ss_customer_sk
    HAVING SUM(
        ((ss.ss_ext_list_price - ss.ss_ext_wholesale_cost
          - ss.ss_ext_discount_amt) + ss.ss_ext_sales_price) / 2
    ) FILTER (WHERE d.d_year = 1998) > 0
),
catalog_yearly AS (
    SELECT
        cs.cs_bill_customer_sk AS customer_sk,
        SUM(
            ((cs.cs_ext_list_price - cs.cs_ext_wholesale_cost
              - cs.cs_ext_discount_amt) + cs.cs_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1998) AS first_year_total,
        SUM(
            ((cs.cs_ext_list_price - cs.cs_ext_wholesale_cost
              - cs.cs_ext_discount_amt) + cs.cs_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1999) AS second_year_total
    FROM catalog_sales AS cs
    JOIN date_dim AS d ON d.d_date_sk = cs.cs_sold_date_sk
    WHERE d.d_year IN (1998, 1999)
      AND cs.cs_bill_customer_sk IS NOT NULL
    GROUP BY cs.cs_bill_customer_sk
    HAVING SUM(
        ((cs.cs_ext_list_price - cs.cs_ext_wholesale_cost
          - cs.cs_ext_discount_amt) + cs.cs_ext_sales_price) / 2
    ) FILTER (WHERE d.d_year = 1998) > 0
),
web_yearly AS (
    SELECT
        ws.ws_bill_customer_sk AS customer_sk,
        SUM(
            ((ws.ws_ext_list_price - ws.ws_ext_wholesale_cost
              - ws.ws_ext_discount_amt) + ws.ws_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1998) AS first_year_total,
        SUM(
            ((ws.ws_ext_list_price - ws.ws_ext_wholesale_cost
              - ws.ws_ext_discount_amt) + ws.ws_ext_sales_price) / 2
        ) FILTER (WHERE d.d_year = 1999) AS second_year_total
    FROM web_sales AS ws
    JOIN date_dim AS d ON d.d_date_sk = ws.ws_sold_date_sk
    WHERE d.d_year IN (1998, 1999)
      AND ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk
    HAVING SUM(
        ((ws.ws_ext_list_price - ws.ws_ext_wholesale_cost
          - ws.ws_ext_discount_amt) + ws.ws_ext_sales_price) / 2
    ) FILTER (WHERE d.d_year = 1998) > 0
)
SELECT
    c.c_customer_id AS customer_id,
    c.c_first_name AS customer_first_name,
    c.c_last_name AS customer_last_name,
    c.c_birth_country AS customer_birth_country
FROM store_yearly AS s
JOIN catalog_yearly AS cat ON cat.customer_sk = s.customer_sk
JOIN web_yearly AS w ON w.customer_sk = s.customer_sk
JOIN customer AS c ON c.c_customer_sk = s.customer_sk
WHERE cat.second_year_total / cat.first_year_total
        > s.second_year_total / s.first_year_total
  AND cat.second_year_total / cat.first_year_total
        > w.second_year_total / w.first_year_total
ORDER BY
    c.c_customer_id,
    c.c_first_name,
    c.c_last_name,
    c.c_birth_country
LIMIT 100;
