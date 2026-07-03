"""Extended GeoPackage rendering of views."""

import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import orjson as json
from uvicorn.config import logger as log

from gerrydb_meta.crud.graph import GraphRenderContext
from gerrydb_meta.crud.view import ViewRenderContext
from gerrydb_meta.schemas import GraphMeta, ObjectMeta, ViewMeta

# For bulk exports, we wrap the command-line utility `ogr2ogr` (distributed with GDAL)
# to generate a GeoPackage with geographies and tabular data directly from the
# PostGIS database; SQLAlchemy is only used to generate the query that `ogr2ogr` runs.
# We then treat the GeoPackage export as a regular SQLite database and inject metadata.
#
# The CLI/subprocess dependency is slightly annoying (and potentially a cause for
# security concerns--ideally, ogr2ogr should be granted only read access to the database),
# but empirical evidence suggests that using `ogr2ogr` is *much* faster and less
# memory-intensive than loading geographies with SQLAlchemy/GeoAlchemy.


class RenderError(Exception):
    """Raised when rendering a view fails."""


def _ogr2ogr_common_args() -> list[str]:
    """Builds shared tuning arguments for ogr2ogr transfer performance."""
    args = []

    pg_cursor_page = os.getenv("GERRYDB_OGR_PG_CURSOR_PAGE", "50000")
    if pg_cursor_page:
        args.extend(["--config", "OGR_PG_CURSOR_PAGE", pg_cursor_page])

    sqlite_sync = os.getenv("GERRYDB_OGR_SQLITE_SYNCHRONOUS", "OFF")
    if sqlite_sync:
        args.extend(["--config", "OGR_SQLITE_SYNCHRONOUS", sqlite_sync])

    sqlite_pragma = os.getenv(
        "GERRYDB_OGR_SQLITE_PRAGMA",
        "journal_mode=OFF,temp_store=MEMORY,cache_size=-262144,locking_mode=EXCLUSIVE",
    )
    if sqlite_pragma:
        args.extend(["--config", "OGR_SQLITE_PRAGMA", sqlite_pragma])

    group_size = os.getenv("GERRYDB_OGR2OGR_GROUP_SIZE", "65536")
    if group_size:
        args.extend(["-gt", group_size])

    return args


def _ogr2ogr_sql_args(query: str) -> list[str]:
    """Builds SQL arguments for server-side execution in PostgreSQL."""
    args = []
    dialect = os.getenv("GERRYDB_OGR_SQL_DIALECT", "PostgreSQL")
    if dialect:
        args.extend(["-dialect", dialect])
    args.extend(["-sql", query])
    return args


def _init_base_graph_gpkg_extensions(conn: sqlite3.Connection, layer_name: str) -> None:
    conn.execute(
        """
        CREATE TABLE gerrydb_graph_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE gerrydb_geo_meta (
            meta_id INTEGER PRIMARY KEY,
            value   TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE gerrydb_geo_attrs (
            path        TEXT PRIMARY KEY REFERENCES {layer_name}(path),
            meta_id     BLOB NOT NULL    REFERENCES gerrydb_geo_meta(meta_id),
            valid_from  TEXT
        )
        """
    )

    # gpkg_data_columns_sql table definition:
    # https://www.geopackage.org/spec/#gpkg_data_columns_sql
    conn.execute(
        """
        CREATE TABLE gpkg_data_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            name TEXT,
            title TEXT,
            description TEXT,
            mime_type TEXT,
            constraint_name TEXT,
            CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name),
            CONSTRAINT gdc_tn UNIQUE (table_name, name)
        )
        """
    )
    # gpkg_extensions table definition: http://www.geopackage.org/spec/#_gpkg_extensions
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpkg_extensions (
            table_name     TEXT,
            column_name    TEXT,
            extension_name TEXT NOT NULL,
            definition     TEXT NOT NULL,
            scope          TEXT NOT NULL,
            CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO gpkg_extensions
        (table_name, column_name, extension_name, definition, scope)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                "gerrydb_graph_meta",
                None,
                "mggg_gerrydb",
                ("JSON-formatted metadata for the graph's data."),
                "read-write",
            ),
            (
                "gerrydb_geo_meta",
                None,
                "mggg_gerrydb",
                "JSON-formatted metadata for the view's geographies.",
                "read-write",
            ),
            (
                "gerrydb_geo_attrs",
                None,
                "mggg_gerrydb",
                (
                    "Mapping between geographies and metadata objects, "
                    "plus additional geography-level metadata attributes."
                ),
                "read-write",
            ),
        ],
    )
    conn.commit()


