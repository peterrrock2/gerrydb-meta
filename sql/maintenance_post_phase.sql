-- Run after each bulk-load phase (geo / graph / pop): refreshes planner
-- statistics on the tables bulk loads touch. Autovacuum keeps up eventually,
-- but a phase can insert hundreds of millions of rows faster than autovacuum
-- reacts, leaving the next phase planning against stale statistics.
-- ANALYZE on the partitioned parent also analyzes every column_value
-- partition and builds parent-level statistics (autovacuum never does the
-- parent).

ANALYZE gerrydb.geography;
ANALYZE gerrydb.geo_version;
ANALYZE gerrydb.geo_bin;
ANALYZE gerrydb.geo_set_member;
ANALYZE gerrydb.geo_set_version;
ANALYZE gerrydb.graph;
ANALYZE gerrydb.graph_edge;
ANALYZE gerrydb.column_value;
ANALYZE gerrydb.column_value_count;
