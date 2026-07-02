"""Tests for GerryDB REST API view template endpoints."""

import logging
from http import HTTPStatus

import networkx as nx
from shapely import box
from shapely.geometry import Point, Polygon

import gerrydb_meta.models as models
from gerrydb_meta import crud, schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.main import API_PREFIX

VIEW_TEMPLATES_ROOT = f"{API_PREFIX}/views"


def test_view_make_and_get_cached_render(ctx_superuser):
    db = ctx_superuser.db
    ctx = ctx_superuser
    user = models.User(email="view_test_api@example.com", name="view_test_api User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"view_test_api_key", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="view_api test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    grid_graph = nx.Graph()
    grid_graph.add_nodes_from(["central", "western"])
    grid_graph.add_edge("central", "western", weight=1.0)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=None,
                internal_point=None,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=None,
                internal_point=None,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis_blocks",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis_locality",
                parent_path=None,
                name="Atlantis",
                aliases=None,
            ),
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

    created_graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="atlantis_dual",
            description="The legendary city of Atlantis",
            locality="atlantis_locality",
            layer="atlantis_blocks",
            edges=[
                (a, b, {k: v for k, v in attr.items() if k != "id"})
                for (a, b), attr in grid_graph.edges.items()
            ],
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={"central": geo[0][0], "western": geo[1][0]},
        obj_meta=meta,
        namespace=ns,
    )

    mayor_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=mayor_col,
        values=[
            (geo[0][0], "Poseidon"),
            (geo[1][0], "Poseidon"),
        ],
        obj_meta=meta,
    )

    pop_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=pop_col,
        values=[
            (geo[0][0], 1000),
            (geo[1][0], 2000),
        ],
        obj_meta=meta,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    ret = ctx.client.post(
        f"{API_PREFIX}/view-templates/{ns.path}",
        json={
            "path": "mayor_power_template",
            "description": "template for viewing mayor power",
            "members": [f"/column-sets/{ns.path}/mayor_power"],
        },
    )

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )
    assert ret.json()["path"] == "mayor_power"

    ret_get = ctx.client.get(
        f"{API_PREFIX}/views/{ns.path}/mayor_power",
    )

    assert ret_get.json() == ret.json()


