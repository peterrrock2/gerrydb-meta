-- Physically orders every column_value partition by its primary key
-- (col_id, geo_id, valid_from). Within a partition col_id is constant, so
-- this is effectively (geo_id, valid_from) order: the access pattern renders
-- scan. CLUSTER takes an ACCESS EXCLUSIVE lock per partition, so run this
-- only after a bulk load completes, never during serving.
--
-- Requires psql (\gexec runs each generated CLUSTER in its own transaction).

-- USING takes a bare index name (never schema-qualified).
SELECT format('CLUSTER %s USING %I', c.oid::regclass, ic.relname)
FROM pg_inherits h
JOIN pg_class c ON c.oid = h.inhrelid
JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary
JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE h.inhparent = 'gerrydb.column_value'::regclass
ORDER BY c.oid::regclass::text \gexec

ANALYZE gerrydb.column_value;
