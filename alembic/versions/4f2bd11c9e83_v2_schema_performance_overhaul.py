"""v2 schema: geometry dedup, column-value partitioning, and performance overhaul.

* column_value: rebuilt LIST-partitioned by col_id, composite primary key
  (col_id, geo_id, valid_from); val_id and val_json are gone.
* New tables: geo_bin (deduplicated geometries, md5 generated column), column_value_count
  (validation stats), view_geo_set_versions (replaces view.set_version_id), graph_render,
  namespace_limit, plan_limit.
* Targeted changes: geo_version trades its inline geography column for a geo_bin_id FK;
  geo_set_version gains namespace_id; geography paths are unique per namespace; plan gains
  complete; plan_assignment gains its missing FK; user_group names are unique; etag uniqueness
  treats NULL namespaces as equal.

Revision ID: 4f2bd11c9e83
Revises: cc9d1f7f2a11
Create Date: 2026-07-05

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4f2bd11c9e83"
down_revision = "cc9d1f7f2a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- column_value: rebuild as partitioned (per-column LIST partitions
    # are attached at column-creation time by the application).
    op.execute("DROP TABLE gerrydb.column_value CASCADE")
    op.execute(
        "CREATE TYPE public.graphrenderstatus AS ENUM ('PENDING', 'RUNNING', 'FAILED', 'SUCCEEDED')"
    )
    op.execute(
        "CREATE TABLE gerrydb.column_value (\n    col_id integer NOT NULL,\n    geo_id integer NOT NULL,\n    meta_id integer NOT NULL,\n    valid_from timestamp with time zone NOT NULL,\n    valid_to timestamp with time zone,\n    val_float double precision,\n    val_int bigint,\n    val_str text,\n    val_bool boolean\n)\nPARTITION BY LIST (col_id);"
    )
    op.execute("ALTER TABLE gerrydb.column_value OWNER TO postgres;")
    op.execute(
        "CREATE TABLE gerrydb.column_value_count (\n    col_id integer NOT NULL,\n    set_version_id integer NOT NULL,\n    count bigint NOT NULL\n);"
    )
    op.execute("ALTER TABLE gerrydb.column_value_count OWNER TO postgres;")
    op.execute(
        "CREATE TABLE gerrydb.geo_bin (\n    geo_bin_id integer NOT NULL,\n    geography public.geography(Geometry,4269),\n    geometry_hash bytea GENERATED ALWAYS AS (decode(md5(public.st_asbinary(geography)), 'hex'::text)) STORED\n);"
    )
    op.execute("ALTER TABLE gerrydb.geo_bin OWNER TO postgres;")
    op.execute(
        "CREATE SEQUENCE gerrydb.geo_bin_geo_bin_id_seq\n    AS integer\n    START WITH 1\n    INCREMENT BY 1\n    NO MINVALUE\n    NO MAXVALUE\n    CACHE 1;"
    )
    op.execute("ALTER SEQUENCE gerrydb.geo_bin_geo_bin_id_seq OWNER TO postgres;")
    op.execute("ALTER SEQUENCE gerrydb.geo_bin_geo_bin_id_seq OWNED BY gerrydb.geo_bin.geo_bin_id;")
    op.execute(
        "CREATE TABLE gerrydb.graph_render (\n    render_id uuid NOT NULL,\n    graph_id integer NOT NULL,\n    created_at timestamp with time zone DEFAULT now() NOT NULL,\n    created_by integer NOT NULL,\n    path text NOT NULL,\n    status public.graphrenderstatus NOT NULL\n);"
    )
    op.execute("ALTER TABLE gerrydb.graph_render OWNER TO postgres;")
    op.execute(
        "CREATE TABLE gerrydb.namespace_limit (\n    user_id integer NOT NULL,\n    max_ns_creation integer,\n    curr_creation_count integer NOT NULL\n);"
    )
    op.execute("ALTER TABLE gerrydb.namespace_limit OWNER TO postgres;")
    op.execute(
        "CREATE TABLE gerrydb.plan_limit (\n    namespace_id integer NOT NULL,\n    loc_id integer NOT NULL,\n    layer_id integer NOT NULL,\n    max_plans integer NOT NULL\n);"
    )
    op.execute("ALTER TABLE gerrydb.plan_limit OWNER TO postgres;")
    op.execute(
        "CREATE TABLE gerrydb.view_geo_set_versions (\n    view_id integer NOT NULL,\n    set_version_id integer NOT NULL\n);"
    )
    op.execute("ALTER TABLE gerrydb.view_geo_set_versions OWNER TO postgres;")
    op.execute(
        "ALTER TABLE ONLY gerrydb.geo_bin ALTER COLUMN geo_bin_id SET DEFAULT nextval('gerrydb.geo_bin_geo_bin_id_seq'::regclass);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value_count\n    ADD CONSTRAINT column_value_count_pkey PRIMARY KEY (col_id, set_version_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_pkey PRIMARY KEY (col_id, geo_id, valid_from);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.geo_bin\n    ADD CONSTRAINT geo_bin_pkey PRIMARY KEY (geo_bin_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.graph_render\n    ADD CONSTRAINT graph_render_pkey PRIMARY KEY (render_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.namespace_limit\n    ADD CONSTRAINT namespace_limit_pkey PRIMARY KEY (user_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.plan_limit\n    ADD CONSTRAINT plan_limit_pkey PRIMARY KEY (namespace_id, loc_id, layer_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.geo_bin\n    ADD CONSTRAINT uq_geo_bin_geometry_hash UNIQUE (geometry_hash);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.view_geo_set_versions\n    ADD CONSTRAINT view_geo_set_versions_pkey PRIMARY KEY (view_id, set_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_column_value_geo_id_valid_from ON ONLY gerrydb.column_value USING btree (geo_id, valid_from);"
    )
    op.execute(
        "CREATE INDEX ix_column_value_geo_id_valid_to ON ONLY gerrydb.column_value USING btree (geo_id, valid_to);"
    )
    op.execute(
        'ALTER TABLE gerrydb.column_value\n    ADD CONSTRAINT column_value_col_id_fkey FOREIGN KEY (col_id) REFERENCES gerrydb."column"(col_id);'
    )
    op.execute(
        'ALTER TABLE ONLY gerrydb.column_value_count\n    ADD CONSTRAINT column_value_count_col_id_fkey FOREIGN KEY (col_id) REFERENCES gerrydb."column"(col_id);'
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value_count\n    ADD CONSTRAINT column_value_count_set_version_id_fkey FOREIGN KEY (set_version_id) REFERENCES gerrydb.geo_set_version(set_version_id);"
    )
    op.execute(
        "ALTER TABLE gerrydb.column_value\n    ADD CONSTRAINT column_value_geo_id_fkey FOREIGN KEY (geo_id) REFERENCES gerrydb.geography(geo_id);"
    )
    op.execute(
        "ALTER TABLE gerrydb.column_value\n    ADD CONSTRAINT column_value_meta_id_fkey FOREIGN KEY (meta_id) REFERENCES gerrydb.meta(meta_id);"
    )
    op.execute(
        'ALTER TABLE ONLY gerrydb.graph_render\n    ADD CONSTRAINT graph_render_created_by_fkey FOREIGN KEY (created_by) REFERENCES gerrydb."user"(user_id);'
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.graph_render\n    ADD CONSTRAINT graph_render_graph_id_fkey FOREIGN KEY (graph_id) REFERENCES gerrydb.graph(graph_id);"
    )
    op.execute(
        'ALTER TABLE ONLY gerrydb.namespace_limit\n    ADD CONSTRAINT namespace_limit_user_id_fkey FOREIGN KEY (user_id) REFERENCES gerrydb."user"(user_id);'
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.plan_limit\n    ADD CONSTRAINT plan_limit_layer_id_fkey FOREIGN KEY (layer_id) REFERENCES gerrydb.geo_layer(layer_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.plan_limit\n    ADD CONSTRAINT plan_limit_loc_id_fkey FOREIGN KEY (loc_id) REFERENCES gerrydb.locality(loc_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.plan_limit\n    ADD CONSTRAINT plan_limit_namespace_id_fkey FOREIGN KEY (namespace_id) REFERENCES gerrydb.namespace(namespace_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.view_geo_set_versions\n    ADD CONSTRAINT view_geo_set_versions_set_version_id_fkey FOREIGN KEY (set_version_id) REFERENCES gerrydb.geo_set_version(set_version_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.view_geo_set_versions\n    ADD CONSTRAINT view_geo_set_versions_view_id_fkey FOREIGN KEY (view_id) REFERENCES gerrydb.view(view_id);"
    )

    # -- etag: allow one namespace-NULL (global) row per table name.
    op.execute("ALTER TABLE gerrydb.etag DROP CONSTRAINT etag_namespace_id_table_key")
    op.execute('ALTER TABLE gerrydb.etag ADD UNIQUE NULLS NOT DISTINCT (namespace_id, "table")')

    # -- geo_set_version: namespace scoping (metadata-only set resolution).
    op.execute("ALTER TABLE gerrydb.geo_set_version ADD COLUMN namespace_id integer NOT NULL")
    op.execute(
        "ALTER TABLE gerrydb.geo_set_version ADD FOREIGN KEY (namespace_id)"
        " REFERENCES gerrydb.namespace (namespace_id)"
    )
    op.execute(
        "CREATE INDEX ix_gerrydb_geo_set_version_namespace_id"
        " ON gerrydb.geo_set_version (namespace_id)"
    )

    # -- geo_version: geometry moves to deduplicated geo_bin rows.
    op.execute("DROP INDEX gerrydb.idx_geo_version_geography")
    op.execute("DROP INDEX gerrydb.idx_geo_version_internal_point")
    op.execute("DROP INDEX gerrydb.geo_version_geo_id")
    op.execute("DROP INDEX gerrydb.ix_geo_version_geo_id_valid_from")
    op.execute("ALTER TABLE gerrydb.geo_version DROP COLUMN geography")
    op.execute("ALTER TABLE gerrydb.geo_version ADD COLUMN geo_bin_id integer")
    op.execute(
        "ALTER TABLE gerrydb.geo_version ADD FOREIGN KEY (geo_bin_id)"
        " REFERENCES gerrydb.geo_bin (geo_bin_id)"
    )
    op.execute(
        "CREATE INDEX ix_geo_version_geo_id_valid_from ON gerrydb.geo_version (geo_id, valid_from)"
    )

    # -- geography: enforce per-namespace path uniqueness.
    op.execute("ALTER TABLE gerrydb.geography ADD UNIQUE (path, namespace_id)")
    op.execute("CREATE INDEX ix_gerrydb_geography_namespace_id ON gerrydb.geography (namespace_id)")

    # -- plans: completeness flag and the previously missing plan FK.
    op.execute("ALTER TABLE gerrydb.plan ADD COLUMN complete boolean NOT NULL")
    op.execute(
        "ALTER TABLE gerrydb.plan_assignment ADD FOREIGN KEY (plan_id)"
        " REFERENCES gerrydb.plan (plan_id)"
    )

    # -- user_group: names are unique.
    op.execute("ALTER TABLE gerrydb.user_group ADD UNIQUE (name)")

    # -- view: single set_version pointer replaced by view_geo_set_versions.
    op.execute("ALTER TABLE gerrydb.view DROP CONSTRAINT view_set_version_id_fkey")
    op.execute("ALTER TABLE gerrydb.view DROP COLUMN set_version_id")


def downgrade() -> None:
    op.execute("DROP TABLE gerrydb.column_value CASCADE")
    op.execute("DROP TABLE gerrydb.column_value_count")
    op.execute("DROP TABLE gerrydb.view_geo_set_versions")
    op.execute("DROP TABLE gerrydb.graph_render")
    op.execute("DROP TABLE gerrydb.namespace_limit")
    op.execute("DROP TABLE gerrydb.plan_limit")
    op.execute("DROP TYPE public.graphrenderstatus")

    op.execute("ALTER TABLE gerrydb.view ADD COLUMN set_version_id integer")
    op.execute(
        "ALTER TABLE gerrydb.view ADD CONSTRAINT view_set_version_id_fkey"
        " FOREIGN KEY (set_version_id) REFERENCES gerrydb.geo_set_version (set_version_id)"
    )
    op.execute("ALTER TABLE gerrydb.user_group DROP CONSTRAINT user_group_name_key")
    op.execute("ALTER TABLE gerrydb.plan_assignment DROP CONSTRAINT plan_assignment_plan_id_fkey")
    op.execute("ALTER TABLE gerrydb.plan DROP COLUMN complete")
    op.execute("ALTER TABLE gerrydb.geography DROP CONSTRAINT geography_path_namespace_id_key")
    op.execute("DROP INDEX gerrydb.ix_gerrydb_geography_namespace_id")
    op.execute("DROP INDEX gerrydb.ix_geo_version_geo_id_valid_from")
    op.execute("ALTER TABLE gerrydb.geo_version DROP COLUMN geo_bin_id")
    op.execute(
        "ALTER TABLE gerrydb.geo_version ADD COLUMN geography public.geography(Geometry,4269)"
    )
    op.execute(
        "CREATE INDEX idx_geo_version_geography ON gerrydb.geo_version USING gist (geography)"
    )
    op.execute(
        "CREATE INDEX idx_geo_version_internal_point ON gerrydb.geo_version USING gist (internal_point)"
    )
    op.execute("CREATE INDEX geo_version_geo_id ON gerrydb.geo_version (geo_id)")
    op.execute(
        "CREATE INDEX ix_geo_version_geo_id_valid_from"
        " ON gerrydb.geo_version (geo_id, valid_from DESC)"
    )
    op.execute("DROP INDEX gerrydb.ix_gerrydb_geo_set_version_namespace_id")
    op.execute("ALTER TABLE gerrydb.geo_set_version DROP COLUMN namespace_id")
    op.execute("ALTER TABLE gerrydb.etag DROP CONSTRAINT etag_namespace_id_table_key")
    op.execute('ALTER TABLE gerrydb.etag ADD UNIQUE (namespace_id, "table")')

    op.execute(
        "ALTER TABLE gerrydb.geo_version DROP CONSTRAINT IF EXISTS geo_version_geo_bin_id_fkey"
    )
    op.execute("DROP TABLE gerrydb.geo_bin")
    op.execute(
        "CREATE TABLE gerrydb.column_value (\n    val_id bigint NOT NULL,\n    col_id integer NOT NULL,\n    geo_id integer NOT NULL,\n    meta_id integer NOT NULL,\n    valid_from timestamp with time zone NOT NULL,\n    valid_to timestamp with time zone,\n    val_float double precision,\n    val_int bigint,\n    val_str text,\n    val_bool boolean,\n    val_json jsonb\n);"
    )
    op.execute("ALTER TABLE gerrydb.column_value OWNER TO postgres;")
    op.execute(
        "CREATE SEQUENCE gerrydb.column_value_val_id_seq\n    START WITH 1\n    INCREMENT BY 1\n    NO MINVALUE\n    NO MAXVALUE\n    CACHE 1;"
    )
    op.execute("ALTER SEQUENCE gerrydb.column_value_val_id_seq OWNER TO postgres;")
    op.execute(
        "ALTER SEQUENCE gerrydb.column_value_val_id_seq OWNED BY gerrydb.column_value.val_id;"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value ALTER COLUMN val_id SET DEFAULT nextval('gerrydb.column_value_val_id_seq'::regclass);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_col_id_geo_id_valid_from_key UNIQUE (col_id, geo_id, valid_from);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_pkey PRIMARY KEY (val_id);"
    )
    op.execute(
        "CREATE INDEX ix_column_value_geo_id_valid_from ON gerrydb.column_value USING btree (geo_id, valid_from DESC);"
    )
    op.execute(
        "CREATE INDEX ix_column_value_geo_id_valid_to ON gerrydb.column_value USING btree (geo_id, valid_to);"
    )
    op.execute(
        'ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_col_id_fkey FOREIGN KEY (col_id) REFERENCES gerrydb."column"(col_id);'
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_geo_id_fkey FOREIGN KEY (geo_id) REFERENCES gerrydb.geography(geo_id);"
    )
    op.execute(
        "ALTER TABLE ONLY gerrydb.column_value\n    ADD CONSTRAINT column_value_meta_id_fkey FOREIGN KEY (meta_id) REFERENCES gerrydb.meta(meta_id);"
    )
