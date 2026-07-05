"""Tests for GerryDB REST API locality endpoints."""

import logging
from http import HTTPStatus

import pytest

from gerrydb_meta import crud, schemas
from gerrydb_meta.enums import ScopeType
from gerrydb_meta.main import API_PREFIX

from .scopes import grant_scope

LOCALITIES_ROOT = f"{API_PREFIX}/localities"


@pytest.fixture
def ctx_locality_read_write(ctx_no_scopes_factory):
    """An API client with `LOCALITY_READ` and `LOCALITY_WRITE` scopes (+ session and metadata)."""
    ctx = ctx_no_scopes_factory()
    try:
        grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_READ)
        grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_WRITE)
    except Exception:
        pass
    yield ctx


@pytest.fixture
def ctx_locality_read_only(ctx_no_scopes_factory):
    """An API client with `LOCALITY_READ` scope (+ a preexisting locality)."""
    ctx = ctx_no_scopes_factory()
    try:
        grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_READ)
    except Exception:
        pass
    yield ctx


def test_api_locality_create_read__no_parent_no_aliases(ctx_locality_read_write):
    ctx = ctx_locality_read_write
    name = "Lost City of Atlantis"
    path = "atlantis"

    # Create new locality.
    create_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/", json=[{"name": name, "canonical_path": path}]
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.Locality(**create_response.json()[0])
    assert create_body.name == name
    assert create_body.canonical_path == path
    assert create_body.parent_path is None
    assert create_body.meta.uuid == ctx.meta.uuid

    # Read it back.
    read_response = ctx.client.get(f"{API_PREFIX}/localities/{path}")
    assert read_response.status_code == HTTPStatus.OK
    read_body = schemas.Locality(**read_response.json())
    assert read_body == create_body


def test_api_locality_create_read__parent_and_aliases(ctx_locality_read_write):
    ctx = ctx_locality_read_write
    name = "Lost City of Atlantis"
    path = "greece/atlantis"
    parent_path = "greece"
    aliases = ["atlantis", "g-atlantis"]

    # Create parent locality.
    create_parent_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/", json=[{"name": "Greece", "canonical_path": parent_path}]
    )
    assert create_parent_response.status_code == HTTPStatus.CREATED

    # Create child locality with aliases.
    create_child_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/",
        json=[
            {
                "name": name,
                "canonical_path": path,
                "parent_path": parent_path,
                "aliases": aliases,
            }
        ],
    )
    assert create_child_response.status_code == HTTPStatus.CREATED, create_child_response.json()
    create_child_body = schemas.Locality(**create_child_response.json()[0])
    assert create_child_body.name == name
    assert create_child_body.canonical_path == path
    assert create_child_body.aliases == aliases
    assert create_child_body.parent_path == parent_path
    assert create_child_body.meta.uuid == ctx.meta.uuid

    # Read back the parent and the child.
    read_response = ctx.client.get(f"{LOCALITIES_ROOT}/")
    assert read_response.status_code == HTTPStatus.OK
    read_body = [schemas.Locality(**obj) for obj in read_response.json()]
    assert set(loc.canonical_path for loc in read_body) == {path, parent_path}


def test_api_locality_create_read__with_redirects(ctx_locality_read_write):
    ctx = ctx_locality_read_write
    name = "Lost City of Atlantis"
    path = "greece/atlantis"
    alias = "atlantis"

    # Create child locality with aliases.
    create_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/",
        json=[{"name": name, "canonical_path": path, "aliases": [alias]}],
    )
    assert create_response.status_code == HTTPStatus.CREATED

    # Aliases serve the canonical body directly (no redirect: the old 308
    # URL rewrite corrupted URLs whose host or path contained the alias
    # string).
    read_response = ctx.client.get(f"{LOCALITIES_ROOT}/{alias}", follow_redirects=False)
    assert read_response.status_code == HTTPStatus.OK
    assert read_response.json()["canonical_path"] == path


