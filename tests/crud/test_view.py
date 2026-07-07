import uuid
from datetime import datetime, timedelta, timezone

import networkx as nx
import pytest
from shapely import Point, Polygon

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.exceptions import CreateValueError

square_corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]

square = Polygon(square_corners)

internal_point = Point(0.0, 0.0)


def make_atlantis_ns(db, meta):
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )
    return ns


def test_view_create(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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
                canonical_path="atlantis",
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

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            template="mayor_power_template",
            locality="atlantis_loc",
            layer="atlantis_blocks",
            graph="atlantis_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=created_graph,
    )

    assert view.template_id == view_template.template_id
    assert view.loc_id == loc[0].loc_id
    assert view.layer_id == geo_layer.layer_id
    assert view.graph_id == created_graph.graph_id
    assert view.num_geos == 2
    assert view.loc == loc[0]
    assert view.layer == geo_layer
    assert view.graph == created_graph
    assert view.template_version == view_template


def test_view_get(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            template="mayor_power_template",
            locality="atlantis_locality",
            layer="atlantis_blocks",
            graph="atlantis_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=created_graph,
    )

    retrieved = crud.view.get(db=db, path="mayor_power", namespace=ns)

    assert retrieved == view


def test_view_render(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            template="mayor_power_template",
            locality="atlantis_loc",
            layer="atlantis_blocks",
            graph="atlantis_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=created_graph,
    )

    geo_set_version = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])

    plan, _ = crud.plan.create(
        db=db,
        obj_in=schemas.PlanCreate(
            path="atlantis_plan",
            description="A plan for the city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
            districtr_id="districtr_atlantis_plan",
            daves_id="daves_atlantis_plan",
            locality="atlantis_loc",
            layer="atlantis_layer",
            assignments={"central_atlantis": "1", "western_atlantis": "2"},
        ),
        geo_set_version=geo_set_version,
        obj_meta=meta,
        namespace=ns,
        assignments={geo[0][0]: "1", geo[1][0]: "2"},
    )

    view_render_context = crud.view.render(db=db, view=view, include_plans=True)

    assert set(view_render_context.columns.keys()) == set(["mayor", "population"])
    assert view_render_context.plan_labels == ["atlantis_plan"]

    new_plan_assignment_list = [(b, c) for a, b, c in view_render_context.plan_assignments]
    assert new_plan_assignment_list == [
        ("central_atlantis", "1"),
        ("western_atlantis", "2"),
    ]


def test_view_make_and_get_cached_render(db_with_meta_and_user):
    db, meta, user = db_with_meta_and_user

    ns = make_atlantis_ns(db, meta)

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

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            template="mayor_power_template",
            locality="atlantis_loc",
            layer="atlantis_blocks",
            graph="atlantis_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
        graph=created_graph,
    )

    geo_set_version = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])

    plan, _ = crud.plan.create(
        db=db,
        obj_in=schemas.PlanCreate(
            path="atlantis_plan",
            description="A plan for the city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
            districtr_id="districtr_atlantis_plan",
            daves_id="daves_atlantis_plan",
            locality="atlantis_loc",
            layer="atlantis_layer",
            assignments={"central_atlantis": "1", "western_atlantis": "2"},
        ),
        geo_set_version=geo_set_version,
        obj_meta=meta,
        namespace=ns,
        assignments={geo[0][0]: "1", geo[1][0]: "2"},
    )

    _ = crud.view.render(db=db, view=view)

    render_uuid = uuid.uuid4()

    cashed_render = crud.view.cache_render(
        db=db, view=view, created_by=user, render_id=render_uuid, path="mayor_power"
    )

    retrieved_cashed_render = crud.view.get_cached_render(db=db, view=view)

    assert retrieved_cashed_render == cashed_render


import logging
from unittest.mock import patch


