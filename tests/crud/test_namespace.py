import pytest

import gerrydb_meta.models as models
from gerrydb_meta import crud, schemas
from gerrydb_meta.admin import grant_scope
from gerrydb_meta.enums import NamespaceGroup, ScopeType
from gerrydb_meta.exceptions import CreateValueError


def test_crud_namespace_create(db_with_meta):
    db, meta = db_with_meta
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )
    assert ns.path == "atlantis"
    assert ns.description == "A legendary city"
    assert ns.public is True


def test_crud_namespace_create_many(db_with_meta):
    db, meta = db_with_meta

    for i in range(10):
        _ = crud.namespace.create(
            db=db,
            obj_in=schemas.NamespaceCreate(
                path=f"atlantis_{i}",
                description="A legendary city",
                public=True,
            ),
            obj_meta=meta,
        )

    with pytest.raises(
        CreateValueError,
        match=(
            r"User\(email=test@example.com, name=Test User\) has reached the "
            r"maximum number of namespaces \(10\) that they can create."
        ),
    ):
        _ = crud.namespace.create(
            db=db,
            obj_in=schemas.NamespaceCreate(
                path=f"atlantis_bad_create",
                description="A legendary city",
                public=True,
            ),
            obj_meta=meta,
        )


def test_crud_namespace_create_many_admin(db_with_meta):
    db, meta = db_with_meta

    user = db.query(models.User).filter(models.User.user_id == meta.created_by).first()

    grant_scope(
        db=db,
        user=user,
        scopes=ScopeType.ALL,
        meta=meta,
        namespace_group=NamespaceGroup.ALL,
    )
    db.flush()

    for i in range(10):
        _ = crud.namespace.create(
            db=db,
            obj_in=schemas.NamespaceCreate(
                path=f"atlantis_{i}",
                description="A legendary city",
                public=True,
            ),
            obj_meta=meta,
        )
    # No limit for admin
    for i in range(11):
        _ = crud.namespace.create(
            db=db,
            obj_in=schemas.NamespaceCreate(
                path=f"admin_atlantis_{i}",
                description="A legendary city",
                public=True,
            ),
            obj_meta=meta,
        )


def test_crud_namespace_get(db_with_meta):
    db, meta = db_with_meta
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )
    assert crud.namespace.get(db=db, path="atlantis").namespace_id == ns.namespace_id
