-- READ-ONLY verification of *effective* PostgreSQL settings in THIS connection.
SELECT current_database() AS database, version() AS postgres_version;

SELECT
    name,
    current_setting(name) AS effective_value,
    CASE WHEN name IN ('shared_buffers','effective_cache_size','work_mem')
         THEN pg_size_bytes(current_setting(name))/1024 END AS effective_kb,
    source,
    context,
    pending_restart
FROM pg_settings
WHERE name IN (
    'effective_cache_size', 'jit', 'max_parallel_workers_per_gather',
    'random_page_cost', 'shared_buffers', 'work_mem'
)
ORDER BY name;

-- ANALYZE status, including web_sales, catalog_sales and store_sales.
SELECT relname AS table_name,
       (last_analyze IS NOT NULL OR last_autoanalyze IS NOT NULL) AS analyzed,
       last_analyze,
       last_autoanalyze
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY relname;
