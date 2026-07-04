"""Tests for GerryDB REST API geography endpoints."""

from http import HTTPStatus

import msgpack
import pytest
import shapely.wkb
from shapely import box
from shapely.geometry import Point, Polygon

from gerrydb_meta import crud, schemas
from gerrydb_meta.main import API_PREFIX

GEOS_ROOT = f"{API_PREFIX}/geographies"


def geo_import_id(ctx) -> str:
    """Creates a GeoImport ID (direct CRUD)."""
    geo_import, _ = crud.geo_import.create(
        db=ctx.db,
        obj_meta=ctx.meta,
        namespace=ctx.namespace,
    )
    return geo_import.uuid.hex


def headers(ctx) -> str:
    """Generates headers for POST requests."""
    return {
        "content-type": "application/msgpack",
        "x-gerrydb-geo-import-id": geo_import_id(ctx),
    }


@pytest.fixture
def unit_box():
    """Shapely polygon representation of the unit square."""
    return box(0, 0, 1, 1)


@pytest.fixture
def unit_box_wkb(unit_box):
    """WKB encoding of the unit square."""
    return shapely.wkb.dumps(unit_box)


@pytest.fixture
def unit_box_msgpack(unit_box_wkb):
    """Msgpack encoding of `box` geography."""
    return msgpack.dumps([{"path": "box", "geography": unit_box_wkb}])


def test_api_geography_create_read(ctx_public_namespace_read_write, unit_box, unit_box_msgpack):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)

    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])

    assert create_body.path == "box"
    assert create_body.internal_point == Point().wkb
    assert shapely.wkb.loads(create_body.geography) == unit_box

    read_response = ctx.client.get(f"{GEOS_ROOT}/{namespace}/box")
    assert read_response.status_code == HTTPStatus.OK, read_response.json()

    read_body = schemas.GeographyMeta(**read_response.json())
    assert read_body.path == "box"
    assert read_body.namespace == namespace
    assert read_body.meta == create_body.meta


def test_api_geography_create_all(ctx_public_namespace_read_write, unit_box_msgpack):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)
    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])

    all_response = ctx.client.get(f"{GEOS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.OK, all_response.json()
    assert len(all_response.json()) == 1

    all_body = schemas.GeographyMeta(**all_response.json()[0])
    assert all_body.path == "box"
    assert all_body.namespace == namespace
    assert all_body.meta == create_body.meta


def test_api_geography_create__internal_point(
    ctx_public_namespace_read_write, unit_box, unit_box_wkb
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    internal_point = Point(0.5, 0.5)
    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps(
            [
                {
                    "path": "box",
                    "geography": unit_box_wkb,
                    "internal_point": shapely.wkb.dumps(internal_point),
                }
            ]
        ),
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)

    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])
    assert create_body.path == "box"
    assert create_body.namespace == namespace
    assert shapely.wkb.loads(create_body.internal_point) == internal_point
    assert shapely.wkb.loads(create_body.geography) == unit_box


def test_api_geography_create__missing_geos(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps([{"path": "box", "geography": None, "internal_point": None}]),
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)

    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])
    assert create_body.internal_point == Point().wkb
    assert create_body.geography == Polygon().wkb


def test_api_geography_create__malformed_wkb(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps(
            [{"path": "box", "geography": b"123"}]  # not a valid WKB-encoded geometry
        ),
    )
    assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, create_response.json()


def test_api_geography_create__twice(ctx_public_namespace_read_write, unit_box_msgpack):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_twice_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert create_twice_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (
        create_twice_response.json()
    )


def test_api_geography_create_patch(ctx_public_namespace_read_write, unit_box_msgpack):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)
    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])

    # Implicitly create a new GeoVersion for the geography.
    shifted_unit_box = box(1, 1, 2, 2)
    shifted_internal_point = Point(1.5, 1.5)
    patch_response = ctx.client.patch(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps(
            [
                {
                    "path": "box",
                    "geography": shapely.wkb.dumps(shifted_unit_box),
                    "internal_point": shapely.wkb.dumps(shifted_internal_point),
                }
            ]
        ),
    )
    assert patch_response.status_code == HTTPStatus.OK, msgpack.loads(patch_response.content)

    patch_body = schemas.Geography(**msgpack.loads(patch_response.content)[0])
    assert shapely.wkb.loads(patch_body.geography) == shifted_unit_box
    assert shapely.wkb.loads(patch_body.internal_point) == shifted_internal_point
    assert patch_body.valid_from > create_body.valid_from


def test_api_geography_create_patch__return_geos_false(
    ctx_public_namespace_read_write, unit_box, unit_box_msgpack
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=unit_box_msgpack,
        params={"return_geos": "false"},
    )
    assert create_response.status_code == HTTPStatus.CREATED, msgpack.loads(create_response.content)
    create_body = schemas.Geography(**msgpack.loads(create_response.content)[0])
    assert create_body.path == "box"
    assert create_body.geography is None
    assert create_body.internal_point is None
    assert create_body.valid_from is not None

    shifted_unit_box = box(1, 1, 2, 2)
    patch_response = ctx.client.patch(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps([{"path": "box", "geography": shapely.wkb.dumps(shifted_unit_box)}]),
        params={"return_geos": "false"},
    )
    assert patch_response.status_code == HTTPStatus.OK, msgpack.loads(patch_response.content)
    patch_body = schemas.Geography(**msgpack.loads(patch_response.content)[0])
    assert patch_body.geography is None
    assert patch_body.valid_from > create_body.valid_from

    # A default (echoing) patch shows the slim create/patch really stored shapes.
    final_box = box(2, 2, 3, 3)
    echo_response = ctx.client.patch(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(ctx),
        content=msgpack.dumps([{"path": "box", "geography": shapely.wkb.dumps(final_box)}]),
    )
    assert echo_response.status_code == HTTPStatus.OK, msgpack.loads(echo_response.content)
    echo_body = schemas.Geography(**msgpack.loads(echo_response.content)[0])
    assert shapely.wkb.loads(echo_body.geography) == final_box


def test_api_geography_patch__nonexistent(ctx_public_namespace_read_write, unit_box_msgpack):
    ctx = ctx_public_namespace_read_write
    patch_response = ctx.client.patch(
        f"{GEOS_ROOT}/{ctx.namespace.path}",
        headers=headers(ctx),
        content=unit_box_msgpack,
    )
    assert patch_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, patch_response.json()


def test_api_geography_create_read__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
    unit_box_msgpack,
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(private_ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    read_response = ctx_public_namespace_read_write.client.get(f"{GEOS_ROOT}/{namespace}/box")
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_geography_create_all__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
    unit_box_msgpack,
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(private_ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = ctx_public_namespace_read_write.client.get(f"{GEOS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.NOT_FOUND, all_response.json()


def test_api_geography_create_patch__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
    unit_box_msgpack,
):
    private_ctx = ctx_private_namespace_read_write
    public_ctx = ctx_public_namespace_read_write

    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(private_ctx),
        content=unit_box_msgpack,
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    patch_response = public_ctx.client.patch(
        f"{GEOS_ROOT}/{namespace}",
        headers=headers(public_ctx),
        content=unit_box_msgpack,
    )
    assert patch_response.status_code == HTTPStatus.NOT_FOUND, patch_response.json()
