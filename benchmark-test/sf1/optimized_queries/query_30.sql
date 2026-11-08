-- TPC-DS Query 30 optimized for PostgreSQL.
-- Calculate each customer's annual return once, then calculate the state
-- average once with a window function instead of a correlated CTE scan.

WITH customer_total_return AS (
    SELECT
        wr.wr_returning_customer_sk AS customer_sk,
        ca.ca_state AS return_state,
        SUM(wr.wr_return_amt) AS total_return
    FROM web_returns AS wr
    JOIN date_dim AS d ON d.d_date_sk = wr.wr_returned_date_sk
    JOIN customer_address AS ca
      ON ca.ca_address_sk = wr.wr_returning_addr_sk
    WHERE d.d_year = 2002
      AND wr.wr_returning_customer_sk IS NOT NULL
      AND ca.ca_state IS NOT NULL
    GROUP BY
        wr.wr_returning_customer_sk,
        ca.ca_state
),
return_with_state_average AS (
    SELECT
        customer_sk,
        return_state,
        total_return,
        AVG(total_return) OVER (PARTITION BY return_state) AS state_average_return
    FROM customer_total_return
)
SELECT
    c.c_customer_id,
    c.c_salutation,
    c.c_first_name,
    c.c_last_name,
    c.c_preferred_cust_flag,
    c.c_birth_day,
    c.c_birth_month,
    c.c_birth_year,
    c.c_birth_country,
    c.c_login,
    c.c_email_address,
    c.c_last_review_date,
    r.total_return AS ctr_total_return
FROM return_with_state_average AS r
JOIN customer AS c ON c.c_customer_sk = r.customer_sk
JOIN customer_address AS current_address
  ON current_address.ca_address_sk = c.c_current_addr_sk
WHERE current_address.ca_state = 'TX'
  AND r.total_return > r.state_average_return * 1.2
ORDER BY
    c.c_customer_id,
    c.c_salutation,
    c.c_first_name,
    c.c_last_name,
    c.c_preferred_cust_flag,
    c.c_birth_day,
    c.c_birth_month,
    c.c_birth_year,
    c.c_birth_country,
    c.c_login,
    c.c_email_address,
    c.c_last_review_date,
    r.total_return
LIMIT 100;
