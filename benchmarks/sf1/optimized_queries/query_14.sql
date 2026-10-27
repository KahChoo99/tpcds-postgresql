WITH d_3yr AS (
    SELECT d_date_sk
    FROM date_dim
    WHERE d_year BETWEEN 1998 AND 1998 + 2
),
ss_3yr AS MATERIALIZED (
    SELECT ss_item_sk AS item_sk,
           SUM(ss_quantity * ss_list_price) AS s_sum,
           COUNT(ss_quantity * ss_list_price) AS s_cnt
    FROM store_sales
    JOIN d_3yr ON ss_sold_date_sk = d_date_sk
    GROUP BY ss_item_sk
),
cs_3yr AS MATERIALIZED (
    SELECT cs_item_sk AS item_sk,
           SUM(cs_quantity * cs_list_price) AS c_sum,
           COUNT(cs_quantity * cs_list_price) AS c_cnt
    FROM catalog_sales
    JOIN d_3yr ON cs_sold_date_sk = d_date_sk
    GROUP BY cs_item_sk
),
ws_3yr AS MATERIALIZED (
    SELECT ws_item_sk AS item_sk,
           SUM(ws_quantity * ws_list_price) AS w_sum,
           COUNT(ws_quantity * ws_list_price) AS w_cnt
    FROM web_sales
    JOIN d_3yr ON ws_sold_date_sk = d_date_sk
    GROUP BY ws_item_sk
),
cross_items AS MATERIALIZED (
    SELECT i.i_item_sk AS item_sk,
           i.i_brand_id,
           i.i_class_id,
           i.i_category_id
    FROM item i
    JOIN (
        SELECT iss.i_brand_id AS brand_id,
               iss.i_class_id AS class_id,
               iss.i_category_id AS category_id
        FROM ss_3yr s
        JOIN item iss ON s.item_sk = iss.i_item_sk
        INTERSECT
        SELECT ics.i_brand_id,
               ics.i_class_id,
               ics.i_category_id
        FROM cs_3yr c
        JOIN item ics ON c.item_sk = ics.i_item_sk
        INTERSECT
        SELECT iws.i_brand_id,
               iws.i_class_id,
               iws.i_category_id
        FROM ws_3yr w
        JOIN item iws ON w.item_sk = iws.i_item_sk
    ) x ON i.i_brand_id = x.brand_id
       AND i.i_class_id = x.class_id
       AND i.i_category_id = x.category_id
),
avg_sales AS MATERIALIZED (
    SELECT SUM(total_sum) / SUM(total_cnt) AS average_sales
    FROM (
        SELECT SUM(s_sum) AS total_sum, SUM(s_cnt) AS total_cnt FROM ss_3yr
        UNION ALL
        SELECT SUM(c_sum), SUM(c_cnt) FROM cs_3yr
        UNION ALL
        SELECT SUM(w_sum), SUM(w_cnt) FROM ws_3yr
    ) a
),
nov_2000_dates AS (
    SELECT d_date_sk
    FROM date_dim
    WHERE d_year = 1998 + 2
      AND d_moy = 11
)
SELECT channel,
       i_brand_id,
       i_class_id,
       i_category_id,
       SUM(sales),
       SUM(number_sales)
FROM (
    SELECT 'store' AS channel,
           ci.i_brand_id,
           ci.i_class_id,
           ci.i_category_id,
           SUM(ss.ss_quantity * ss.ss_list_price) AS sales,
           COUNT(*) AS number_sales
    FROM store_sales ss
    JOIN nov_2000_dates d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN cross_items ci ON ss.ss_item_sk = ci.item_sk
    GROUP BY ci.i_brand_id, ci.i_class_id, ci.i_category_id
    HAVING SUM(ss.ss_quantity * ss.ss_list_price) > (SELECT average_sales FROM avg_sales)
    UNION ALL
    SELECT 'catalog' AS channel,
           ci.i_brand_id,
           ci.i_class_id,
           ci.i_category_id,
           SUM(cs.cs_quantity * cs.cs_list_price) AS sales,
           COUNT(*) AS number_sales
    FROM catalog_sales cs
    JOIN nov_2000_dates d ON cs.cs_sold_date_sk = d.d_date_sk
    JOIN cross_items ci ON cs.cs_item_sk = ci.item_sk
    GROUP BY ci.i_brand_id, ci.i_class_id, ci.i_category_id
    HAVING SUM(cs.cs_quantity * cs.cs_list_price) > (SELECT average_sales FROM avg_sales)
    UNION ALL
    SELECT 'web' AS channel,
           ci.i_brand_id,
           ci.i_class_id,
           ci.i_category_id,
           SUM(ws.ws_quantity * ws.ws_list_price) AS sales,
           COUNT(*) AS number_sales
    FROM web_sales ws
    JOIN nov_2000_dates d ON ws.ws_sold_date_sk = d.d_date_sk
    JOIN cross_items ci ON ws.ws_item_sk = ci.item_sk
    GROUP BY ci.i_brand_id, ci.i_class_id, ci.i_category_id
    HAVING SUM(ws.ws_quantity * ws.ws_list_price) > (SELECT average_sales FROM avg_sales)
) y
GROUP BY ROLLUP (channel, i_brand_id, i_class_id, i_category_id)
ORDER BY channel, i_brand_id, i_class_id, i_category_id
LIMIT 100;

