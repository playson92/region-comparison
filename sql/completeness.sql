-- Authentic missing values and excluded flags stay visible in the complete observation grid.
SELECT year, indicator_id, quality_status, reason_code,
       COUNT(*) AS observation_count,
       COUNT(semantic_value) AS numeric_count
FROM observations
WHERE snapshot_id = :snapshot_id
GROUP BY year, indicator_id, quality_status, reason_code
ORDER BY year, indicator_id, quality_status, reason_code;
