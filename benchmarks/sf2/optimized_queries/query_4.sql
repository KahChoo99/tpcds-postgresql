WITH store_agg AS (
    SELECT c_customer_id AS customer_id,
           c_first_name AS customer_first_name,
           c_last_name AS customer_last_name,
           c_birth_country AS customer_birth_country,
           SUM(CASE WHEN d_year = 1998 THEN ((ss_ext_list_price - ss_ext_wholesale_cost - ss_ext_discount_amt) + ss_ext_sales_price) / 2 END) AS s_firstyear,
           SUM(CASE WHEN d_year = 1998 + 1 THEN ((ss_ext_list_price - ss_ext_wholesale_cost - ss_ext_discount_amt) + ss_ext_sales_price) / 2 END) AS s_secyear
    FROM customer
    JOIN store_sales ON c_customer_sk = ss_customer_sk
    JOIN date_dim ON ss_sold_date_sk = d_date_sk
    WHERE d_year IN (1998, 1998 + 1)
    GROUP BY c_customer_id,
             c_first_name,
             c_last_name,
             c_preferred_cust_flag,
             c_birth_country,
             c_login,
             c_email_address
    HAVING SUM(CASE WHEN d_year = 1998 THEN ((ss_ext_list_price - ss_ext_wholesale_cost - ss_ext_discount_amt) + ss_ext_sales_price) / 2 END) > 0
       AND COUNT(CASE WHEN d_year = 1998 + 1 THEN 1 END) > 0
),
catalog_agg AS (
    SELECT c_customer_id AS customer_id,
           SUM(CASE WHEN d_year = 1998 THEN ((cs_ext_list_price - cs_ext_wholesale_cost - cs_ext_discount_amt) + cs_ext_sales_price) / 2 END) AS c_firstyear,
           SUM(CASE WHEN d_year = 1998 + 1 THEN ((cs_ext_list_price - cs_ext_wholesale_cost - cs_ext_discount_amt) + cs_ext_sales_price) / 2 END) AS c_secyear
    FROM customer
    JOIN catalog_sales ON c_customer_sk = cs_bill_customer_sk
    JOIN date_dim ON cs_sold_date_sk = d_date_sk
    WHERE d_year IN (1998, 1998 + 1)
    GROUP BY c_customer_id,
             c_first_name,
             c_last_name,
             c_preferred_cust_flag,
             c_birth_country,
             c_login,
             c_email_address
    HAVING SUM(CASE WHEN d_year = 1998 THEN ((cs_ext_list_price - cs_ext_wholesale_cost - cs_ext_discount_amt) + cs_ext_sales_price) / 2 END) > 0
       AND COUNT(CASE WHEN d_year = 1998 + 1 THEN 1 END) > 0
),
web_agg AS (
    SELECT c_customer_id AS customer_id,
           SUM(CASE WHEN d_year = 1998 THEN ((ws_ext_list_price - ws_ext_wholesale_cost - ws_ext_discount_amt) + ws_ext_sales_price) / 2 END) AS w_firstyear,
           SUM(CASE WHEN d_year = 1998 + 1 THEN ((ws_ext_list_price - ws_ext_wholesale_cost - ws_ext_discount_amt) + ws_ext_sales_price) / 2 END) AS w_secyear
    FROM customer
    JOIN web_sales ON c_customer_sk = ws_bill_customer_sk
    JOIN date_dim ON ws_sold_date_sk = d_date_sk
    WHERE d_year IN (1998, 1998 + 1)
    GROUP BY c_customer_id,
             c_first_name,
             c_last_name,
             c_preferred_cust_flag,
             c_birth_country,
             c_login,
             c_email_address
    HAVING SUM(CASE WHEN d_year = 1998 THEN ((ws_ext_list_price - ws_ext_wholesale_cost - ws_ext_discount_amt) + ws_ext_sales_price) / 2 END) > 0
       AND COUNT(CASE WHEN d_year = 1998 + 1 THEN 1 END) > 0
)
SELECT s.customer_id,
       s.customer_first_name,
       s.customer_last_name,
       s.customer_birth_country
FROM store_agg s
JOIN catalog_agg c ON s.customer_id = c.customer_id
JOIN web_agg w ON s.customer_id = w.customer_id
WHERE (c.c_secyear / c.c_firstyear) > (s.s_secyear / s.s_firstyear)
  AND (c.c_secyear / c.c_firstyear) > (w.w_secyear / w.w_firstyear)
ORDER BY s.customer_id,
         s.customer_first_name,
         s.customer_last_name,
         s.customer_birth_country
LIMIT 100;