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

    view_render_context = crud.view.render(db=db, view=view)

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
