import logging
import os
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from fastapi import HTTPException
from shapely.geometry import Point

from gerrydb_meta.crud.geography import GEO_GRID_SIZE


def _canonical_geoseries(series):
    """What the server stores: coordinates snapped to the canonical grid."""
    return series.apply(lambda g: shapely.set_precision(g, GEO_GRID_SIZE, mode="pointwise"))

import gerrydb_meta.api.view as view_api
import gerrydb_meta.models as models
from gerrydb_meta import crud, schemas
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.render import (
    RenderError,
    __get_arg_max,
    __run_subprocess,
    __validate_geo_and_internal_point_rows_count,
    __validate_query,
    graph_to_gpkg,
    view_to_gpkg,
)


class DummyContext:
    # minimal stub
    view = SimpleNamespace(
        path="foo", proj=None, loc=SimpleNamespace(default_proj=None), num_geos=0
    )
    geo_query = "SELECT * from dummy_table"
    internal_point_query = "SELECT 2"
    columns = {}
    geo_meta = {}
    geo_meta_ids = {}
    geo_valid_from_dates = {}
    graph_edges = None
    plan_assignments = None
    plan_labels = []


def test_run_subprocess_logs_and_raises(monkeypatch, caplog):
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ogr2ogr", "--fake"],
        output=b"fake-stdout",
        stderr=b"fake-stderr",
    )

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(err))
    caplog.set_level(logging.ERROR)

    with pytest.raises(RenderError) as excinfo:
        __run_subprocess(DummyContext(), ["ogr2ogr", "--fake"])
    assert str(excinfo.value) == "Failed to render view: geography query failed."

    log_text = caplog.text
    assert "Failed to export view with ogr2ogr. Query: SELECT * from dummy_table" in log_text
    assert "ogr2ogr stdout: fake-stdout" in log_text
    assert "ogr2ogr stderr: fake-stderr" in log_text


def test_sysconf_raises_oserror(monkeypatch):
    monkeypatch.setattr(os, "sysconf_names", {"SC_ARG_MAX": object()})

    def fake_sysconf(name):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "sysconf", fake_sysconf)

    with pytest.raises(OSError) as excinfo:
        __get_arg_max()
    assert "simulated failure" in str(excinfo.value)


def test_sysconf_raises_valueerror(monkeypatch):
    monkeypatch.setattr(os, "sysconf_names", {"SC_ARG_MAX": object()})
    monkeypatch.setattr(os, "sysconf", lambda name: (_ for _ in ()).throw(ValueError("bad arg")))
    with pytest.raises(ValueError):
        __get_arg_max()


def test_windows_raises_runtime(monkeypatch):
    monkeypatch.delattr(os, "sysconf", raising=False)
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        __get_arg_max()
    assert "cannot be run in a Windows environment" in str(excinfo.value)


def test_fallback_default(monkeypatch):
    monkeypatch.setattr(os, "sysconf_names", {}, raising=False)
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    assert __get_arg_max() == 2097152


def test_max_query_len():
    max_len = __get_arg_max()
    query = "*" * (max_len + 1)
    with pytest.raises(
        RuntimeError, match="The length of the geoquery passed to ogr2ogr is too long."
    ):
        __validate_query(query)


def test_geo_layer_not_found():
    conn = sqlite3.connect(":memory:")
    # no tables at all → first SELECT blows up
    with pytest.raises(RenderError) as excinfo:
        __validate_geo_and_internal_point_rows_count(
            conn,
            geo_layer_name="missing_geo",
            internal_point_layer_name="missing_internal",
            type="T1",
        )
    assert str(excinfo.value) == ("Failed to render T1: geographic layer not found in GeoPackage.")


def test_internal_point_layer_not_found():
    conn = sqlite3.connect(":memory:")
    # only geo exists
    conn.execute("CREATE TABLE geo_table (id INTEGER)")
    with pytest.raises(RenderError) as excinfo:
        __validate_geo_and_internal_point_rows_count(
            conn,
            geo_layer_name="geo_table",
            internal_point_layer_name="missing_internal",
            type="T2",
        )
    assert str(excinfo.value) == (
        "Failed to render T2: internal point layer not found in GeoPackage."
    )