def test_api_locality_create__with_no_meta(ctx_no_scopes):
    grant_scope(ctx_no_scopes.db, ctx_no_scopes.user, ScopeType.LOCALITY_WRITE)

    create_response = ctx_no_scopes.client.post(
        f"{LOCALITIES_ROOT}/",
        json=[{"name": "Greece", "canonical_path": "greece"}],
        headers={"x-gerrydb-meta-id": ""},
    )
    assert create_response.status_code == HTTPStatus.BAD_REQUEST
    assert "metadata" in create_response.json()["detail"]


def test_api_locality_create__scope_read_only(ctx_locality_read_only):
    ctx = ctx_locality_read_only
    grant_scope(ctx.db, ctx.user, ScopeType.LOCALITY_READ)

    create_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/", json=[{"name": "Greece", "canonical_path": "greece"}]
    )
    assert create_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to write" in create_response.json()["detail"]


def test_api_locality_create__bad_parent_path(ctx_locality_read_write):
    # Create child locality with aliases.
    create_response = ctx_locality_read_write.client.post(
        f"{LOCALITIES_ROOT}/",
        json=[
            {
                "name": "Lost City of Atlantis",
                "canonical_path": "greece/atlantis",
                "parent_path": "greece",
            },
        ],
    )
    assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "parent" in create_response.json()["detail"]


def test_api_locality_create__twice(ctx_locality_read_write):
    ctx = ctx_locality_read_write
    body = [
        {
            "name": "Lost City of Atlantis",
            "canonical_path": "greece/atlantis",
        }
    ]

    create_response = ctx.client.post(f"{LOCALITIES_ROOT}/", json=body)
    assert create_response.status_code == HTTPStatus.CREATED

    create_again_response = ctx.client.post(f"{LOCALITIES_ROOT}/", json=body)
    assert create_again_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "exist" in create_again_response.json()["detail"]

    read_response = ctx.client.get(f"{LOCALITIES_ROOT}/")
    assert read_response.status_code == HTTPStatus.OK
    assert len(read_response.json()) == 1


def test_api_locality_patch__add_aliases(ctx_locality_read_write):
    ctx = ctx_locality_read_write
    path = "greece/atlantis"
    aliases = ["atlantis", "g-atlantis"]

    create_response = ctx.client.post(
        f"{LOCALITIES_ROOT}/",
        json=[{"name": "Lost City of Atlantis", "canonical_path": path}],
    )
    assert create_response.status_code == HTTPStatus.CREATED

    patch_response = ctx.client.patch(f"{LOCALITIES_ROOT}/{path}", json={"aliases": aliases[:1]})
    assert patch_response.status_code == HTTPStatus.OK

    patch_again_response = ctx.client.patch(f"{LOCALITIES_ROOT}/{path}", json={"aliases": aliases})
    assert patch_again_response.status_code == HTTPStatus.OK
    patch_body = schemas.Locality(**patch_again_response.json())
    assert set(patch_body.aliases) == set(aliases)


def test_api_locality_patch__read_only(ctx_locality_read_only):
    ctx = ctx_locality_read_only
    path = "greece"
    grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_READ)

    # Create a locality to attempt to read via direct CRUD access.
    crud.locality.create_bulk(
        db=ctx.db,
        objs_in=[schemas.LocalityCreate(name="Greece", canonical_path=path)],
        obj_meta=ctx.meta,
    )

    patch_response = ctx.client.patch(
        f"{LOCALITIES_ROOT}/{path}", json={"aliases": [path + "_alias"]}
    )
    assert patch_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to write" in patch_response.json()["detail"]


def test_api_missing_loc_errors(ctx_locality_read_only, caplog):
    ctx = ctx_locality_read_only
    aliases = ["atlantis", "g/atlantis"]

    grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_READ)
    grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_WRITE)

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    response = ctx.client.get(f"{LOCALITIES_ROOT}/bad_path")
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "Locality not found" in response.json()["detail"]

    response = ctx.client.patch(f"{LOCALITIES_ROOT}/bad_path", json={"aliases": aliases[:1]})
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "Locality not found" in response.json()["detail"]
