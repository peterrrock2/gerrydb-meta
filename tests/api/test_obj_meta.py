"""Tests for GerryDB REST API object metadata endpoints."""

from http import HTTPStatus

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.enums import ScopeType
from gerrydb_meta.main import API_PREFIX

from .scopes import grant_scope

META_ROOT = f"{API_PREFIX}/meta"


def create_new_user_meta(db: Session) -> models.ObjectMeta:
    """Creates metadata associated with a new user."""

    # TODO: fix this abstraction violation (use `crud` instead)
    # once users are exposed via API.
    user = models.User(name="other user", email="other@example.com")
    db.add(user)
    db.flush()
    db.refresh(user)

    return crud.obj_meta.create(db=db, obj_in=schemas.ObjectMetaCreate(notes="secret!"), user=user)


def test_notes_too_long() -> models.ObjectMeta:
    """Creates metadata associated with a new user."""
    with pytest.raises(ValidationError):
        schemas.ObjectMetaCreate(notes="a" * 10000)


def test_api_object_meta_create_read(ctx_no_scopes):
    ctx = ctx_no_scopes
    notes = "test"
    grant_scope(ctx.db, ctx.user, ScopeType.META_WRITE)

    # Create new metadata.
    create_response = ctx.client.post(f"{META_ROOT}/", json={"notes": notes})
    assert create_response.status_code == HTTPStatus.CREATED
    create_body = schemas.ObjectMeta(**create_response.json())
    assert create_body.notes == notes
    assert create_body.created_by == ctx.user.email

    # Read it back.
    read_response = ctx.client.get(f"{META_ROOT}/{create_body.uuid}")
    assert read_response.status_code == HTTPStatus.OK
    read_body = schemas.ObjectMeta(**read_response.json())
    assert read_body == create_body


def test_api_object_meta_create__no_scopes(ctx_no_scopes):
    create_response = ctx_no_scopes.client.post(f"{META_ROOT}/", json={"notes": ""})
    assert create_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to write metadata" in create_response.json()["detail"]


def test_api_object_meta_create__read_only(ctx_no_scopes):
    ctx = ctx_no_scopes
    grant_scope(ctx.db, ctx.meta, ScopeType.META_READ)

    create_response = ctx.client.post(f"{META_ROOT}/", json={"notes": ""})
    assert create_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to write metadata" in create_response.json()["detail"]


def test_api_object_meta_read__other_user_no_read_scope(ctx_no_scopes):
    ctx = ctx_no_scopes
    grant_scope(ctx.db, ctx.user, ScopeType.META_WRITE)
    other_user_meta = create_new_user_meta(ctx.db)

    # Read metadata created by the other user.
    read_response = ctx.client.get(f"{META_ROOT}/{other_user_meta.uuid}")
    assert read_response.status_code == HTTPStatus.FORBIDDEN
    assert "permissions to read metadata" in read_response.json()["detail"]


def test_api_object_meta_read__other_user_read_scope(ctx_no_scopes):
    ctx = ctx_no_scopes
    grant_scope(ctx.db, ctx.user, ScopeType.META_READ)
    other_user_meta = create_new_user_meta(ctx.db)

    # Read metadata created by the other user.
    read_response = ctx.client.get(f"{META_ROOT}/{other_user_meta.uuid}")
    assert read_response.status_code == HTTPStatus.OK


def test_errors_in_get(ctx_no_scopes):
    ctx = ctx_no_scopes
    grant_scope(ctx.db, ctx.user, ScopeType.META_READ)
    create_new_user_meta(ctx.db)

    # Read metadata created by the other user.
    read_response = ctx.client.get(f"{META_ROOT}/bad_uuid")
    assert read_response.status_code == HTTPStatus.BAD_REQUEST
    assert "Object metadata ID is not a valid UUID hex string" in read_response.json()["detail"]

    read_response = ctx.client.get(f"{META_ROOT}/00000009-0008-0007-0006-000000000005")
    assert read_response.status_code == HTTPStatus.NOT_FOUND
    assert "Object metadata not found" in read_response.json()["detail"]
