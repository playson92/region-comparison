-- Bound parameters; the UI breaks lines when semantic_value is NULL or the flag blocks analysis.
SELECT year, indicator_id, semantic_value, quality_status, reason_code,
       raw_value, raw_attr_id, source_file, source_record
FROM observations
WHERE snapshot_id = :snapshot_id AND unit_id = :unit_id
ORDER BY indicator_id, year;
