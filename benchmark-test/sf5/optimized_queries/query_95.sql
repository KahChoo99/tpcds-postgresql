WITH filtered_ws AS MATERIALIZED (
    SELECT ws1.ws_order_number,
           ws1.ws_ext_ship_cost,
           ws1.ws_net_profit
    FROM web_sales ws1
    JOIN date_dim ON ws1.ws_ship_date_sk = d_date_sk
    JOIN customer_address ON ws1.ws_ship_addr_sk = ca_address_sk
    JOIN web_site ON ws1.ws_web_site_sk = web_site_sk
    WHERE d_date BETWEEN '1999-2-01' AND (CAST('1999-2-01' AS date) + 60)
      AND ca_state = 'AR'
      AND web_company_name = 'pri'
),
multi_wh_orders AS (
    SELECT ws_order_number
    FROM web_sales
    WHERE ws_order_number IN (SELECT ws_order_number FROM filtered_ws)
    GROUP BY ws_order_number
    HAVING COUNT(DISTINCT ws_warehouse_sk) > 1
)
SELECT COUNT(DISTINCT ws_order_number) AS "order count",
       SUM(ws_ext_ship_cost) AS "total shipping cost",
       SUM(ws_net_profit) AS "total net profit"
FROM filtered_ws
WHERE ws_order_number IN (SELECT ws_order_number FROM multi_wh_orders)
  AND ws_order_number IN (SELECT wr_order_number FROM web_returns)
ORDER BY COUNT(DISTINCT ws_order_number)
LIMIT 100;