def test_view_errors(db_with_meta, caplog):
    db, meta = db_with_meta

    caplog.set_level(logging.DEBUG, logger="uvicorn.error")

    ns = make_atlantis_ns(db, meta)

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
                canonical_path="atlantis",
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

    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis2",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    with pytest.raises(
        CreateValueError,
        match=(
            "No set of geographies exists in the current namespace satisfying locality "
            "and layer constraints."
        ),
    ):
        view, _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual",
            ),
            obj_meta=meta,
            namespace=ns2,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
        )

    with pytest.raises(
        CreateValueError,
        match=(
            "Cannot instantiate view: no set of geographies exists satisfying locality, "
            "layer, and time constraints for the columns in the view template."
        ),
    ):
        with patch.object(crud.view, "_CRView__get_all_set_col_ids", return_value=[]):
            _ = crud.view.create(
                db=db,
                obj_in=schemas.ViewCreate(
                    path="mayor_power",
                    description="how many people the mayor controls",
                    template="mayor_power_template",
                    locality="atlantis_loc",
                    layer="atlantis_blocks",
                    graph="atlantis_dual",
                ),
                obj_meta=meta,
                namespace=ns,
                template=view_template,
                locality=loc[0],
                layer=geo_layer,
            )

    with pytest.raises(CreateValueError, match="Cannot instantiate view in the future"):
        _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual",
                valid_at=datetime(3000, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
        )

    with pytest.raises(
        CreateValueError, match="No template version found satisfying time constraints"
    ):
        new_template = models.ViewTemplate(
            template_id=9000,
            namespace_id=ns.namespace_id,
            path="mayor_power_template",
            description="template for viewing mayor power",
            meta_id=meta.meta_id,
            meta=view_template.meta,
            namespace=ns,
        )
        _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual",
            ),
            obj_meta=meta,
            namespace=ns,
            template=new_template,
            locality=loc[0],
            layer=geo_layer,
        )

    geo_import2, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns2)

    geo2, _ = crud.geography.create_bulk(
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
        geo_import=geo_import2,
        namespace=ns2,
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
        geo_set_version=crud.geo_layer.get_set_by_locality(
            db=db, layer=geo_layer2, locality=loc[0]
        ),
        edge_geos={"central": geo2[0][0], "western": geo2[1][0]},
        obj_meta=meta,
        namespace=ns,
    )

    with pytest.raises(
        CreateValueError,
        match='Cannot instantiate view: graph "/atlantis/atlantis_dual" does not match locality',
    ):
        _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual",
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
            graph=created_graph,
        )

    recreated_graph, _ = crud.graph.create(
        db=db,
        obj_in=schemas.GraphCreate(
            path="atlantis_dual2",
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

    with pytest.raises(
        CreateValueError,
        match='Cannot instantiate view: graph "/atlantis/atlantis_dual2" exists in the future',
    ):
        recreated_graph.created_at = datetime(3000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual2",
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
            graph=recreated_graph,
        )

    with pytest.raises(
        CreateValueError,
        match=(
            "Cannot instantiate view: column values satisfying all constraints constraints "
            "not available for all geographies."
        ),
    ):
        _ = crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="mayor_power",
                description="how many people the mayor controls",
                template="mayor_power_template",
                locality="atlantis_loc",
                layer="atlantis_blocks",
                graph="atlantis_dual2",
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
        )


def test_view_create_cols_multiple_namespaces(db_with_meta, caplog):
    db, meta = db_with_meta

    caplog.set_level(logging.DEBUG, logger="uvicorn.error")

    ns = make_atlantis_ns(db, meta)
    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis2",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    loc, _ = crud.locality.create(
        db=db,
        obj_in=schemas.LocalityCreate(
            canonical_path="atlantis",
            parent_path=None,
            name="Atlantis",
            aliases=None,
        ),
        obj_meta=meta,
    )

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

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc,
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    geo_import2, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns2)

    geo2, _ = crud.geography.create_bulk(
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
        geo_import=geo_import2,
        namespace=ns2,
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

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer2,
        locality=loc,
        geographies=[geo[0] for geo in geo2],
        obj_meta=meta,
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
        namespace=ns2,
    )

    crud.column.set_values(
        db=db,
        col=pop_col,
        values=[
            (geo2[0][0], 1000),
            (geo2[1][0], 2000),
        ],
        obj_meta=meta,
    )

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template",
            description="template for viewing mayor power",
            members=["mayor", "population"],
        ),
        resolved_members=[pop_col.canonical_ref, mayor_col.canonical_ref],
        obj_meta=meta,
        namespace=ns,
    )

    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            template="mayor_power_template",
            locality="atlantis_loc",
            layer="atlantis_blocks",
            graph="atlantis_dual",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc,
        layer=geo_layer,
    )

    assert view.template_id == view_template.template_id
    assert view.loc_id == loc.loc_id
    assert view.layer_id == geo_layer.layer_id
    assert view.num_geos == 2
    assert view.loc == loc
    assert view.layer == geo_layer
    assert view.template_version == view_template


