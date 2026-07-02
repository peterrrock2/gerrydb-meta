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
