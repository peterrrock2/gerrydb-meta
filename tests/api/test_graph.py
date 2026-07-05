import logging

import geopandas as gpd
import pytest
from starlette.responses import Response

from gerrydb_meta import crud, schemas
from gerrydb_meta.api.graph import *


def test_good_graph_create_get(ctx_no_scopes, me_2010_gdf, me_2010_nx_graph, caplog):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta
    scopes = get_scopes(user)

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
                canonical_path="main_graph",
                name="main_graph",
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

    response = Response()

    with pytest.raises(HTTPException) as excinfo:
        _ = create_graph(
            response=response,
            namespace="bad_namespace",
            obj_in=schemas.GraphCreate(
                path="me_2010_county_dual",
                description="The maine 2010 county dual graph",
                locality="main_graph",
                layer="counties_graph",
                edges=list(me_2010_nx_graph.edges(data=True)),
            ),
            db=db,
            obj_meta=meta,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        'Namespace "bad_namespace" not found, or you do not have sufficient permissions '
        "to read data in this namespace."
    ) in str(excinfo.value.detail)

    created = create_graph(
        response=response,
        namespace=ns.path,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="main_graph",
            layer="counties_graph",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        include_edges=True,
        db=db,
        obj_meta=meta,
        scopes=scopes,
    )
    assert isinstance(created, schemas.Graph)
    assert len(created.edges) == len(me_2010_nx_graph.edges)

    meta_only = create_graph(
        response=Response(),
        namespace=ns.path,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual_meta_only",
            description="The maine 2010 county dual graph",
            locality="main_graph",
            layer="counties_graph",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        include_edges=False,
        db=db,
        obj_meta=meta,
        scopes=scopes,
    )
    assert isinstance(meta_only, schemas.GraphMeta)
    assert not isinstance(meta_only, schemas.Graph)
    assert meta_only.path == "me_2010_county_dual_meta_only"

    response2 = Response()

    with pytest.raises(HTTPException) as excinfo:
        all_graph_check = all_graphs(
            response=response2,
            namespace="bad_namespace",
            db=db,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        'Namespace "bad_namespace" not found, or you do not have sufficient permissions '
        "to read data in this namespace."
    ) in str(excinfo.value.detail)

    all_graph_check = all_graphs(
        response=response2,
        namespace=ns.path,
        db=db,
        scopes=scopes,
    )

    response3 = Response()

    with pytest.raises(HTTPException) as excinfo:
        graph_check = get_graph(
            response=response3,
            namespace="bad_namespace",
            path="me_2010_county_dual",
            db=db,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        'Namespace "bad_namespace" not found, or you do not have sufficient permissions '
        "to read data in this namespace."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        graph_check = get_graph(
            response=response3,
            namespace=ns.path,
            path="bad_me_2010_county_dual",
            db=db,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert "Graph not found in namespace." in str(excinfo.value.detail)

    graph_check = get_graph(
        response=response3,
        namespace=ns.path,
        path="me_2010_county_dual",
        db=db,
        scopes=scopes,
    )

    assert len(all_graph_check) == 2
    assert {g.path for g in all_graph_check} == {
        "me_2010_county_dual",
        "me_2010_county_dual_meta_only",
    }
    assert graph_check == next(
        g for g in all_graph_check if g.path == "me_2010_county_dual"
    )


def test_graph_render(ctx_no_scopes, me_2010_gdf, me_2010_nx_graph, caplog):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta
    scopes = get_scopes(user)

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
                canonical_path="main_graph2",
                name="main_graph2",
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

    response = Response()

    _ = create_graph(
        response=response,
        namespace=ns.path,
        obj_in=schemas.GraphCreate(
            path="me_2010_county_dual",
            description="The maine 2010 county dual graph",
            locality="main_graph2",
            layer="counties_graph2",
            edges=list(me_2010_nx_graph.edges(data=True)),
        ),
        db=db,
        obj_meta=meta,
        scopes=scopes,
    )

    with pytest.raises(HTTPException) as excinfo:
        render_response = render_graph(
            namespace="bad_namespace",
            path="me_2010_county_dual",
            db=db,
            db_config="PG:postgresql://postgres:test@localhost:54321",
            user=user,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        'Namespace "bad_namespace" not found, or you do not have sufficient permissions '
        "to read data in this namespace."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        render_response = render_graph(
            namespace=ns.path,
            path="bad_me_2010_county_dual",
            db=db,
            db_config="PG:postgresql://postgres:test@localhost:54321",
            user=user,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert "Graph not found in namespace." in str(excinfo.value.detail)

    render_response = render_graph(
        namespace=ns.path,
        path="me_2010_county_dual",
        db=db,
        db_config="PG:postgresql://postgres:test@localhost:54321",
        user=user,
        scopes=scopes,
    )

    gpkg_path = render_response.path

    graph_gdf = gpd.read_file(gpkg_path, layer="gerrydb_graph_edge")

    sorted_me_edges = {tuple(sorted(e)) for e in me_2010_nx_graph.edges()}
    sorted_graph_edges = {tuple(sorted(e)) for e in zip(graph_gdf["path_1"], graph_gdf["path_2"])}

    assert sorted_graph_edges == sorted_me_edges
