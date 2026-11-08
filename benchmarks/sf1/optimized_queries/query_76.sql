
SELECT
    channel,
    col_name,
    d_year,
    d_qoy,
    i_category,
    SUM(sales_cnt) AS sales_cnt,
    SUM(sales_amt) AS sales_amt
FROM (
    SELECT
        'store' AS channel,
        'ss_cdemo_sk' AS col_name,
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*) AS sales_cnt,
        SUM(s.ss_ext_sales_price) AS sales_amt
    FROM store_sales s
    JOIN date_dim d ON s.ss_sold_date_sk = d.d_date_sk
    JOIN item i ON s.ss_item_sk = i.i_item_sk
    WHERE s.ss_cdemo_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category

    UNION ALL

    SELECT
        'web',
        'ws_bill_customer_sk',
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*),
        SUM(w.ws_ext_sales_price)
    FROM web_sales w
    JOIN date_dim d ON w.ws_sold_date_sk = d.d_date_sk
    JOIN item i ON w.ws_item_sk = i.i_item_sk
    WHERE w.ws_bill_customer_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category

    UNION ALL

    SELECT
        'catalog',
        'cs_bill_hdemo_sk',
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*),
        SUM(c.cs_ext_sales_price)
    FROM catalog_sales c
    JOIN date_dim d ON c.cs_sold_date_sk = d.d_date_sk
    JOIN item i ON c.cs_item_sk = i.i_item_sk
    WHERE c.cs_bill_hdemo_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category
) AS channel_aggregates
GROUP BY
    channel, col_name, d_year, d_qoy, i_category
ORDER BY
    channel, col_name, d_year, d_qoy, i_category
LIMIT 100;