def test_view_create_historical_valid_at_uses_scan(db_with_meta, monkeypatch):
    """A view anchored before its values existed must fail validation.

    The stats table only knows CURRENT value coverage; a historical valid_at
    must take the as-of column_value scan, which sees zero values at that
    timestamp even though coverage is complete now. The freshness slack is
    zeroed so a milliseconds-old anchor counts as historical.
    """
    import importlib

    view_module = importlib.import_module("gerrydb_meta.crud.view")
    monkeypatch.setattr(view_module, "STATS_FRESHNESS_SLACK", timedelta(0))
    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path="hist_a", geography=None, internal_point=None),
            schemas.GeographyCreate(path="hist_b", geography=None, internal_point=None),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )
    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(path="hist_blocks", description="test"),
        obj_meta=meta,
        namespace=ns,
    )
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[schemas.LocalityCreate(canonical_path="hist_loc", name="Hist", aliases=None)],
        obj_meta=meta,
    )
    crud.geo_layer.map_locality(
        db=db, layer=geo_layer, locality=loc[0], geographies=[g[0] for g in geo], obj_meta=meta
    )
    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="hist_pop",
            description="test",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )
    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="hist_template", description="test", members=["hist_pop"]
        ),
        resolved_members=[col.canonical_ref],
        obj_meta=meta,
        namespace=ns,
    )
    before_values = datetime.now(timezone.utc)
    crud.column.set_values(
        db=db, col=col, values=[(geo[0][0], 1), (geo[1][0], 2)], obj_meta=meta
    )

    # Anchored now: the stats table validates coverage and the view creates.
    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="hist_now",
            description="test",
            template="hist_template",
            locality="hist_loc",
            layer="hist_blocks",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
    )
    assert view.num_geos == 2

    # Anchored before the values existed: must fail via the as-of scan.
    with pytest.raises(CreateValueError, match="Bad columns"):
        crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="hist_backdated",
                description="test",
                template="hist_template",
                locality="hist_loc",
                layer="hist_blocks",
                valid_at=before_values,
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
        )


def test_view_create_historical_valid_at_uses_scan_default_slack(db_with_meta):
    """The shipping freshness gate (no monkeypatch) sends historical anchors
    to the as-of scan.

    Fixtures are backdated in SQL so a 30-minute-old anchor is genuinely
    historical under the default slack; the values appeared only 10 minutes
    ago, so validation must fail via the scan even though CURRENT coverage
    (what the stats table sees) is complete.
    """
    from sqlalchemy import text as sql_text

    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path="hist2_a", geography=None, internal_point=None),
            schemas.GeographyCreate(path="hist2_b", geography=None, internal_point=None),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )
    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(path="hist2_blocks", description="test"),
        obj_meta=meta,
        namespace=ns,
    )
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[schemas.LocalityCreate(canonical_path="hist2_loc", name="Hist2", aliases=None)],
        obj_meta=meta,
    )
    crud.geo_layer.map_locality(
        db=db, layer=geo_layer, locality=loc[0], geographies=[g[0] for g in geo], obj_meta=meta
    )
    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="hist2_pop",
            description="test",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )
    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="hist2_template", description="test", members=["hist2_pop"]
        ),
        resolved_members=[col.canonical_ref],
        obj_meta=meta,
        namespace=ns,
    )
    crud.column.set_values(
        db=db, col=col, values=[(geo[0][0], 1), (geo[1][0], 2)], obj_meta=meta
    )

    # Backdate the resolution fixtures an hour, and the values to 10 minutes
    # ago, so a 30-minute anchor resolves the template and set version but
    # predates the values.
    set_version = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])
    db.execute(
        sql_text(
            "UPDATE gerrydb.view_template_version "
            "SET valid_from = now() - interval '1 hour' WHERE template_id = :tid"
        ),
        {"tid": view_template.template_id},
    )
    db.execute(
        sql_text(
            "UPDATE gerrydb.geo_set_version "
            "SET valid_from = now() - interval '1 hour' WHERE set_version_id = :svid"
        ),
        {"svid": set_version.set_version_id},
    )
    db.execute(
        sql_text(
            "UPDATE gerrydb.column_value "
            "SET valid_from = now() - interval '10 minutes' WHERE col_id = :cid"
        ),
        {"cid": col.col_id},
    )

    anchor = datetime.now(timezone.utc) - timedelta(minutes=30)
    with pytest.raises(CreateValueError, match="Bad columns"):
        crud.view.create(
            db=db,
            obj_in=schemas.ViewCreate(
                path="hist2_backdated",
                description="test",
                template="hist2_template",
                locality="hist2_loc",
                layer="hist2_blocks",
                valid_at=anchor,
            ),
            obj_meta=meta,
            namespace=ns,
            template=view_template,
            locality=loc[0],
            layer=geo_layer,
        )

    # A now-anchored view of the same data validates via the stats table.
    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="hist2_now",
            description="test",
            template="hist2_template",
            locality="hist2_loc",
            layer="hist2_blocks",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc[0],
        layer=geo_layer,
    )
    assert view.num_geos == 2


