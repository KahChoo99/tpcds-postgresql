SELECT
    channel,
    col_name,
    d_year,
    d_qoy,
    i_category,
    sales_cnt,
    sales_amt
FROM (
    SELECT
        'store' AS channel,
        'ss_promo_sk' AS col_name,
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*) AS sales_cnt,
        SUM(s.ss_ext_sales_price) AS sales_amt
    FROM store_sales s
    JOIN date_dim d ON s.ss_sold_date_sk = d.d_date_sk
    JOIN item i ON s.ss_item_sk = i.i_item_sk
    WHERE s.ss_promo_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category

    UNION ALL

    SELECT
        'web' AS channel,
        'ws_ship_mode_sk' AS col_name,
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*) AS sales_cnt,
        SUM(w.ws_ext_sales_price) AS sales_amt
    FROM web_sales w
    JOIN date_dim d ON w.ws_sold_date_sk = d.d_date_sk
    JOIN item i ON w.ws_item_sk = i.i_item_sk
    WHERE w.ws_ship_mode_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category

    UNION ALL

    SELECT
        'catalog' AS channel,
        'cs_bill_hdemo_sk' AS col_name,
        d.d_year,
        d.d_qoy,
        i.i_category,
        COUNT(*) AS sales_cnt,
        SUM(c.cs_ext_sales_price) AS sales_amt
    FROM catalog_sales c
    JOIN date_dim d ON c.cs_sold_date_sk = d.d_date_sk
    JOIN item i ON c.cs_item_sk = i.i_item_sk
    WHERE c.cs_bill_hdemo_sk IS NULL
    GROUP BY d.d_year, d.d_qoy, i.i_category
) AS channel_aggregates
ORDER BY channel, col_name, d_year, d_qoy, i_category
LIMIT 100;