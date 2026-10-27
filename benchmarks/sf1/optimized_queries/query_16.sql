SELECT COUNT(DISTINCT cs1.cs_order_number) AS "order count",
       SUM(cs1.cs_ext_ship_cost)           AS "total shipping cost",
       SUM(cs1.cs_net_profit)              AS "total net profit"
FROM catalog_sales cs1
JOIN date_dim d          ON cs1.cs_ship_date_sk = d.d_date_sk
JOIN customer_address ca ON cs1.cs_ship_addr_sk = ca.ca_address_sk
JOIN call_center cc      ON cs1.cs_call_center_sk = cc.cc_call_center_sk
WHERE d.d_date BETWEEN DATE '2001-03-01' AND DATE '2001-03-01' + 60
  AND ca.ca_state = 'KY'
  AND cc.cc_county = 'Williamson County'
  AND EXISTS (SELECT 1
              FROM catalog_sales cs2
              WHERE cs2.cs_order_number = cs1.cs_order_number
                AND cs2.cs_warehouse_sk <> cs1.cs_warehouse_sk)
  AND NOT EXISTS (SELECT 1
                  FROM catalog_returns cr1
                  WHERE cr1.cr_order_number = cs1.cs_order_number)
ORDER BY COUNT(DISTINCT cs1.cs_order_number)
LIMIT 100;