def test_view_create_clone_ref_pins_and_survives_repoint(db_with_meta):
    """A view over a target-namespace clone ref resolves the source column's
    sets (creation succeeds pre-materialization), and repointing the ref
    afterwards does not move the existing template version's resolution."""
    from gerrydb_meta.crud.view import _view_columns

    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)
    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis_source",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )

    loc, _ = crud.locality.create(
        db=db,
        obj_in=schemas.LocalityCreate(
            canonical_path="atlantis",
            parent_path=None,
            name="Atlantis",
            aliases=None,
        ),
        obj_meta=meta,
    )

    geos_by_ns = {}
    layers_by_ns = {}
    for namespace in (ns, ns2):
        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=namespace)
        geos, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(path="central_atlantis", geography=None, internal_point=None),
                schemas.GeographyCreate(path="western_atlantis", geography=None, internal_point=None),
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=namespace,
        )
        layer, _ = crud.geo_layer.create(
            db=db,
            obj_in=schemas.GeoLayerCreate(
                path="atlantis_blocks",
                description="The legendary city of Atlantis",
                source_url="https://en.wikipedia.org/wiki/Atlantis",
            ),
            obj_meta=meta,
            namespace=namespace,
        )
        crud.geo_layer.map_locality(
            db=db,
            layer=layer,
            locality=loc,
            geographies=[g[0] for g in geos],
            obj_meta=meta,
        )
        geos_by_ns[namespace.path] = geos
        layers_by_ns[namespace.path] = layer

    # Values live only in the source namespace.
    pop_col, _ = crud.column.create(
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
            (geos_by_ns["atlantis_source"][0][0], 1000),
            (geos_by_ns["atlantis_source"][1][0], 2000),
        ],
        obj_meta=meta,
    )

    clone_ref, _ = crud.column.create_reference(
        db=db, path="population", namespace=ns, col=pop_col, obj_meta=meta
    )
    assert clone_ref.namespace_id == ns.namespace_id

    view_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="clone_template",
            description="template over a cloned column",
            members=["population"],
        ),
        resolved_members=[clone_ref],
        obj_meta=meta,
        namespace=ns,
    )

    # Creation succeeds even though the values and stats live under the
    # source namespace's set version, because resolution keys on the pinned
    # column's namespace rather than the clone ref's.
    view, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="clone_view",
            description="view over a cloned column",
            template="clone_template",
            locality="atlantis",
            layer="atlantis_blocks",
        ),
        obj_meta=meta,
        namespace=ns,
        template=view_template,
        locality=loc,
        layer=layers_by_ns["atlantis"],
    )
    assert view.num_geos == 2
    resolved = _view_columns(db, view_template.template_version_id)
    assert resolved["population"].col_id == pop_col.col_id

    # Simulate materialization's repoint: the clone path now names a new
    # local column. The existing template version must keep its pin.
    new_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population_materialized",
            description="locally owned population",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )
    crud.column.set_values(
        db=db,
        col=new_col,
        values=[
            (geos_by_ns["atlantis"][0][0], 1111),
            (geos_by_ns["atlantis"][1][0], 2222),
        ],
        obj_meta=meta,
    )
    clone_ref.col_id = new_col.col_id
    db.flush()
    db.expire(clone_ref)

    resolved_after = _view_columns(db, view_template.template_version_id)
    assert resolved_after["population"].col_id == pop_col.col_id

    # A template version created after the repoint resolves the new column.
    post_template, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="post_repoint_template",
            description="template created after the repoint",
            members=["population"],
        ),
        resolved_members=[clone_ref],
        obj_meta=meta,
        namespace=ns,
    )
    resolved_post = _view_columns(db, post_template.template_version_id)
    assert set(resolved_post) == {"population_materialized"}
    assert resolved_post["population_materialized"].col_id == new_col.col_id


