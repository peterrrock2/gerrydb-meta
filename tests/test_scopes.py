from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import text

import gerrydb_meta.admin as admin_module
import gerrydb_meta.crud as crud
from gerrydb_meta.admin import GerryAdmin
from gerrydb_meta.enums import GroupPermissions
from gerrydb_meta.models import *
from gerrydb_meta.schemas import NamespaceCreate
from gerrydb_meta.scopes import ScopeManager


def clear_db(session):
    # delete in reverse‐FK order
    session.execute(text("DROP SCHEMA IF EXISTS gerrydb CASCADE"))
    session.execute(text("CREATE SCHEMA gerrydb"))
    session.commit()

    Base.metadata.create_all(bind=session.get_bind())


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, db_schema, db):
    """
    1) Patch admin_module.Session to use our test schema.
    2) Wipe out ALL users / groups / keys / scopes / meta.
    3) Bootstrap a fresh admin via `init:user` CLI.
    Runs automatically before every test that uses pytest.
    """
    monkeypatch.setenv("GERRYDB_RUN_TESTS", "1")
    monkeypatch.setattr(admin_module, "Session", db_schema)

    clear_db(db)

    admin_ctx = GerryAdmin(session=db)
    admin_ctx.initial_user_create(email="admin@example.com", name="Admin")

    yield


def test_scopes_public_user(db):
    """Test that a public user has the correct scopes."""
    admin_ctx = GerryAdmin(session=db)
    admin = admin_ctx.user_find_by_email("admin@example.com")

    pub_user = admin_ctx.user_create(
        email="public@example.com",
        name="Public",
        group_perm=GroupPermissions.PUBLIC,
        creator=admin,
    )

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000001"),
            notes="test",
            created_at=datetime.now(),
            created_by=admin.user_id,
        )
    )
    meta = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000001").one()
    db.add(
        Namespace(
            path="public_ns",
            description="a test ns",
            public=True,
            meta_id=meta.meta_id,
        )
    )
    db.add(
        Namespace(
            path="private_ns",
            description="a test ns",
            public=False,
            meta_id=meta.meta_id,
        )
    )
    db.commit()

    pub_ns = db.query(Namespace).filter_by(path="public_ns").one()
    priv_ns = db.query(Namespace).filter_by(path="private_ns").one()

    scopes = ScopeManager(pub_user)

    assert scopes.can_read_localities()
    assert not scopes.can_write_localities()
    assert not scopes.can_read_meta()
    assert not scopes.can_write_meta()
    assert not scopes.can_create_namespace()
    assert scopes.can_read_in_namespace(pub_ns)
    assert not scopes.can_write_in_namespace(pub_ns)
    assert scopes.can_write_derived_in_namespace(pub_ns)
    assert scopes.can_read_in_public_namespaces()
    assert not scopes.can_read_in_namespace(priv_ns)
    assert not scopes.can_write_in_namespace(priv_ns)
    assert not scopes.can_write_derived_in_namespace(priv_ns)


