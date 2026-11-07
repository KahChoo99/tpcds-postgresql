WITH ss AS (
    SELECT
        ca.ca_county,
        SUM(ss.ss_ext_sales_price) FILTER (WHERE d.d_qoy = 1) AS store_q1,
        SUM(ss.ss_ext_sales_price) FILTER (WHERE d.d_qoy = 2) AS store_q2,
        SUM(ss.ss_ext_sales_price) FILTER (WHERE d.d_qoy = 3) AS store_q3
    FROM store_sales ss
    JOIN date_dim d
        ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN customer_address ca
        ON ss.ss_addr_sk = ca.ca_address_sk
    WHERE d.d_year = 2001
      AND d.d_qoy IN (1, 2, 3)
    GROUP BY ca.ca_county
    HAVING COUNT(*) FILTER (WHERE d.d_qoy = 1) > 0
       AND COUNT(*) FILTER (WHERE d.d_qoy = 2) > 0
       AND COUNT(*) FILTER (WHERE d.d_qoy = 3) > 0
),
ws AS (
    SELECT
        ca.ca_county,
        SUM(ws.ws_ext_sales_price) FILTER (WHERE d.d_qoy = 1) AS web_q1,
        SUM(ws.ws_ext_sales_price) FILTER (WHERE d.d_qoy = 2) AS web_q2,
        SUM(ws.ws_ext_sales_price) FILTER (WHERE d.d_qoy = 3) AS web_q3
    FROM web_sales ws
    JOIN date_dim d
        ON ws.ws_sold_date_sk = d.d_date_sk
    JOIN customer_address ca
        ON ws.ws_bill_addr_sk = ca.ca_address_sk
    WHERE d.d_year = 2001
      AND d.d_qoy IN (1, 2, 3)
    GROUP BY ca.ca_county
    HAVING COUNT(*) FILTER (WHERE d.d_qoy = 1) > 0
       AND COUNT(*) FILTER (WHERE d.d_qoy = 2) > 0
       AND COUNT(*) FILTER (WHERE d.d_qoy = 3) > 0
)
SELECT
    s.ca_county,
    2001 AS d_year,
    w.web_q2 / w.web_q1 AS web_q1_q2_increase,
    s.store_q2 / s.store_q1 AS store_q1_q2_increase,
    w.web_q3 / w.web_q2 AS web_q2_q3_increase,
    s.store_q3 / s.store_q2 AS store_q2_q3_increase
FROM ss s
JOIN ws w ON w.ca_county = s.ca_county
WHERE
    CASE WHEN w.web_q1 > 0
         THEN w.web_q2 / w.web_q1 END
    >
    CASE WHEN s.store_q1 > 0
         THEN s.store_q2 / s.store_q1 END
AND
    CASE WHEN w.web_q2 > 0
         THEN w.web_q3 / w.web_q2 END
    >
    CASE WHEN s.store_q2 > 0
         THEN s.store_q3 / s.store_q2 END
ORDER BY web_q1_q2_increase;