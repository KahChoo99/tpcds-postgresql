-- Eight required indexes for the clustered-only scenario.
-- These are ordinary PostgreSQL indexes used by CLUSTER to reorder each table.
CREATE INDEX IF NOT EXISTS idx_store_sales_ss_customer_sk
ON store_sales (ss_customer_sk);

CREATE INDEX IF NOT EXISTS idx_ss_date_item
ON store_sales (ss_sold_date_sk, ss_item_sk);

CREATE INDEX IF NOT EXISTS idx_web_sales_ws_bill_customer_sk
ON web_sales (ws_bill_customer_sk);

CREATE INDEX IF NOT EXISTS idx_ws_date_item
ON web_sales (ws_sold_date_sk, ws_item_sk);

CREATE INDEX IF NOT EXISTS idx_catalog_sales_cs_sold_date_sk
ON catalog_sales (cs_sold_date_sk);

CREATE INDEX IF NOT EXISTS idx_cs_date_customer
ON catalog_sales (cs_sold_date_sk, cs_bill_customer_sk);

CREATE INDEX IF NOT EXISTS idx_cs_date_item
ON catalog_sales (cs_sold_date_sk, cs_item_sk);

CREATE INDEX IF NOT EXISTS idx_catalog_returns_cr_returned_date_sk
ON catalog_returns (cr_returned_date_sk);
