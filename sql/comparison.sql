-- Bound parameters: :snapshot_id, :year. Select 2–4 units in presentation only.
SELECT u.unit_id, u.name, u.kind, u.powiat, o.year, o.indicator_id,
       o.semantic_value, o.quality_status, o.reason_code, d.metadata
FROM observations o
JOIN unit_versions u USING (snapshot_id, unit_id)
JOIN indicator_definitions d USING (snapshot_id, indicator_id)
WHERE o.snapshot_id = :snapshot_id AND o.year = :year
ORDER BY u.unit_id, o.indicator_id;
