WITH cat_avg AS (
    SELECT i_category,
           AVG(i_current_price) AS avg_price
    FROM item
    GROUP BY i_category
)
SELECT a.ca_state AS state,
       COUNT(*)   AS cnt
FROM customer_address a
JOIN customer c    ON a.ca_address_sk = c.c_current_addr_sk
JOIN store_sales s ON c.c_customer_sk = s.ss_customer_sk
JOIN date_dim d    ON s.ss_sold_date_sk = d.d_date_sk
JOIN item i        ON s.ss_item_sk = i.i_item_sk
JOIN cat_avg ca    ON ca.i_category = i.i_category
WHERE d.d_month_seq = (SELECT DISTINCT d_month_seq
                       FROM date_dim
                       WHERE d_year = 2000
                         AND d_moy = 2)
  AND i.i_current_price > 1.2 * ca.avg_price
GROUP BY a.ca_state
HAVING COUNT(*) >= 10
ORDER BY cnt, a.ca_state
LIMIT 100;