def test_view_clone_diverge_end_to_end(db_with_meta):
    """Full clone lifecycle: a view created over a clone serves source values
    forever; after materialization + divergence, a new view serves the
    diverged values, and fingerprints differ only where values do."""
    from sqlalchemy import text as sa_text

    from gerrydb_meta.crud.view import _view_columns

    db, meta = db_with_meta

    src_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="e2esrc", description="d", public=True),
        obj_meta=meta,
    )
    tgt_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="e2etgt", description="d", public=True),
        obj_meta=meta,
    )
    loc, _ = crud.locality.create(
        db=db,
        obj_in=schemas.LocalityCreate(
            canonical_path="e2eloc", parent_path=None, name="E2E", aliases=None
        ),
        obj_meta=meta,
    )
    geos_by_ns = {}
    layers_by_ns = {}
    for namespace in (src_ns, tgt_ns):
        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=namespace)
        geos, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(path=f"e{i}", geography=None, internal_point=None)
                for i in range(2)
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=namespace,
        )
        layer, _ = crud.geo_layer.create(
            db=db,
            obj_in=schemas.GeoLayerCreate(path="e2elayer", description="d"),
            obj_meta=meta,
            namespace=namespace,
        )
        crud.geo_layer.map_locality(
            db=db, layer=layer, locality=loc, geographies=[g[0] for g in geos], obj_meta=meta
        )
        geos_by_ns[namespace.path] = [g[0] for g in geos]
        layers_by_ns[namespace.path] = layer

    pop_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="pop", description="d", kind=ColumnKind.COUNT, type=ColumnType.INT
        ),
        obj_meta=meta,
        namespace=src_ns,
    )
    crud.column.set_values(
        db=db,
        col=pop_col,
        values=[(g, 100 + i) for i, g in enumerate(geos_by_ns["e2esrc"])],
        obj_meta=meta,
    )

    clone_ref, _ = crud.column.create_reference(
        db, path="pop", namespace=tgt_ns, col=pop_col, obj_meta=meta
    )
    template_v1, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="e2e_template", description="d", members=["pop"]
        ),
        resolved_members=[clone_ref],
        obj_meta=meta,
        namespace=tgt_ns,
    )
    view1, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="e2e_view_v1",
            description="pre-divergence",
            template="e2e_template",
            locality="e2eloc",
            layer="e2elayer",
        ),
        obj_meta=meta,
        namespace=tgt_ns,
        template=template_v1,
        locality=loc,
        layer=layers_by_ns["e2etgt"],
    )
    assert view1.num_geos == 2

    def current_values(col_id: int) -> dict[str, int]:
        rows = db.execute(
            sa_text(
                "SELECT g.path, cv.val_int FROM gerrydb.column_value cv "
                "JOIN gerrydb.geography g ON g.geo_id = cv.geo_id "
                f"WHERE cv.col_id = {col_id} AND cv.valid_to IS NULL"
            )
        ).all()
        return {r.path: r.val_int for r in rows}

    v1_col = _view_columns(db, view1.template_version_id)["pop"]
    assert v1_col.col_id == pop_col.col_id
    assert current_values(v1_col.col_id) == {"e0": 100, "e1": 101}

    # Diverge: materialize the clone, then change one value locally.
    owned_col, _ = crud.column.materialize(db, ref=clone_ref, obj_meta=meta)
    crud.column.set_values(
        db=db,
        col=owned_col,
        values=[(geos_by_ns["e2etgt"][0], 999)],
        obj_meta=meta,
    )

    template_v2, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="e2e_template_v2", description="d", members=["pop"]
        ),
        resolved_members=[clone_ref],
        obj_meta=meta,
        namespace=tgt_ns,
    )
    view2, _ = crud.view.create(
        db=db,
        obj_in=schemas.ViewCreate(
            path="e2e_view_v2",
            description="post-divergence",
            template="e2e_template_v2",
            locality="e2eloc",
            layer="e2elayer",
        ),
        obj_meta=meta,
        namespace=tgt_ns,
        template=template_v2,
        locality=loc,
        layer=layers_by_ns["e2etgt"],
    )

    # The old view still pins and serves the source; the new one serves the
    # diverged values.
    assert _view_columns(db, view1.template_version_id)["pop"].col_id == pop_col.col_id
    assert current_values(pop_col.col_id) == {"e0": 100, "e1": 101}
    v2_col = _view_columns(db, view2.template_version_id)["pop"]
    assert v2_col.col_id == owned_col.col_id
    assert current_values(owned_col.col_id) == {"e0": 999, "e1": 101}

    # Fingerprints: identical before the divergent write would have matched;
    # after it, the two columns' stats differ.
    src_stats = (
        db.query(models.ColumnValueCount).filter_by(col_id=pop_col.col_id).one()
    )
    tgt_stats = (
        db.query(models.ColumnValueCount).filter_by(col_id=owned_col.col_id).one()
    )
    assert src_stats.count == tgt_stats.count == 2
    assert (src_stats.value_hash_hi, src_stats.value_hash_lo) != (
        tgt_stats.value_hash_hi,
        tgt_stats.value_hash_lo,
    )