def test_expected_count_mismatch():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE geo_table (id INTEGER)")
    conn.execute("CREATE TABLE internal_table (id INTEGER)")
    # geo has 1 row, internal has 0
    conn.execute("INSERT INTO geo_table (id) VALUES (1)")

    with pytest.raises(RenderError) as excinfo:
        __validate_geo_and_internal_point_rows_count(
            conn,
            geo_layer_name="geo_table",
            internal_point_layer_name="internal_table",
            type="T3",
            expected_count=2,
        )
    assert str(excinfo.value) == (
        "Failed to render T3: expected 2 geographies in layer 'geo_table', got 1 geographies."
    )


def test_geo_internal_count_mismatch():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE geo_table (id INTEGER)")
    conn.execute("CREATE TABLE internal_table (id INTEGER)")
    # geo has 1, internal has 2
    conn.execute("INSERT INTO geo_table (id) VALUES (1)")
    conn.execute("INSERT INTO internal_table (id) VALUES (10)")
    conn.execute("INSERT INTO internal_table (id) VALUES (20)")

    with pytest.raises(RenderError) as excinfo:
        __validate_geo_and_internal_point_rows_count(
            conn,
            geo_layer_name="geo_table",
            internal_point_layer_name="internal_table",
            type="T4",
        )
    assert str(excinfo.value) == (
        "Failed to render T4: found 1 geographies in layer 'geo_table', but 2 internal points."
    )


def test_counts_match_and_expected_count_ok():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE geo_table (id INTEGER)")
    conn.execute("CREATE TABLE internal_table (id INTEGER)")
    # insert 3 matching rows
    for i in range(3):
        conn.execute("INSERT INTO geo_table (id) VALUES (?)", (i,))
        conn.execute("INSERT INTO internal_table (id) VALUES (?)", (i,))

    # should not raise if counts match
    __validate_geo_and_internal_point_rows_count(
        conn,
        geo_layer_name="geo_table",
        internal_point_layer_name="internal_table",
        type="T5",
    )

    # and also OK if expected_count matches
    __validate_geo_and_internal_point_rows_count(
        conn,
        geo_layer_name="geo_table",
        internal_point_layer_name="internal_table",
        type="T5",
        expected_count=3,
    )


def test_ogr2ogr_failure(monkeypatch):
    # make subprocess.run always fail
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1, cmd=args[0], stderr=b"bang", output=b"boom"
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RenderError, match="Failed to render view: geography query failed"):
        view_to_gpkg(
            DummyContext(),
            "postgresql://doesntmatter",
        )