WITH d_3yr AS (
    SELECT d_date_sk
    FROM date_dim
    WHERE d_year BETWEEN 1998 AND 1998 + 2
),
ss_3yr AS MATERIALIZED (
    SELECT ss_item_sk AS item_sk,
           SUM(ss_quantity * ss_list_price) AS s_sum,
           COUNT(ss_quantity * ss_list_price) AS s_cnt
    FROM store_sales
    JOIN d_3yr ON ss_sold_date_sk = d_date_sk
    GROUP BY ss_item_sk
),
cs_3yr AS MATERIALIZED (
    SELECT cs_item_sk AS item_sk,
           SUM(cs_quantity * cs_list_price) AS c_sum,
           COUNT(cs_quantity * cs_list_price) AS c_cnt
    FROM catalog_sales
    JOIN d_3yr ON cs_sold_date_sk = d_date_sk
    GROUP BY cs_item_sk
),
ws_3yr AS MATERIALIZED (
    SELECT ws_item_sk AS item_sk,
           SUM(ws_quantity * ws_list_price) AS w_sum,
           COUNT(ws_quantity * ws_list_price) AS w_cnt
    FROM web_sales
    JOIN d_3yr ON ws_sold_date_sk = d_date_sk
    GROUP BY ws_item_sk
),
cross_items AS MATERIALIZED (
    SELECT i.i_item_sk AS item_sk,
           i.i_brand_id,
           i.i_class_id,
           i.i_category_id
    FROM item i
    JOIN (
        SELECT iss.i_brand_id AS brand_id,
               iss.i_class_id AS class_id,
               iss.i_category_id AS category_id
        FROM ss_3yr s
        JOIN item iss ON s.item_sk = iss.i_item_sk
        INTERSECT
        SELECT ics.i_brand_id,
               ics.i_class_id,
               ics.i_category_id
        FROM cs_3yr c
        JOIN item ics ON c.item_sk = ics.i_item_sk
        INTERSECT
        SELECT iws.i_brand_id,
               iws.i_class_id,
               iws.i_category_id
        FROM ws_3yr w
        JOIN item iws ON w.item_sk = iws.i_item_sk
    ) x ON i.i_brand_id = x.brand_id
       AND i.i_class_id = x.class_id
       AND i.i_category_id = x.category_id
),
avg_sales AS MATERIALIZED (
    SELECT SUM(total_sum) / SUM(total_cnt) AS average_sales
    FROM (
        SELECT SUM(s_sum) AS total_sum, SUM(s_cnt) AS total_cnt FROM ss_3yr
        UNION ALL
        SELECT SUM(c_sum), SUM(c_cnt) FROM cs_3yr
        UNION ALL
        SELECT SUM(w_sum), SUM(w_cnt) FROM ws_3yr
    ) a
),
target_weeks AS (
    SELECT (SELECT d_week_seq FROM date_dim WHERE d_year = 1998 + 1 AND d_moy = 12 AND d_dom = 22) AS ty_week,
           (SELECT d_week_seq FROM date_dim WHERE d_year = 1998 AND d_moy = 12 AND d_dom = 22) AS ly_week
)
SELECT 'store' AS ty_channel,
       ci.i_brand_id AS ty_brand,
       ci.i_class_id AS ty_class,
       ci.i_category_id AS ty_category,
       SUM(ss.ss_quantity * ss.ss_list_price) FILTER (WHERE d.d_week_seq = tw.ty_week) AS ty_sales,
       COUNT(*) FILTER (WHERE d.d_week_seq = tw.ty_week) AS ty_number_sales,
       'store' AS ly_channel,
       ci.i_brand_id AS ly_brand,
       ci.i_class_id AS ly_class,
       ci.i_category_id AS ly_category,
       SUM(ss.ss_quantity * ss.ss_list_price) FILTER (WHERE d.d_week_seq = tw.ly_week) AS ly_sales,
       COUNT(*) FILTER (WHERE d.d_week_seq = tw.ly_week) AS ly_number_sales
FROM store_sales ss
JOIN date_dim d ON ss.ss_sold_date_sk = d.d_date_sk
CROSS JOIN target_weeks tw
JOIN cross_items ci ON ss.ss_item_sk = ci.item_sk
WHERE d.d_week_seq IN (tw.ty_week, tw.ly_week)
GROUP BY ci.i_brand_id,
         ci.i_class_id,
         ci.i_category_id
HAVING SUM(ss.ss_quantity * ss.ss_list_price) FILTER (WHERE d.d_week_seq = tw.ty_week) > (SELECT average_sales FROM avg_sales)
   AND SUM(ss.ss_quantity * ss.ss_list_price) FILTER (WHERE d.d_week_seq = tw.ly_week) > (SELECT average_sales FROM avg_sales)
ORDER BY 1, 2, 3, 4
LIMIT 100;