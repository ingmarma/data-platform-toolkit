-- Daily Summary Report
-- Template: daily_summary
-- Parameters: date (YYYY-MM-DD), database_name
-- Description: Aggregated metrics for all datasets on a given date

SELECT
    table_name AS dataset,
    COUNT(*) AS total_records,
    COUNT(DISTINCT partition_date) AS partitions,
    SUM(CASE WHEN quality_score >= 0.8 THEN 1 ELSE 0 END) AS healthy_records,
    ROUND(
        CAST(SUM(CASE WHEN quality_score >= 0.8 THEN 1 ELSE 0 END) AS DOUBLE)
        / CAST(COUNT(*) AS DOUBLE) * 100,
        2
    ) AS health_pct,
    MIN(created_at) AS earliest_record,
    MAX(created_at) AS latest_record,
    ROUND(
        CAST(SUM(CASE WHEN id IS NULL OR id = '' THEN 1 ELSE 0 END) AS DOUBLE)
        / CAST(COUNT(*) AS DOUBLE) * 100,
        2
    ) AS null_id_pct
FROM "{{database_name}}"."data_catalog"
WHERE partition_date = {{date}}
GROUP BY table_name
ORDER BY total_records DESC
