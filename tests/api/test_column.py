"""Tests for GerryDB REST API column metadata endpoints."""

from http import HTTPStatus

from gerrydb_meta import schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.main import API_PREFIX

COLUMNS_ROOT = f"{API_PREFIX}/columns"


def test_api_column_create_read(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_body = schemas.Column(**create_response.json())
    assert create_body.canonical_path == pop_column_meta["canonical_path"]
    assert create_body.description == pop_column_meta["description"]
    assert str(create_body.source_url) == pop_column_meta["source_url"]
    assert create_body.kind == ColumnKind.COUNT
    assert create_body.type == ColumnType.INT
    assert set(create_body.aliases) == set(pop_column_meta["aliases"])

    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{create_body.canonical_path}"
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.Column(**read_response.json())
    assert read_body == create_body


def test_api_column_create_read__get_by_alias(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.Column(**create_response.json())

    alias = pop_column_meta["aliases"][0]
    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{alias}"
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.Column(**read_response.json())
    assert read_body == create_body


def test_api_column_create__twice(ctx_public_namespace_read_write, pop_column_meta):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    create_response = ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_twice_response = ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_twice_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (
        create_twice_response.json()
    )


def test_api_column_create_patch(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    path = pop_column_meta["canonical_path"]
    patch_response = ctx_public_namespace_read_write.client.patch(
        f"{COLUMNS_ROOT}/{namespace}/{path}",
        json={"aliases": ["another_alias"]},
    )
    assert patch_response.status_code == HTTPStatus.OK, patch_response.json()
    patch_body = schemas.Column(**patch_response.json())
    assert set(patch_body.aliases) == {*pop_column_meta["aliases"], "another_alias"}


def test_api_column_create_all(ctx_public_namespace_read_write, pop_column_meta, vap_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    canonical_paths = set()
    for col_meta in (pop_column_meta, vap_column_meta):
        create_response = ctx_public_namespace_read_write.client.post(
            f"{COLUMNS_ROOT}/{namespace}", json=col_meta
        )
        canonical_paths.add(col_meta["canonical_path"])
        assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = ctx_public_namespace_read_write.client.get(f"{COLUMNS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.OK, all_response.json()
    assert set(col["canonical_path"] for col in all_response.json()) == canonical_paths


def test_api_column_create_read__scope_read_only(ctx_public_namespace_read_only, pop_column_meta):
    namespace = ctx_public_namespace_read_only.namespace.path
    create_response = ctx_public_namespace_read_only.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()

    read_response = ctx_public_namespace_read_only.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}"
    )
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_column_create_read__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}"
    )
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_column_create_all__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = ctx_public_namespace_read_write.client.get(f"{COLUMNS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.NOT_FOUND, all_response.json()


def test_api_column_create_patch__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    patch_response = ctx_public_namespace_read_write.client.patch(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}",
        json={"aliases": ["another_alias"]},
    )
    assert patch_response.status_code == HTTPStatus.NOT_FOUND, patch_response.json()