def test_api_view_create_get_errors(ctx_superuser, caplog):
    db = ctx_superuser.db
    ctx = ctx_superuser
    ctx.user
    meta = ctx.meta

    caplog.set_level(logging.ERROR, logger="uvicorn")

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis2",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )
    grid_graph = nx.Graph()
    grid_graph.add_nodes_from(["central", "western"])
    grid_graph.add_edge("central", "western", weight=1.0)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=Polygon().wkb,
                internal_point=Point().wkb,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=Polygon().wkb,
                internal_point=Point().wkb,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geo2, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=box(0, 0, 1, 1).wkb,
                internal_point=Point(0, 0).wkb,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=box(0, 0, 1, 1).wkb,
                internal_point=Point(0, 0).wkb,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns2,
    )

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis_blocks",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )
    geo_layer2, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis_blocks",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis_locality",
                parent_path=None,
                name="Atlantis",
                aliases=None,
            ),
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
    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer2,
        locality=loc[0],
        geographies=[geo[0] for geo in geo2],
        obj_meta=meta,
    )

    created_graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="atlantis_dual",
            description="The legendary city of Atlantis",
            locality="atlantis_locality",
            layer="atlantis_blocks",
            edges=[
                (a, b, {k: v for k, v in attr.items() if k != "id"})
                for (a, b), attr in grid_graph.edges.items()
            ],
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={"central": geo[0][0], "western": geo[1][0]},
        obj_meta=meta,
        namespace=ns,
    )

    mayor_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    mayor_col2, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    crud.column.set_values(
        db=db,
        col=mayor_col,
        values=[
            (geo[0][0], "Poseidon"),
            (geo[1][0], "Poseidon"),
        ],
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=mayor_col2,
        values=[
            (geo2[0][0], "Poseidon"),
            (geo2[1][0], "Poseidon"),
        ],
        obj_meta=meta,
    )

    pop_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    pop_col2, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    crud.column.set_values(
        db=db,
        col=pop_col,
        values=[
            (geo[0][0], 1000),
            (geo[1][0], 2000),
        ],
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=pop_col2,
        values=[
            (geo2[0][0], 1000),
            (geo2[1][0], 2000),
        ],
        obj_meta=meta,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    col_set2, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template",
            description="template for viewing mayor power",
            members=["mayor_power"],
        ),
        resolved_members=[col_set],
        obj_meta=meta,
        namespace=ns,
    )

    view_template2, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template2",
            description="template for viewing mayor power",
            members=["mayor_power"],
        ),
        resolved_members=[col_set2],
        obj_meta=meta,
        namespace=ns,
    )

    ret = ctx.client.post(
        f"{API_PREFIX}/views/bad_ns",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert (
        'Namespace "bad_ns" not found, or you do not have sufficient permissions '
        "to write views in this namespace."
    ) in ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "bad_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert "Locality not found." == ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "bad_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert "View template not found." == ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "bad_layer",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert "Geographic layer not found." == ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "bad_graph",
        },
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert "Dual graph not found." == ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert (
        "Object creation failed. Reason: Failed to create view 'mayor_power'. "
        "(The path may already exist in the namespace.)"
    ) == ret.json()["detail"]

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power2",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template2",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
            "graph": "atlantis_dual",
        },
    )

    assert ret.status_code == HTTPStatus.CONFLICT
    assert (
        "Cannot create view. Some of the geographies are defined on a geo_layer that does "
        "not have the same geometries as the geo_layer in the namespace. Please ensure "
        "that all of the columns that you are trying to make a view for have the same "
        "geographies. The following columns sets have different geographies:"
    ) in ret.json()["detail"]
    assert "'population'" in ret.json()["detail"]
    assert "'mayor'" in ret.json()["detail"]

    ret = ctx.client.get(
        f"{API_PREFIX}/views/bad_ns/mayor_power",
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert (
        'Namespace "bad_ns" not found, or you do not have sufficient permissions '
        "to read views in this namespace."
    ) in ret.json()["detail"]

    ret = ctx.client.get(
        f"{API_PREFIX}/views/{ns.path}/bad_view",
    )

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert "View not found in namespace." == ret.json()["detail"]


def test_api_view_create_multiple_get_all(ctx_superuser):
    db = ctx_superuser.db
    ctx = ctx_superuser
    ctx.user
    meta = ctx.meta

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    grid_graph = nx.Graph()
    grid_graph.add_nodes_from(["central", "western"])
    grid_graph.add_edge("central", "western", weight=1.0)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=None,
                internal_point=None,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=None,
                internal_point=None,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis_blocks",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis_locality",
                parent_path=None,
                name="Atlantis",
                aliases=None,
            ),
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

    created_graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="atlantis_dual",
            description="The legendary city of Atlantis",
            locality="atlantis_locality",
            layer="atlantis_blocks",
            edges=[
                (a, b, {k: v for k, v in attr.items() if k != "id"})
                for (a, b), attr in grid_graph.edges.items()
            ],
        ),
        geo_set_version=crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0]),
        edge_geos={"central": geo[0][0], "western": geo[1][0]},
        obj_meta=meta,
        namespace=ns,
    )

    mayor_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=mayor_col,
        values=[
            (geo[0][0], "Poseidon"),
            (geo[1][0], "Poseidon"),
        ],
        obj_meta=meta,
    )

    pop_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=pop_col,
        values=[
            (geo[0][0], 1000),
            (geo[1][0], 2000),
        ],
        obj_meta=meta,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template",
            description="template for viewing mayor power",
            members=["mayor_power"],
        ),
        resolved_members=[col_set],
        obj_meta=meta,
        namespace=ns,
    )

    ret = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
        },
    )

    ret2 = ctx.client.post(
        f"{API_PREFIX}/views/{ns.path}",
        json={
            "path": "mayor_power2",
            "description": "how many people the mayor controls",
            "template": "mayor_power_template",
            "locality": "atlantis_locality",
            "layer": "atlantis_blocks",
        },
    )

    all_views = ctx.client.get(
        f"{API_PREFIX}/views/{ns.path}",
    )

    assert ret.json() in all_views.json()
    assert ret2.json() in all_views.json()
    assert ret != ret2
    assert len(all_views.json()) == 2

    ret = ctx.client.get(f"{API_PREFIX}/views/bad_ns")

    assert ret.status_code == HTTPStatus.NOT_FOUND
    assert (
        'Namespace "bad_ns" not found, or you do not have sufficient permissions '
        "to read views in this namespace."
    ) in ret.json()["detail"]