def test_scopes_contributor_user(db):
    """Test that a public user has the correct scopes."""
    admin_ctx = GerryAdmin(session=db)
    admin = admin_ctx.user_find_by_email("admin@example.com")

    contrib_user = admin_ctx.user_create(
        email="contributor@example.com",
        name="Contributor",
        group_perm=GroupPermissions.CONTRIBUTOR,
        creator=admin,
    )

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000001"),
            notes="test",
            created_at=datetime.now(),
            created_by=admin.user_id,
        )
    )
    meta = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000001").one()
    db.add(
        Namespace(
            path="public_ns",
            description="a test ns",
            public=True,
            meta_id=meta.meta_id,
        )
    )
    db.add(
        Namespace(
            path="private_ns",
            description="a test ns",
            public=False,
            meta_id=meta.meta_id,
        )
    )

    db.commit()

    pub_ns = db.query(Namespace).filter_by(path="public_ns").one()
    priv_ns = db.query(Namespace).filter_by(path="private_ns").one()

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000002"),
            notes="test",
            created_at=datetime.now(),
            created_by=contrib_user.user_id,
        )
    )
    meta2 = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000002").one()

    other_ns, _ = crud.namespace.create(
        db=db,
        obj_in=NamespaceCreate(
            path="other_ns",
            description="a test ns",
            public=False,
        ),
        obj_meta=meta2,
    )

    scopes = ScopeManager(contrib_user)

    assert scopes.can_read_localities()
    assert scopes.can_write_localities()
    assert not scopes.can_read_meta()
    assert scopes.can_write_meta()
    assert scopes.can_create_namespace()
    assert scopes.can_read_in_namespace(pub_ns)
    assert not scopes.can_write_in_namespace(pub_ns)
    assert scopes.can_write_derived_in_namespace(pub_ns)
    assert scopes.can_read_in_public_namespaces()
    assert not scopes.can_read_in_namespace(priv_ns)
    assert not scopes.can_write_in_namespace(priv_ns)
    assert not scopes.can_write_derived_in_namespace(priv_ns)
    assert scopes.can_read_in_namespace(other_ns)
    assert scopes.can_write_in_namespace(other_ns)
    assert scopes.can_write_derived_in_namespace(other_ns)


def test_scopes_admin_user(db):
    """Test that a public user has the correct scopes."""
    admin_ctx = GerryAdmin(session=db)
    admin = admin_ctx.user_find_by_email("admin@example.com")

    top_all_scopes = db.query(UserScope).all()
    top_all_groups = db.query(UserGroup).all()
    top_all_group_scopes = db.query(UserGroupScope).all()

    contrib_user = admin_ctx.user_create(
        email="admin_2@example.com",
        name="Admin 2",
        group_perm=GroupPermissions.CONTRIBUTOR,
        creator=admin,
    )

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000001"),
            notes="test",
            created_at=datetime.now(),
            created_by=admin.user_id,
        )
    )
    meta = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000001").one()
    db.add(
        Namespace(
            path="public_ns",
            description="a test ns",
            public=True,
            meta_id=meta.meta_id,
        )
    )
    db.add(
        Namespace(
            path="private_ns",
            description="a test ns",
            public=False,
            meta_id=meta.meta_id,
        )
    )

    db.commit()

    pub_ns = db.query(Namespace).filter_by(path="public_ns").one()
    priv_ns = db.query(Namespace).filter_by(path="private_ns").one()

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000002"),
            notes="test",
            created_at=datetime.now(),
            created_by=contrib_user.user_id,
        )
    )
    meta2 = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000002").one()

    other_ns, _ = crud.namespace.create(
        db=db,
        obj_in=NamespaceCreate(
            path="other_ns",
            description="a test ns",
            public=False,
        ),
        obj_meta=meta2,
    )

    scopes = ScopeManager(contrib_user)

    assert scopes.can_read_localities()
    assert scopes.can_write_localities()
    assert not scopes.can_read_meta()
    assert scopes.can_write_meta()
    assert scopes.can_create_namespace()
    assert scopes.can_read_in_namespace(pub_ns)
    assert not scopes.can_write_in_namespace(pub_ns)
    assert scopes.can_write_derived_in_namespace(pub_ns)
    assert scopes.can_read_in_public_namespaces()
    assert not scopes.can_read_in_namespace(priv_ns)
    assert not scopes.can_write_in_namespace(priv_ns)
    assert not scopes.can_write_derived_in_namespace(priv_ns)
    assert scopes.can_read_in_namespace(other_ns)
    assert scopes.can_write_in_namespace(other_ns)
    assert scopes.can_write_derived_in_namespace(other_ns)

    # Now check that extra scopes were not added to the
    # user scope table

    assert all([a == b for a, b in zip(top_all_scopes, db.query(UserScope).all())])
    assert all([a == b for a, b in zip(top_all_groups, db.query(UserGroup).all())])
    assert all([a == b for a, b in zip(top_all_group_scopes, db.query(UserGroupScope).all())])
