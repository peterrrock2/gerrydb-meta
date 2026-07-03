"""Database and authorization dependencies for GerryDB endpoints."""

import os
import re
from hashlib import sha512
from http import HTTPStatus
from typing import Generator
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models
from gerrydb_meta.db import db_url, ogr2ogr_db_config
from gerrydb_meta.enums import ScopeType
from gerrydb_meta.scopes import ScopeManager

GERRYDB_SQL_ECHO = bool(os.environ.get("GERRYDB_SQL_ECHO", False))

API_KEY_PATTERN = re.compile(r"[0-9a-z]{64}")


_engine = None


def _get_engine():  # pragma: no cover
    """Lazily creates the per-process engine (one pool per gunicorn worker)."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            db_url,
            echo=GERRYDB_SQL_ECHO,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )
    return _engine


def get_db(request: Request) -> Generator:  # pragma: no cover
    """Yields a pooled per-request session.

    The COMMIT is issued by CommitBeforeSendMiddleware when the response's
    first bytes head out, NOT here: FastAPI runs this teardown after the
    response can reach the client, so a fast caller could reference an object
    (e.g. X-GerryDB-Meta-Id) before its transaction committed. The old
    time.sleep(0.1) in get_obj_meta papered over exactly that race.
    """
    db = Session(_get_engine())
    request.state.db = db
    try:
        yield db
    finally:
        # Uncommitted work (error paths) is rolled back on pool return.
        db.close()


def get_ogr2ogr_db_config() -> str:  # pragma: no cover
    return ogr2ogr_db_config


def get_user(
    db: Session = Depends(get_db), x_api_key: str | None = Header(default=None)
) -> models.User:
    """Retrieves the user associated with an API key."""
    if x_api_key is None:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="API key required.")

    key_raw = x_api_key.lower()
    if re.match(API_KEY_PATTERN, key_raw) is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Invalid API key format.")

    key_hash = sha512(key_raw.encode("utf-8")).digest()
    api_key = crud.api_key.get(db=db, id=key_hash)
    if api_key is None:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Unknown API key.")
    if not api_key.active:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="API key is not active.")
    return api_key.user


def get_obj_meta(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_user),
    x_gerrydb_meta_id: str | None = Header(default=None),
) -> models.ObjectMeta:
    """Retrieves the object metadata referenced in a request header."""
    if x_gerrydb_meta_id is None:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Object metadata ID required."
        )

    try:
        meta_uuid = UUID(x_gerrydb_meta_id)
    except ValueError:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Object metadata ID is not a valid UUID hex string.",
        )
    log.debug("Retrieving ObjectMeta: %s", meta_uuid)  # Debugging line
    obj_meta = crud.obj_meta.get(db=db, id=meta_uuid)
    if obj_meta is None:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Metadata object could not be found in the database.",
        )
    if obj_meta.created_by != user.user_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Cannot use metadata object created by another user.",
        )
    log.debug("Retrieved ObjectMeta for: %s", obj_meta.uuid)  # Debugging line
    return obj_meta


def get_scopes(
    user: models.User = Depends(get_user),
) -> ScopeManager:
    """Returns a user-level scope manager."""
    return ScopeManager(user=user)


def get_geo_import(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_user),
    scopes: ScopeManager = Depends(get_scopes),
    x_gerrydb_geo_import_id: str | None = Header(default=None),
) -> models.ObjectMeta:
    """Retrieves the geographic import metadata referenced in a request header."""
    if x_gerrydb_geo_import_id is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="GeoImport ID required.")

    try:
        geo_import_uuid = UUID(x_gerrydb_geo_import_id)
    except ValueError:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="GeoImport ID is not a valid UUID hex string.",
        )

    geo_import = crud.geo_import.get(db=db, uuid=geo_import_uuid)
    if geo_import is None or not scopes.can_read_in_namespace(geo_import.namespace):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Unknown GeoImport ID.",
        )

    if geo_import.created_by != user.user_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Cannot use GeoImport created by another user.",
        )
    return geo_import


def no_perms(msg: str) -> str:
    """Generates a permissions-related error string."""
    return f"You do not have sufficient permissions to {msg}."


def global_scope_check(scope: ScopeType, message: str):
    """Returns a dependency that raises 403 Forbidden if a scope requirement fails."""

    def dependency(scopes: ScopeManager = Depends(get_scopes)):
        if not scopes.has_global_scope(scope):
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=no_perms(message))

    return dependency


can_read_localities = global_scope_check(ScopeType.LOCALITY_READ, "read localities")
can_write_localities = global_scope_check(ScopeType.LOCALITY_WRITE, "write localities")
can_write_meta = global_scope_check(ScopeType.META_WRITE, "write metadata")
can_create_namespace = global_scope_check(ScopeType.NAMESPACE_CREATE, "create namespaces")
