-- CLUSTER is physical table reordering; PostgreSQL does not have a
-- separate CREATE CLUSTERED INDEX syntax. Indexes remain regular indexes.
-- Run only after the corresponding indexes have been created.
CLUSTER catalog_sales USING idx_catalog_sales_cs_sold_date_sk;
CLUSTER catalog_returns USING idx_catalog_returns_cr_returned_date_sk;
CLUSTER store_sales USING idx_ss_date_item;
CLUSTER web_sales USING idx_ws_date_item;
