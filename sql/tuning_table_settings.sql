-- One-time per-table tuning (idempotent; re-running is harmless).
--
-- geo_set_member is hot on the read side (set-membership joins on every
-- render and stats write) but only ~17M rows, so the default 20% dead-tuple
-- threshold lets ~3.5M dead tuples pile up before autovacuum fires. Vacuum
-- at 5% instead.
ALTER TABLE gerrydb.geo_set_member SET (autovacuum_vacuum_scale_factor = 0.05);
