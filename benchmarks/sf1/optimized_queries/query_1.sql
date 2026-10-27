WITH customer_total_return AS (
    SELECT
        sr.sr_customer_sk AS ctr_customer_sk,
        sr.sr_store_sk    AS ctr_store_sk,
        SUM(sr.sr_return_amt) AS ctr_total_return
    FROM store_returns sr
    JOIN date_dim d ON sr.sr_returned_date_sk = d.d_date_sk
    JOIN store s    ON sr.sr_store_sk = s.s_store_sk
    WHERE d.d_year = 1998
      AND s.s_state = 'TN'
    GROUP BY sr.sr_customer_sk, sr.sr_store_sk
),
store_average AS (
    SELECT
        ctr_store_sk,
        AVG(ctr_total_return) AS avg_total_return
    FROM customer_total_return
    GROUP BY ctr_store_sk
)
SELECT c.c_customer_id
FROM customer_total_return ctr
JOIN customer c       ON c.c_customer_sk = ctr.ctr_customer_sk
JOIN store_average a  ON a.ctr_store_sk = ctr.ctr_store_sk
WHERE ctr.ctr_total_return > a.avg_total_return * 1.2
ORDER BY c.c_customer_id
LIMIT 100;