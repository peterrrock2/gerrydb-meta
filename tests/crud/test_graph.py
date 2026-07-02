import networkx as nx
import pytest
from shapely import Point, Polygon

from gerrydb_meta import crud, schemas
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


def test_crud_graph_create(db_with_meta):
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
            locality="atlantis",
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

    assert created_graph.path == "atlantis_dual"
    assert created_graph.description == "The legendary city of Atlantis"
    assert set((edge.geo_id_1, edge.geo_id_2) for edge in created_graph.edges) == {
        (geo[0][0].geo_id, geo[1][0].geo_id)
    } or set((edge.geo_id_1, edge.geo_id_2) for edge in created_graph.edges) == {
        (geo[1][0].geo_id, geo[0][0].geo_id)
    }


def test_crud_graph_create_bad_geos_error(db_with_meta):
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

    import2, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geo2, _ = crud.geography.create(
        db=db,
        obj_in=schemas.GeographyCreate(
            path="northern_atlantis",
            geography=None,
            internal_point=None,
        ),
        namespace=ns,
        obj_meta=meta,
        geo_import=import2,
    )

    with pytest.raises(
        CreateValueError, match="Geographies not associated with locality and layer"
    ):
        crud.graph.create(
            db=db,
            obj_in=schemas.GraphCreate(
                path="atlantis_dual",
                description="The legendary city of Atlantis",
                locality="atlantis",
                layer="atlantis_blocks",
                edges=[
                    (a, b, {k: v for k, v in attr.items() if k != "id"})
                    for (a, b), attr in grid_graph.edges.items()
                ],
            ),
            geo_set_version=crud.geo_layer.get_set_by_locality(
                db=db, layer=geo_layer, locality=loc[0]
            ),
            edge_geos={"central": geo[0][0], "western": geo[1][0], "northern": geo2[0]},
            obj_meta=meta,
            namespace=ns,
        )


def test_crud_graph_create_missing_geos(db_with_meta):
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

    with pytest.raises(
        CreateValueError,
        match=(
            "Passed edge geographies do not match the geographies associated with the "
            r"underlying graph. Missing edge geographies: \[western\]"
        ),
    ):
        _ = crud.graph.create(
            db=db,
            obj_in=schemas.GraphCreate(
                path="atlantis_dual",
                description="The legendary city of Atlantis",
                locality="atlantis",
                layer="atlantis_blocks",
                edges=[
                    (a, b, {k: v for k, v in attr.items() if k != "id"})
                    for (a, b), attr in grid_graph.edges.items()
                ],
            ),
            geo_set_version=crud.geo_layer.get_set_by_locality(
                db=db, layer=geo_layer, locality=loc[0]
            ),
            edge_geos={"central": geo[0][0]},
            obj_meta=meta,
            namespace=ns,
        )

    with pytest.raises(
        CreateValueError,
        match=(
            "Passed edge geographies do not match the geographies associated with the "
            r"underlying graph. Missing edge geographies: \[western\]"
        ),
    ):
        _ = crud.graph.create(
            db=db,
            obj_in=schemas.GraphCreate(
                path="atlantis_dual",
                description="The legendary city of Atlantis",
                locality="atlantis",
                layer="atlantis_blocks",
                edges=[
                    (b, a, {k: v for k, v in attr.items() if k != "id"})  # changed here
                    for (a, b), attr in grid_graph.edges.items()
                ],
            ),
            geo_set_version=crud.geo_layer.get_set_by_locality(
                db=db, layer=geo_layer, locality=loc[0]
            ),
            edge_geos={"central": geo[0][0]},
            obj_meta=meta,
            namespace=ns,
        )


def test_crud_graph_get(db_with_meta):
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
            locality="atlantis",
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

    retrieved_graph = crud.graph.get(
        db=db,
        path="atlantis_dual",
        namespace=ns,
    )

    assert created_graph.graph_id == retrieved_graph.graph_id