def _init_base_gpkg_extensions(conn: sqlite3.Connection, layer_name: str) -> None:
    conn.execute(
        """
        CREATE TABLE gerrydb_view_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE gerrydb_geo_meta (
            meta_id INTEGER PRIMARY KEY,
            value   TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE gerrydb_geo_attrs (
            path        TEXT PRIMARY KEY REFERENCES {layer_name}(path),
            meta_id     BLOB NOT NULL    REFERENCES gerrydb_geo_meta(meta_id),
            valid_from  TEXT
        )
        """
    )

    # gpkg_data_columns_sql table definition:
    # https://www.geopackage.org/spec/#gpkg_data_columns_sql
    conn.execute(
        """
        CREATE TABLE gpkg_data_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            name TEXT,
            title TEXT,
            description TEXT,
            mime_type TEXT,
            constraint_name TEXT,
            CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name),
            CONSTRAINT gdc_tn UNIQUE (table_name, name)
        )
        """
    )
    # gpkg_extensions table definition: http://www.geopackage.org/spec/#_gpkg_extensions
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpkg_extensions (
            table_name     TEXT,
            column_name    TEXT,
            extension_name TEXT NOT NULL,
            definition     TEXT NOT NULL,
            scope          TEXT NOT NULL,
            CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO gpkg_extensions
        (table_name, column_name, extension_name, definition, scope)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                "gerrydb_view_meta",
                None,
                "mggg_gerrydb",
                ("JSON-formatted metadata for the view's tabular, geographic, and graph data."),
                "read-write",
            ),
            (
                "gerrydb_geo_meta",
                None,
                "mggg_gerrydb",
                "JSON-formatted metadata for the view's geographies.",
                "read-write",
            ),
            (
                "gerrydb_geo_attrs",
                None,
                "mggg_gerrydb",
                (
                    "Mapping between geographies and metadata objects, "
                    "plus additional geography-level metadata attributes."
                ),
                "read-write",
            ),
        ],
    )
    conn.commit()


def _init_gpkg_graph_extension(conn: sqlite3.Connection, layer_name: str):
    """Initializes a graph edge table in a GeoPackage."""
    conn.execute(
        f"""
        CREATE TABLE gerrydb_graph_edge (
            path_1  TEXT NOT NULL REFERENCES {layer_name}(path),
            path_2  TEXT NOT NULL REFERENCES {layer_name}(path),
            weights TEXT,
            CONSTRAINT unique_edges UNIQUE (path_1, path_2)
        )
        """
    )

    conn.executemany(
        """
        INSERT INTO gpkg_extensions
        (table_name, column_name, extension_name, definition, scope)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                "gerrydb_graph_edge",
                None,
                "mggg_gerrydb",
                "Edges of a dual graph (adjacency graph) of the view's geographies.",
                "read-write",
            ),
        ],
    )
    conn.commit()


def _init_gpkg_plans_extension(conn: sqlite3.Connection, layer_name: str, columns: list[str]):
    """Initializes a plan assignments table in a GeoPackage."""
    table_columns = " TEXT,\n".join(columns) + " TEXT\n"
    conn.execute(
        f"""
        CREATE TABLE gerrydb_plan_assignment (
            path TEXT PRIMARY KEY REFERENCES {layer_name}(path),
            {table_columns} 
        )
        """
    )
    conn.execute(
        """
        INSERT INTO gpkg_extensions
        (table_name, column_name, extension_name, definition, scope)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "gerrydb_plan_assignment",
            None,
            "mggg_gerrydb",
            ("District assignments by geography for districting plans associated with the view."),
            "read-write",
        ),
    )
    conn.commit()


def __get_arg_max() -> int:
    """
    Retrieve the system's ARG_MAX value.

    Returns:
        int: The maximum length of the arguments to the exec functions in bytes.
             Returns None if the value cannot be determined.
    """
    if hasattr(os, "sysconf"):
        if "SC_ARG_MAX" in os.sysconf_names:
            try:
                arg_max = os.sysconf("SC_ARG_MAX")
                if arg_max > 0:
                    return arg_max
            except (ValueError, OSError):
                log.exception("Unable to retrieve ARG_MAX using os.sysconf.")
                raise

    if sys.platform.startswith("win"):
        raise RuntimeError("This function cannot be run in a Windows environment.")

    # Fallback Unix-like systems where SC_ARG_MAX is not available.
    # Uses common default value (Linux typically has 2,097,152 bytes).
    return 2097152


