"""
The main purpose of this files is to check all of the things that
do not get checked in the other tests. Namely, the various error codes that
can be returned by the API.
"""

import hashlib
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from gerrydb_meta.api.deps import (
    get_geo_import,
    get_obj_meta,
    get_scopes,
    get_user,
)
from gerrydb_meta.models import ApiKey, GeoImport, Namespace, ObjectMeta, User


def test_get_user_errors(ctx_no_scopes):
    db = ctx_no_scopes.db
    with pytest.raises(HTTPException, match="API key required"):
        get_user(db=db, x_api_key=None)

    with pytest.raises(HTTPException, match="Invalid API key format"):
        get_user(db=db, x_api_key="bad_key")

    one_key = "1" * 64
    with pytest.raises(HTTPException, match="Unknown API key"):
        get_user(db=db, x_api_key=one_key)

    user = db.query(User).first()
    new_key_hash = hashlib.sha512(one_key.encode("utf-8")).digest()

    api_key_model = ApiKey(
        key_hash=new_key_hash,
        user_id=user.user_id,
        created_at=datetime.now(),
        active=False,
    )
    db.add(api_key_model)
    db.flush()

    with pytest.raises(HTTPException, match="API key is not active"):
        get_user(db=db, x_api_key=one_key)


def test_get_obj_meta(ctx_no_scopes):
    db = ctx_no_scopes.db
    admin = ctx_no_scopes.admin_user

    with pytest.raises(HTTPException, match="Object metadata ID required"):
        get_obj_meta(db=db, user=admin, x_gerrydb_meta_id=None)

    with pytest.raises(HTTPException, match="Object metadata ID is not a valid UUID hex string."):
        get_obj_meta(db=db, user=admin, x_gerrydb_meta_id="bad_uuid")

    with pytest.raises(HTTPException, match="Metadata object could not be found in the database."):
        get_obj_meta(db=db, user=admin, x_gerrydb_meta_id="1" * 32)

    user = ctx_no_scopes.user
    new_uuid = uuid.uuid4()
    db.add(
        ObjectMeta(
            uuid=new_uuid,
            notes="test",
            created_at=datetime.now(),
            created_by=user.user_id,
        )
    )
    new_meta = db.query(ObjectMeta).filter_by(uuid=str(new_uuid)).one()
    with pytest.raises(
        HTTPException,
        match="Cannot use metadata object created by another user.",
    ):
        get_obj_meta(db=db, user=admin, x_gerrydb_meta_id=str(new_meta.uuid))


def test_get_geo_import(ctx_no_scopes):
    db = ctx_no_scopes.db
    admin = ctx_no_scopes.admin_user
    admin_scopes = get_scopes(admin)

    with pytest.raises(HTTPException, match="GeoImport ID required"):
        get_geo_import(db=db, user=admin, scopes=admin_scopes, x_gerrydb_geo_import_id=None)

    with pytest.raises(HTTPException, match="GeoImport ID is not a valid UUID hex string."):
        get_geo_import(db=db, user=admin, scopes=admin_scopes, x_gerrydb_geo_import_id="bad_uuid")

    with pytest.raises(HTTPException, match="Unknown GeoImport ID"):
        get_geo_import(db=db, user=admin, scopes=admin_scopes, x_gerrydb_geo_import_id="1" * 32)

    user = ctx_no_scopes.user
    new_uuid = uuid.uuid4()
    db.add(
        ObjectMeta(
            uuid=new_uuid,
            notes="test",
            created_at=datetime.now(),
            created_by=user.user_id,
        )
    )
    meta = db.query(ObjectMeta).filter_by(uuid=str(new_uuid)).one()

    db.add(
        Namespace(
            path="test_ns",
            description="a test ns",
            public=True,
            meta_id=meta.meta_id,
        )
    )
    ns = db.query(Namespace).first()
    db.add(
        GeoImport(
            uuid=new_uuid,
            namespace_id=ns.namespace_id,
            meta_id=meta.meta_id,
            created_at=datetime.now(),
            created_by=user.user_id,
        )
    )

    with pytest.raises(
        HTTPException,
        match="Cannot use GeoImport created by another user.",
    ):
        get_geo_import(
            db=db,
            user=admin,
            scopes=admin_scopes,
            x_gerrydb_geo_import_id=str(new_uuid),
        )