def test_good_render_view(db, me_2010_gdf, me_2010_nx_graph, me_2010_plan_dict, caplog):

    user = models.User(email="rendertest@example.com", name="Render User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"render", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="render test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_render",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_render",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_render",
                name="main_render",
                aliases=["mar", "23r"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    geo_set = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])
    assignments = {mem.geo: me_2010_plan_dict[mem.geo.path] for mem in geo_set.members}

    _ = crud.plan.create(
        db=db,
        obj_in=schemas.PlanCreate(
            path="me_2010_county_plan",
            description="The maine 2010 county bipartition",
            locality="main_render",
            layer="counties_render",
            assignments=me_2010_plan_dict,
        ),
        geo_set_version=geo_set,
        assignments=assignments,
        obj_meta=meta,
        namespace=ns,
    )

    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="main_render",
            layer="counties_render",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    land_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="aland",
            description="The area of land in square meters",
            kind=ColumnKind.AREA,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=land_col,
        values=[(o, int(me_2010_gdf.at[o.path, "ALAND10"])) for o in geo_objs],
        obj_meta=meta,
    )

    land_coL_ref = crud.column.get_ref(db=db, path="aland", namespace=ns)

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="me_test_view_template",
            description="A test view template for maine",
            members=["aland"],
        ),
        resolved_members=[land_coL_ref],
        obj_meta=meta,
        namespace=ns,
    )

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="me_test_view",
            description="A test view for maine",
            locality="main_render",
            layer="counties_render",
            template="me_test_view_template",
            graph="me_2010_county_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=graph,
    )

    # For geo comparisons later
    view.proj = "epsg:4269"

    view_render_ctx = crud.view.render(db=db, view=view)
    db.commit()
    db.flush()

    _, path = view_to_gpkg(
        view_render_ctx,
        db_config="PG:postgresql://postgres:test@localhost:54321",
    )

    gdf = gpd.read_file(path, layer="me_test_view")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)

    assert gdf["aland"].equals(me_2010_gdf["ALAND10"])
    assert gdf["geometry"].equals(_canonical_geoseries(me_2010_gdf["geometry"]))

    gdf = gpd.read_file(path, layer="me_test_view__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf2 = me_2010_gdf.set_geometry("internal_point")
    assert gdf["geometry"].equals(me_2010_gdf2["internal_point"])

    plan_layer = gpd.read_file(path, layer="gerrydb_plan_assignment")
    plan_layer.set_index("path", inplace=True)
    plan_layer.sort_index(inplace=True)
    df = pd.Series(me_2010_plan_dict).sort_index()
    assert plan_layer["me_2010_county_plan"].astype(int).equals(df.astype(int))


def test_good_render_view_default_projection(
    db, me_2010_gdf, me_2010_nx_graph, me_2010_plan_dict, caplog
):

    user = models.User(email="render2test@example.com", name="Render2 User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"render2", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="render2 test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_render2",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_render2",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_render2",
                name="main_render2",
                aliases=["mar2", "23r2"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    geo_set = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])
    assignments = {mem.geo: me_2010_plan_dict[mem.geo.path] for mem in geo_set.members}

    _ = crud.plan.create(
        db=db,
        obj_in=schemas.PlanCreate(
            path="me_2010_county_plan",
            description="The maine 2010 county bipartition",
            locality="main_render2",
            layer="counties_render2",
            assignments=me_2010_plan_dict,
        ),
        geo_set_version=geo_set,
        assignments=assignments,
        obj_meta=meta,
        namespace=ns,
    )

    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="main_render2",
            layer="counties_render2",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    land_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="aland",
            description="The area of land in square meters",
            kind=ColumnKind.AREA,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=land_col,
        values=[(o, int(me_2010_gdf.at[o.path, "ALAND10"])) for o in geo_objs],
        obj_meta=meta,
    )

    land_coL_ref = crud.column.get_ref(db=db, path="aland", namespace=ns)

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="me_test_view_template",
            description="A test view template for maine",
            members=["aland"],
        ),
        resolved_members=[land_coL_ref],
        obj_meta=meta,
        namespace=ns,
    )

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="me_test_view",
            description="A test view for maine",
            locality="main_render2",
            layer="counties_render2",
            template="me_test_view_template",
            graph="me_2010_county_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=graph,
    )

    view_render_ctx = crud.view.render(db=db, view=view)
    db.commit()
    db.flush()

    _, path = view_to_gpkg(
        view_render_ctx,
        db_config="PG:postgresql://postgres:test@localhost:54321",
    )

    gdf = gpd.read_file(path, layer="me_test_view")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)
    me_2010_gdf = me_2010_gdf.to_crs(gdf.crs)

    assert gdf["aland"].equals(me_2010_gdf["ALAND10"])
    assert gdf["geometry"].equals(_canonical_geoseries(me_2010_gdf["geometry"]))

    gdf = gpd.read_file(path, layer="me_test_view__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf2 = me_2010_gdf.set_geometry("internal_point")
    me_2010_gdf2.set_crs("epsg:4269", inplace=True)
    me_2010_gdf2.to_crs(gdf.crs, inplace=True)
    assert gdf["geometry"].equals(me_2010_gdf2["internal_point"])

    plan_layer = gpd.read_file(path, layer="gerrydb_plan_assignment")
    plan_layer.set_index("path", inplace=True)
    plan_layer.sort_index(inplace=True)
    df = pd.Series(me_2010_plan_dict).sort_index()
    assert plan_layer["me_2010_county_plan"].astype(int).equals(df.astype(int))


def test_good_render_graph(db, me_2010_gdf, me_2010_nx_graph, ia_dataframe, caplog):

    user = models.User(email="graphtest@example.com", name="Graph User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"graph", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="graph test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_graph",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    db.commit()
    db.flush()

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_graph",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="maine_graph",
                name="maine_graph",
                aliases=["mag", "23g"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    # Wait for the geos
    time.sleep(1)
    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="maine_graph",
            layer="counties_graph",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    db.commit()
    db.flush()

    graph_render_ctx = crud.graph.render(db=db, graph=graph)

    _, path = graph_to_gpkg(
        graph_render_ctx,
        db_config="PG:postgresql://postgres:test@localhost:54321",
    )

    gdf = gpd.read_file(path, layer="me_2010_county_dual__geometry")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)

    assert gdf["geometry"].equals(_canonical_geoseries(me_2010_gdf["geometry"]))

    gdf = gpd.read_file(path, layer="me_2010_county_dual__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf = me_2010_gdf.set_geometry("internal_point")
    assert gdf["geometry"].equals(me_2010_gdf["internal_point"])

    edge_df = gpd.read_file(path, layer="gerrydb_graph_edge")
    df_edge_set = set(
        [tuple(sorted([row["path_1"], row["path_2"]])) for _, row in edge_df.iterrows()]
    )
    base_edge_set = set([tuple(sorted([e1, e2])) for e1, e2 in me_2010_nx_graph.edges()])
    assert df_edge_set == base_edge_set


# Needed to check and make sure we don't grab extra geos on accident
# Added after finding this as a bug
def test_good_render_graph_extra_geos(db, me_2010_gdf, me_2010_nx_graph, ia_dataframe, caplog):

    user = models.User(email="graphtestextra@example.com", name="Graph User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"graphextra", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="graph test extra", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_graph_extra",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    # Make some extra geos in the db
    ia_geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=Point().wkb,
        )
        for row in ia_dataframe.itertuples()
    ]

    ia_geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    _ = crud.geography.create_bulk(
        db=db,
        objs_in=ia_geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=ia_geo_import,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    db.commit()
    db.flush()

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_graph_extra",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="maine_graph_extra",
                name="maine_graph_extra",
                aliases=["mage", "23ge"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    # Wait for the geos
    time.sleep(1)
    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="maine_graph_extra",
            layer="counties_graph_extra",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    db.commit()
    db.flush()

    graph_render_ctx = crud.graph.render(db=db, graph=graph)

    _, path = graph_to_gpkg(
        graph_render_ctx,
        db_config="PG:postgresql://postgres:test@localhost:54321",
    )

    gdf = gpd.read_file(path, layer="me_2010_county_dual__geometry")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)

    assert gdf["geometry"].equals(_canonical_geoseries(me_2010_gdf["geometry"]))

    gdf = gpd.read_file(path, layer="me_2010_county_dual__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf = me_2010_gdf.set_geometry("internal_point")
    assert gdf["geometry"].equals(me_2010_gdf["internal_point"])

    edge_df = gpd.read_file(path, layer="gerrydb_graph_edge")
    df_edge_set = set(
        [tuple(sorted([row["path_1"], row["path_2"]])) for _, row in edge_df.iterrows()]
    )
    base_edge_set = set([tuple(sorted([e1, e2])) for e1, e2 in me_2010_nx_graph.edges()])
    assert df_edge_set == base_edge_set


def test_good_render_graph_new_projection(db, me_2010_gdf, me_2010_nx_graph, caplog):

    user = models.User(email="graph2test@example.com", name="Render User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"graph2", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="graph2 test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_graph2",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    db.commit()
    db.flush()

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_graph2",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="maine_graph2",
                name="maine_graph2",
                aliases=["mag2", "23g2"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    # Wait for the geos
    time.sleep(1)
    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph2",
            locality="maine_graph2",
            layer="counties_graph2",
            edges=list(me_2010_nx_graph.edges(data=True)),
            proj="epsg:26919",
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    db.commit()
    db.flush()

    graph_render_ctx = crud.graph.render(db=db, graph=graph)

    _, path = graph_to_gpkg(
        graph_render_ctx,
        db_config="PG:postgresql://postgres:test@localhost:54321",
    )

    gdf = gpd.read_file(path, layer="me_2010_county_dual__geometry")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)
    gdf.to_crs(me_2010_gdf.crs, inplace=True)

    # Need this because of floating point precision
    for g1, g2 in zip(gdf.geometry, me_2010_gdf.geometry):
        assert g1.equals_exact(g2, tolerance=8)

    gdf = gpd.read_file(path, layer="me_2010_county_dual__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    gdf.to_crs(me_2010_gdf.crs, inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf = me_2010_gdf.set_geometry("internal_point")
    for g1, g2 in zip(gdf.geometry, me_2010_gdf.internal_point):
        assert g1.equals_exact(g2, tolerance=8)


def test_view_render_api(db, me_2010_gdf, me_2010_nx_graph, me_2010_plan_dict, caplog):
    user = models.User(email="renderapitest@example.com", name="Render API User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"renderapi", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="render api test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    # caplog.set_level(logging.DEBUG, logger="uvicorn.error")
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_render_api",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_render_api",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_render_api",
                name="main_render_api",
                aliases=["marapi", "23rapi"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    geo_set = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])
    assignments = {mem.geo: me_2010_plan_dict[mem.geo.path] for mem in geo_set.members}

    _ = crud.plan.create(
        db=db,
        obj_in=schemas.PlanCreate(
            path="me_2010_county_plan",
            description="The maine 2010 county bipartition",
            locality="main_render_api",
            layer="counties_render_api",
            assignments=me_2010_plan_dict,
        ),
        geo_set_version=geo_set,
        assignments=assignments,
        obj_meta=meta,
        namespace=ns,
    )

    graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="me_api_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="main_render_api",
            layer="counties_render_api",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={o.path: o for o in geo_objs},
        obj_meta=meta,
        namespace=ns,
    )

    land_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="aland",
            description="The area of land in square meters",
            kind=ColumnKind.AREA,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=land_col,
        values=[(o, int(me_2010_gdf.at[o.path, "ALAND10"])) for o in geo_objs],
        obj_meta=meta,
    )

    land_coL_ref = crud.column.get_ref(db=db, path="aland", namespace=ns)

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="me_test_view_api_template",
            description="A test view template for maine",
            members=["aland"],
        ),
        resolved_members=[land_coL_ref],
        obj_meta=meta,
        namespace=ns,
    )

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="me_test_api_view",
            description="A test view for maine",
            locality="main_render_api",
            layer="counties_render_api",
            template="me_test_view_api_template",
            graph="me_api_2010_county_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=graph,
    )

    db.commit()
    db.flush()

    with pytest.raises(HTTPException, match='Namespace "bad_namespace" not found'):
        response = view_api.render_view(
            namespace="bad_namespace",
            path="me_test_api_view",
            db=db,
            db_config="PG:postgresql://postgres:test@localhost:54321",
            user=user,
            scopes=get_scopes(user),
        )

    with pytest.raises(HTTPException, match="View not found in namespace"):
        response = view_api.render_view(
            namespace=ns.path,
            path="bad_view",
            db=db,
            db_config="PG:postgresql://postgres:test@localhost:54321",
            user=user,
            scopes=get_scopes(user),
        )

    response = view_api.render_view(
        namespace=ns.path,
        path="me_test_api_view",
        db=db,
        db_config="PG:postgresql://postgres:test@localhost:54321",
        user=user,
        scopes=get_scopes(user),
    )

    path = response.path

    gdf = gpd.read_file(path, layer="me_test_api_view")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)
    me_2010_gdf.sort_index(inplace=True)

    assert gdf["aland"].equals(me_2010_gdf["ALAND10"])
    # for g1, g2 in zip(gdf.geometry, me_2010_gdf.geometry):
    #     assert g1.equals_exact(g2, tolerance=8)
    assert gdf["geometry"].equals(_canonical_geoseries(me_2010_gdf["geometry"]))

    gdf = gpd.read_file(path, layer="me_test_api_view__internal_points")

    gdf.set_index("path", inplace=True)
    gdf.sort_index(inplace=True)

    # need to do this because because of type nonsense
    me_2010_gdf2 = me_2010_gdf.set_geometry("internal_point")
    assert gdf["geometry"].equals(me_2010_gdf2["internal_point"])