def __validate_query(query: str) -> None:
    """
    Ensures that the query is does not exceed the maximum allowable
    length of queries made to the terminal. This is generally governed by
    the ARG_MAX environment variable.

    Args:
        query: The query to be validated.

    Raises:
        RuntimeError: If the query is too long.
    """
    query_utf8 = query.encode("utf-8")
    max_query_len = __get_arg_max()

    if len(query_utf8) > max_query_len:
        raise RuntimeError("The length of the geoquery passed to ogr2ogr is too long. ")


def __run_subprocess(
    context: ViewRenderContext | GraphRenderContext, subprocess_command_list: list[str]
) -> None:
    try:
        subprocess.run(
            subprocess_command_list,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as ex:
        # Watch out for accidentally leaking credentials via logging here.
        # Production deployments should use a PostgreSQL connection service file
        # to pass credentials to ogr2ogr instead of passing a raw connection string.
        stdout = ex.stdout.decode("utf-8") if ex.stdout else ""
        stderr = ex.stderr.decode("utf-8") if ex.stderr else ""
        log.exception("Failed to export view with ogr2ogr. Query: %s", context.geo_query)
        log.error("ogr2ogr stdout: %s", stdout)
        log.error("ogr2ogr stderr: %s", stderr)
        raise RenderError("Failed to render view: geography query failed.")


def __validate_geo_and_internal_point_rows_count(
    conn: sqlite3.Connection,
    geo_layer_name: str,
    internal_point_layer_name: str,
    *,
    type: str,
    expected_count: int | None = None,
) -> None:
    def _feature_count(layer_name: str) -> int:
        # `gpkg_ogr_contents` is maintained by GDAL and gives O(1) row counts.
        # Fallback to COUNT(*) if unavailable.
        try:
            row = conn.execute(
                "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = ?",
                (layer_name,),
            ).fetchone()
            if row is not None and row[0] is not None:
                return int(row[0])
        except sqlite3.OperationalError:
            pass

        return conn.execute(f"SELECT COUNT(*) FROM {layer_name}").fetchone()[0]

    try:
        geo_row_count = _feature_count(geo_layer_name)
    except sqlite3.OperationalError as ex:
        raise RenderError(
            f"Failed to render {type}: geographic layer not found in GeoPackage.",
        ) from ex

    try:
        internal_point_row_count = _feature_count(internal_point_layer_name)
    except sqlite3.OperationalError as ex:
        raise RenderError(
            f"Failed to render {type}: internal point layer not found in GeoPackage.",
        ) from ex

    if expected_count is not None and geo_row_count != expected_count:
        raise RenderError(
            f"Failed to render {type}: expected {expected_count} geographies "
            f"in layer '{geo_layer_name}', got {geo_row_count} geographies."
        )

    if geo_row_count != internal_point_row_count:
        raise RenderError(
            f"Failed to render {type}: found {geo_row_count} geographies "
            f"in layer '{geo_layer_name}', but {internal_point_row_count} internal points."
        )


def __insert_geopackage_geometries(
    context: ViewRenderContext | GraphRenderContext,
    db_config: str,
    proj_args: list[str],
    gpkg_path: Path,
    geo_layer_name: str,
    internal_point_layer_name: str,
) -> None:
    log.debug("Before ogr2ogr")
    base_args = [
        *_ogr2ogr_common_args(),
        "-f",
        "GPKG",
        str(gpkg_path),
        db_config,
        *proj_args,
    ]

    # view_name = "my_materialized_geo_view"
    # view_sql_path = Path("create_geo_view.sql")

    # with open(view_sql_path, "w") as f:
    #     f.write(f"CREATE OR REPLACE VIEW {view_name} AS\n{context.geo_query};\n")

    # log.debug("View SQL written to %s", view_sql_path)
    # subprocess.run(
    #     [
    #         "psql",
    #         db_config.replace("PG:", ""),
    #         "-f",
    #         str(view_sql_path),
    #     ],
    #     check=True,
    # )

    subprocess_command_list = [
        "ogr2ogr",
        *base_args,
        *_ogr2ogr_sql_args(context.geo_query),
        "-nln",
        geo_layer_name,
    ]

    log.debug("View to gpkg subprocess command list %s", str(subprocess_command_list))

    subprocess_command = shlex.join(subprocess_command_list)

    start = time.perf_counter()
    __validate_query(subprocess_command)
    __run_subprocess(context, subprocess_command_list)
    log.debug("ogr2ogr took %s seconds", time.perf_counter() - start)

    subprocess_command_list = [
        "ogr2ogr",
        *base_args,
        "-update",
        *_ogr2ogr_sql_args(context.internal_point_query),
        "-nln",
        internal_point_layer_name,
        "-nlt",
        "POINT",
    ]

    log.debug(
        "Internal point query to gpkg subprocess command list %s",
        str(subprocess_command_list),
    )

    subprocess_command = shlex.join(subprocess_command_list)

    start = time.perf_counter()
    __validate_query(subprocess_command)
    __run_subprocess(context, subprocess_command_list)
    log.debug("Running internal point query took %s seconds", time.perf_counter() - start)


def __update_geo_attrs_gpkg(
    conn: sqlite3.Connection,
    context: ViewRenderContext | GraphRenderContext,
):
    db_meta_id_to_gpkg_meta_id = {}
    for db_id, meta in context.geo_meta.items():
        cur = conn.execute(
            "INSERT INTO gerrydb_geo_meta (value) VALUES (?)",
            (json.dumps(ObjectMeta.from_attributes(meta).model_dump()).decode("utf-8"),),
        )
        db_meta_id_to_gpkg_meta_id[db_id] = cur.lastrowid

    assert context.geo_meta_ids.keys() == context.geo_valid_from_dates.keys(), (
        "Geographic metadata IDs and valid dates must be aligned."
    )

    geo_attrs_dict = {}
    for path in context.geo_meta_ids.keys():
        geo_attrs_dict[path] = (
            context.geo_meta_ids[path],
            context.geo_valid_from_dates[path],
        )

    conn.executemany(
        "INSERT INTO gerrydb_geo_attrs (path, meta_id, valid_from) VALUES (?, ?, ?)",
        (
            (path, db_meta_id_to_gpkg_meta_id[db_id], valid_from)
            for path, (db_id, valid_from) in geo_attrs_dict.items()
        ),
    )


def __update_view_metadata_gpkg(
    conn: sqlite3.Connection,
    geo_layer_name: str,
    internal_point_layer_name: str,
    context: ViewRenderContext | GraphRenderContext,
):
    # Create indices and references on paths.
    conn.execute(f"CREATE UNIQUE INDEX idx_geo_path ON {geo_layer_name}(path)")
    conn.execute(
        f"CREATE UNIQUE INDEX idx_internal_point_path ON {internal_point_layer_name}(path)"
    )

    # Add extended (non-geographic) data.
    _init_base_gpkg_extensions(conn, geo_layer_name)

    pyd_meta = ViewMeta.from_attributes(context.view)
    meta_dict = pyd_meta.model_dump()

    conn.executemany(
        "INSERT OR REPLACE INTO gerrydb_view_meta (key, value) VALUES (?, ?)",
        (
            # json.dumps(val, default=str) turns nested dicts/UUIDs/datetimes into
            # valid JSON text with DOUBLE quotes
            (key, json.dumps(val, default=str))
            for key, val in meta_dict.items()
        ),
    )

    conn.executemany(
        ("INSERT INTO gpkg_data_columns (table_name, column_name, description) VALUES (?, ?, ?)"),
        ((geo_layer_name, alias, col.description) for alias, col in context.columns.items()),
    )


def __insert_graph_edges(
    context: ViewRenderContext | GraphRenderContext,
    conn: sqlite3.Connection,
    geo_layer_name: str,
):
    _init_gpkg_graph_extension(conn, geo_layer_name)
    conn.executemany(
        "INSERT INTO gerrydb_graph_edge (path_1, path_2, weights) VALUES (?, ?, ?)",
        (
            (edge.path_1, edge.path_2, json.dumps(edge.weights).decode("utf-8"))
            for edge in context.graph_edges
        ),
    )


def __insert_plan_assignments(
    context: ViewRenderContext,
    conn: sqlite3.Connection,
    geo_layer_name: str,
):
    _init_gpkg_plans_extension(conn, geo_layer_name, context.plan_labels)
    cols = ["path", *context.plan_labels]
    placeholders = ", ".join(["?"] * len(cols))

    conn.executemany(
        (f"INSERT INTO gerrydb_plan_assignment ({', '.join(cols)}) VALUES ({placeholders})"),
        ([getattr(row, col) for col in cols] for row in context.plan_assignments),
    )


def view_to_gpkg(context: ViewRenderContext, db_config: str) -> tuple[uuid.UUID, Path]:
    """Renders a view (with metadata) to a GeoPackage."""
    render_uuid = uuid.uuid4()
    temp_dir = Path(tempfile.mkdtemp())
    gpkg_path = Path(temp_dir) / f"{render_uuid.hex}.gpkg"

    geo_layer_name = context.view.path
    internal_point_layer_name = f"{geo_layer_name}__internal_points"

    if context.view.proj is not None:
        # Explicit -s_srs: storage is always EPSG:4269, and GDAL cannot infer the
        # SRS of a SQL result layer whose first geometry is NULL.
        proj_args = ["-s_srs", "epsg:4269", "-t_srs", context.view.proj]
    else:
        proj_args = []  # leave in original projection (conventionally EPSG:4269)

    __insert_geopackage_geometries(
        context,
        db_config,
        proj_args,
        gpkg_path,
        geo_layer_name,
        internal_point_layer_name,
    )

    conn = sqlite3.connect(gpkg_path)

    __validate_geo_and_internal_point_rows_count(
        conn,
        geo_layer_name,
        internal_point_layer_name,
        type="view",
        expected_count=context.view.num_geos,
    )

    __update_view_metadata_gpkg(conn, geo_layer_name, internal_point_layer_name, context)
    __update_geo_attrs_gpkg(conn, context)

    start = time.perf_counter()
    if context.graph_edges is not None:
        __insert_graph_edges(context, conn, geo_layer_name)
    log.debug("Inserting graph edges took %s seconds", time.perf_counter() - start)

    start = time.perf_counter()
    if context.plan_assignments is not None:
        __insert_plan_assignments(context, conn, geo_layer_name)
    log.debug("Inserting plan assignments took %s seconds", time.perf_counter() - start)

    conn.commit()
    conn.close()

    return render_uuid, gpkg_path


def __update_graph_metadata_gpkg(
    conn: sqlite3.Connection,
    geo_layer_name: str,
    internal_point_layer_name: str,
    context: GraphRenderContext,
):
    conn.execute(f"CREATE UNIQUE INDEX idx_geo_path ON {geo_layer_name}(path)")
    conn.execute(
        f"CREATE UNIQUE INDEX idx_internal_point_path ON {internal_point_layer_name}(path)"
    )

    _init_base_graph_gpkg_extensions(conn, geo_layer_name)

    pyd_meta = GraphMeta.from_attributes(context.graph)
    meta_dict = pyd_meta.model_dump()

    conn.executemany(
        "INSERT OR REPLACE INTO gerrydb_graph_meta (key, value) VALUES (?, ?)",
        (
            # json.dumps(val, default=str) turns nested dicts/UUIDs/datetimes into
            # valid JSON text with DOUBLE quotes
            (key, json.dumps(val, default=str))
            for key, val in meta_dict.items()
        ),
    )


def graph_to_gpkg(context: GraphRenderContext, db_config: str) -> tuple[uuid.UUID, Path]:
    render_uuid = uuid.uuid4()
    temp_dir = Path(tempfile.mkdtemp())
    gpkg_path = Path(temp_dir) / f"{render_uuid.hex}.gpkg"

    log.debug("GPKG PATH %s", gpkg_path)

    geo_layer_name = f"{context.graph.path}__geometry"
    internal_point_layer_name = f"{context.graph.path}__internal_points"

    if context.graph.proj is not None:
        # -s_srs for the same NULL-first-geometry reason as in view_to_gpkg above.
        proj_args = ["-s_srs", "epsg:4269", "-t_srs", context.graph.proj]
    else:
        proj_args = []  # leave in original projection (conventionally EPSG:4269)

    __insert_geopackage_geometries(
        context,
        db_config,
        proj_args,
        gpkg_path,
        geo_layer_name,
        internal_point_layer_name,
    )

    conn = sqlite3.connect(gpkg_path)

    __validate_geo_and_internal_point_rows_count(
        conn, geo_layer_name, internal_point_layer_name, type="graph"
    )

    __update_graph_metadata_gpkg(conn, geo_layer_name, internal_point_layer_name, context)
    __update_geo_attrs_gpkg(conn, context)

    start = time.perf_counter()
    if context.graph_edges is not None:
        __insert_graph_edges(context, conn, geo_layer_name)
    log.debug("Inserting graph edges took %s seconds", time.perf_counter() - start)

    conn.commit()
    conn.close()

    return render_uuid, gpkg_path
