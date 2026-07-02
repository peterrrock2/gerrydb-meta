"""Tests for GerryDB REST API geographic layer endpoints."""

from http import HTTPStatus

import pytest

from gerrydb_meta import schemas
from gerrydb_meta.main import API_PREFIX

GEO_LAYERS_ROOT = f"{API_PREFIX}/layers"


@pytest.fixture
def geo_layer():
    """Geographic layer metadata."""
    return {"path": "layer", "description": "A geographic layer."}


def test_api_geo_layer_create_read(ctx_public_namespace_read_write, geo_layer):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.GeoLayer(**create_response.json())

    read_response = ctx.client.get(
        f"{GEO_LAYERS_ROOT}/{namespace}/layer",
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.GeoLayer(**read_response.json())
    assert read_body == create_body


def test_api_geo_layer_create_all(ctx_public_namespace_read_write, geo_layer):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.GeoLayer(**create_response.json())

    all_response = ctx.client.get(f"{GEO_LAYERS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.OK, all_response.json()
    assert len(all_response.json()) == 1
    read_body = schemas.GeoLayer(**all_response.json()[0])
    assert read_body == create_body


def test_api_geo_layer_create_read__scope_read_only(ctx_public_namespace_read_only, geo_layer):
    ctx = ctx_public_namespace_read_only
    namespace = ctx.namespace.path

    create_response = ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()

    read_response = ctx.client.get(f"{GEO_LAYERS_ROOT}/{namespace}/layer")
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_geo_layer_create__twice(ctx_public_namespace_read_write, geo_layer):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_twice_response = ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_twice_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (
        create_twice_response.json()
    )


def test_api_geo_layer_create_read__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
    geo_layer,
):
    public_ctx = ctx_public_namespace_read_write
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path

    create_response = private_ctx.client.post(
        f"{GEO_LAYERS_ROOT}/{namespace}",
        json=geo_layer,
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    read_response = public_ctx.client.get(f"{GEO_LAYERS_ROOT}/{namespace}/layer")
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_geo_layer_create_all__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
    geo_layer,
):
    public_ctx = ctx_public_namespace_read_write
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path

    create_response = private_ctx.client.post(f"{GEO_LAYERS_ROOT}/{namespace}", json=geo_layer)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = public_ctx.client.get(f"{GEO_LAYERS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.NOT_FOUND, all_response.json()
