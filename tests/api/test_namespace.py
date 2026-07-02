"""Tests for GerryDB REST API namespace endpoints."""

import random
from http import HTTPStatus

import pytest
from pydantic import ValidationError

from gerrydb_meta import crud, schemas
from gerrydb_meta.enums import NamespaceGroup, ScopeType
from gerrydb_meta.main import API_PREFIX

from .scopes import grant_scope

NAMESPACES_ROOT = f"{API_PREFIX}/namespaces"


@pytest.fixture
def ctx_with_namespace_rc_all(ctx_no_scopes_factory):
    """Client with global read/create namespace scopes."""
    ctx = ctx_no_scopes_factory()
    grant_scope(ctx.db, ctx.meta, ScopeType.NAMESPACE_READ, namespace_group=NamespaceGroup.ALL)
    grant_scope(ctx.db, ctx.meta, ScopeType.NAMESPACE_CREATE)
    yield ctx


@pytest.fixture
def ctx_with_namespace_ro_all(ctx_no_scopes_factory):
    """Client with global read/write namespace scopes."""
    ctx = ctx_no_scopes_factory()
    grant_scope(ctx.db, ctx.meta, ScopeType.NAMESPACE_READ, namespace_group=NamespaceGroup.ALL)
    yield ctx


@pytest.fixture
def ctx_with_namespace_rc_public(ctx_no_scopes_factory):
    """Client with public read/write/create namespace scopes (+ session and metadata)."""
    ctx = ctx_no_scopes_factory()
    grant_scope(
        ctx.db,
        ctx.meta,
        ScopeType.NAMESPACE_READ,
        namespace_group=NamespaceGroup.PUBLIC,
    )
    grant_scope(ctx.db, ctx.meta, ScopeType.NAMESPACE_CREATE)
    yield ctx


def test_path_too_long():
    with pytest.raises(ValidationError):
        schemas.NamespaceCreate(path="a" * 255)
    with pytest.raises(ValidationError):
        schemas.NamespaceCreate(path="a", description="b" * 10000, public=True)


def test_api_namespace_create_read__public(ctx_with_namespace_rc_all):
    # Create new namespace.
    path = "census.2020"
    description = "2020 Census data"

    create_response = ctx_with_namespace_rc_all.client.post(
        f"{NAMESPACES_ROOT}/",
        json={"path": path, "description": description, "public": True},
    )
    assert create_response.status_code == HTTPStatus.CREATED
    create_body = schemas.Namespace(**create_response.json())
    assert create_body.path == path
    assert create_body.description == description
    assert create_body.public

    # Read it back.
    read_response = ctx_with_namespace_rc_all.client.get(f"{NAMESPACES_ROOT}/{path}")
    assert read_response.status_code == HTTPStatus.OK
    read_body = schemas.Namespace(**read_response.json())
    assert read_body == create_body


def test_api_namespace_create__twice(ctx_with_namespace_rc_all):
    body = {"path": "census", "description": "Census data", "public": True}
    create_response = ctx_with_namespace_rc_all.client.post(f"{NAMESPACES_ROOT}/", json=body)
    assert create_response.status_code == HTTPStatus.CREATED

    create_again_response = ctx_with_namespace_rc_all.client.post(f"{NAMESPACES_ROOT}/", json=body)
    assert create_again_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_api_namespace_create_ro(ctx_with_namespace_ro_all):
    # Create new namespace.
    create_response = ctx_with_namespace_ro_all.client.post(
        f"{NAMESPACES_ROOT}/",
        json={"path": "census", "description": "Census data", "public": True},
    )
    assert create_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to create" in create_response.json()["detail"]


def test_api_namespace_read__missing(ctx_with_namespace_rc_all):
    read_response = ctx_with_namespace_rc_all.client.get(f"{NAMESPACES_ROOT}/missing")
    assert read_response.status_code == HTTPStatus.NOT_FOUND


def test_api_namespace_create_read__private(ctx_with_namespace_rc_public):
    ctx = ctx_with_namespace_rc_public
    private_ns_name = f"{__name__}_private_{random.randint(0, 10000)}"
    # Have admin create a private namespace.
    crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(path=private_ns_name, description="secret!", public=False),
        obj_meta=ctx.admin_meta,
    )
    read_response = ctx.client.get(f"{NAMESPACES_ROOT}/{private_ns_name}")
    assert read_response.status_code == HTTPStatus.NOT_FOUND


def test_api_namespace_all__private(ctx_with_namespace_rc_public):
    ctx = ctx_with_namespace_rc_public
    private_ns_name = f"{__name__}_private_{random.randint(0, 10000)}"
    crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(path=private_ns_name, description="secret!", public=False),
        obj_meta=ctx.admin_meta,
    )
    crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(path="public", description="not secret!", public=True),
        obj_meta=ctx.admin_meta,
    )

    list_response = ctx.client.get(f"{NAMESPACES_ROOT}/")
    assert list_response.status_code == HTTPStatus.OK
    list_body = list_response.json()
    assert len(list_body) == 1
    assert schemas.Namespace(**list_body[0]).path == "public"
