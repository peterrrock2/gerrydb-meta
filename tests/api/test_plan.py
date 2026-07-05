import logging

from shapely import Point, Polygon

from gerrydb_meta import crud, schemas
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.main import API_PREFIX

PLAN_ROOT = f"{API_PREFIX}/plans"

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


def test_plan_create(ctx_superuser, caplog):
    db = ctx_superuser.db
    user = ctx_superuser.user
    meta = ctx_superuser.meta
    get_scopes(user)

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis_layer",
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
                canonical_path="atlantis_loc",
                parent_path=None,
                name="Locality of the Lost City of Atlantis",
                aliases=None,
            ),
        ],
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

    geography_list = [geo[0] for geo in geo]

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=geography_list,
        obj_meta=meta,
    )

    geo_set_version = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=loc[0])

    ret = ctx_superuser.client.post(
        f"{API_PREFIX}/plans/bad_namespace",
        json={
            "path": "atlantis_plan",
            "description": "A plan for the city of Atlantis",
            "source_url": "https://en.wikipedia.org/wiki/Atlantis",
            "districtr_id": "districtr_atlantis_plan",
            "locality": "atlantis_loc",
            "layer": "atlantis_layer",
            "assignments": {"central_atlantis": "1", "western_atlantis": "2"},
        },
    )

    assert ret.status_code == 404
    assert (
        "Namespace not found, or you do not have sufficient permissions "
        "to write plans in this namespace."
    ) in ret.json()["detail"]

    ret = ctx_superuser.client.post(
        f"{API_PREFIX}/plans/{ns.path}",
        json={
            "path": "atlantis_plan",
            "description": "A plan for the city of Atlantis",
            "source_url": "https://en.wikipedia.org/wiki/Atlantis",
            "districtr_id": "districtr_atlantis_plan",
            "locality": "atlantis_loc",
            "layer": "atlantis_layer",
            "assignments": {"central_atlantis": "1", "western_atlantis": "2"},
        },
    )

    ret = ctx_superuser.client.get(f"{API_PREFIX}/plans/{ns.path}/atlantis_plan")
    assert ret.json()["assignments"] == {
        "/atlantis/central_atlantis": "1",
        "/atlantis/western_atlantis": "2",
    }


def test_plan_routes_use_projections_not_orm_traversal(ctx_superuser):
    """Regression: plan list/get/create must not walk the assignment ORM graph.

    List responses carry no assignments at all; single get and create build
    the assignments dict from exactly two column projections (set members,
    assignment rows). Walking the relationships instead loads every
    assignment and member with its eager-joined geography, meta, and
    namespace, which is unusable at state scale.
    """
    from sqlalchemy import event

    db = ctx_superuser.db
    meta = ctx_superuser.meta
    ns = make_atlantis_ns(db, meta)
    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="proj_layer",
            description="Projection regression layer",
            source_url=None,
        ),
        obj_meta=meta,
        namespace=ns,
    )
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="proj_loc",
                parent_path=None,
                name="Projection regression locality",
                aliases=None,
            ),
        ],
        obj_meta=meta,
    )
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path="proj_geo_1", geography=None, internal_point=None),
            schemas.GeographyCreate(path="proj_geo_2", geography=None, internal_point=None),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )
    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geos],
        obj_meta=meta,
    )

    statements: list[str] = []
    engine = db.get_bind()

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def touched(kind: str | None = None) -> list[str]:
        hits = [s for s in statements if "plan_assignment" in s or "geo_set_member" in s]
        if kind is not None:
            hits = [s for s in hits if s.lstrip().upper().startswith(kind)]
        return hits

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        # Create: one INSERT into plan_assignment (the write itself), one
        # geo_set_member SELECT for membership validation, and the two
        # response projections. No other traversal is allowed.
        statements.clear()
        create_response = ctx_superuser.client.post(
            f"{PLAN_ROOT}/{ns.path}",
            json={
                "path": "proj_plan",
                "description": "Projection regression plan",
                "locality": "proj_loc",
                "layer": "proj_layer",
                "assignments": {"proj_geo_1": "1"},
            },
        )
        assert create_response.status_code == 201, create_response.json()
        assert create_response.json()["assignments"] == {
            f"/{ns.path}/proj_geo_1": "1",
            f"/{ns.path}/proj_geo_2": None,
        }
        assert len([s for s in touched("SELECT") if "plan_assignment" in s]) == 1
        assert len([s for s in touched("SELECT") if "geo_set_member" in s]) == 2

        # List: metadata only; the assignment/member tables must not be read.
        statements.clear()
        list_response = ctx_superuser.client.get(f"{PLAN_ROOT}/{ns.path}")
        assert list_response.status_code == 200, list_response.json()
        assert len(list_response.json()) == 1
        assert "assignments" not in list_response.json()[0]
        assert touched() == []

        # Single get: exactly the two projection SELECTs, nothing else.
        statements.clear()
        get_response = ctx_superuser.client.get(f"{PLAN_ROOT}/{ns.path}/proj_plan")
        assert get_response.status_code == 200, get_response.json()
        assert get_response.json()["assignments"] == {
            f"/{ns.path}/proj_geo_1": "1",
            f"/{ns.path}/proj_geo_2": None,
        }
        assert len(touched()) == 2
        assert all(s.lstrip().upper().startswith("SELECT") for s in touched())
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
