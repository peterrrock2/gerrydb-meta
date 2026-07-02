"""Fixtures for REST API tests."""

import random
from dataclasses import dataclass
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.admin import GerryAdmin
from gerrydb_meta.api.deps import get_db
from gerrydb_meta.enums import GroupPermissions, NamespaceGroup, ScopeType
from gerrydb_meta.main import app

from .scopes import grant_namespaced_scope, grant_scope


# Extend this for all new tests rather than returning tuples from fixtures.
@dataclass(frozen=True)
class TestContext:
    """Database context for an API test."""

    db: Session
    client: TestClient
    meta: models.ObjectMeta | None = None
    admin_meta: models.ObjectMeta | None = None
    user: models.User | None = None
    admin_user: models.User | None = None
    namespace: models.Namespace | None = None


@pytest.fixture
def client_no_auth(db):
    """FastAPI test client with no authentication."""

    def get_test_db() -> Generator:
        yield db

    app.dependency_overrides[get_db] = get_test_db
    yield TestClient(app)


@pytest.fixture
def ctx_no_scopes_factory(db):
    """Factory for database session + test client with API key auth and metadata context."""

    def get_test_db() -> Generator:
        yield db

    def ctx_factory() -> TestContext:
        # TODO: replace with `crud` calls.
        admin = GerryAdmin(db)
        try:
            creator = admin.initial_user_create("admin@example.com", "admin")
        except Exception:
            creator = admin.user_find_by_email("admin@example.com")

        user_idx = random.randint(0, 1_000_000_000)
        user = admin.user_create(
            name="Test User",
            email=f"test{user_idx}@example.com",
            group_perm=GroupPermissions.PUBLIC,
            creator=creator,
        )
        user_idx += 1
        api_key = admin.key_create(user)
        db.flush()

        meta = models.ObjectMeta(notes="metameta", created_by=user.user_id)
        admin_meta = models.ObjectMeta(notes="adminmeta", created_by=creator.user_id)
        db.add(meta)
        db.add(admin_meta)
        db.flush()
        db.refresh(user)
        db.refresh(meta)
        db.refresh(admin_meta)
        db.refresh(creator)

        app.dependency_overrides[get_db] = get_test_db
        headers = {"X-API-Key": api_key, "X-GerryDB-Meta-Id": str(meta.uuid)}
        client = TestClient(app, headers=headers)
        return TestContext(
            db=db,
            client=client,
            user=user,
            admin_user=creator,
            meta=meta,
            admin_meta=admin_meta,
        )

    return ctx_factory


@pytest.fixture
def ctx_no_scopes(ctx_no_scopes_factory):
    """Database session + test client with API key auth and metadata context."""
    yield ctx_no_scopes_factory()


@pytest.fixture
def ctx_superuser(ctx_no_scopes_factory):
    """FastAPI test client with API key authentication and maximum privileges."""
    ctx = ctx_no_scopes_factory()
    grant_scope(ctx.db, ctx.user, ScopeType.ALL, namespace_group=NamespaceGroup.ALL)
    yield ctx


@pytest.fixture
def client_with_meta_locality(db_and_client_with_meta_locality):
    """An API client with `LOCALITY_READ` and `LOCALITY_WRITE` scopes (+ session and metadata)."""
    _, client, meta = db_and_client_with_meta_locality
    yield client, meta


@pytest.fixture
def ctx_public_namespace_read_only(request, ctx_no_scopes_factory):
    """Context with an API client with public NAMESPACE_READ scope."""
    base_ctx = ctx_no_scopes_factory()
    test_name = request.node.name.replace("[", "__").replace("]", "")
    namespace, _ = crud.namespace.create(
        db=base_ctx.db,
        obj_in=schemas.NamespaceCreate(
            path=test_name,
            description=f"Namespace for test {request.node.name}",
            public=True,
        ),
        obj_meta=base_ctx.meta,
    )

    yield TestContext(
        db=base_ctx.db,
        client=base_ctx.client,
        meta=base_ctx.meta,
        admin_meta=base_ctx.admin_meta,
        user=base_ctx.user,
        admin_user=base_ctx.admin_user,
        namespace=namespace,
    )


@pytest.fixture
def ctx_public_namespace_read_write(ctx_public_namespace_read_only):
    """Context with an API client with public NAMESPACE_READ scope and
    namespaced NAMESPACE_WRITE scope."""
    ctx = ctx_public_namespace_read_only
    grant_namespaced_scope(ctx.db, ctx.meta, ctx.namespace, ScopeType.NAMESPACE_WRITE)
    grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_WRITE)
    yield ctx


@pytest.fixture
def ctx_private_namespace_read_only(request, ctx_no_scopes_factory):
    """Context with an API client with NAMESPACE_READ scope in a private namespace."""
    base_ctx = ctx_no_scopes_factory()
    test_name = request.node.name.replace("[", "__").replace("]", "")
    namespace, _ = crud.namespace.create(
        db=base_ctx.db,
        obj_in=schemas.NamespaceCreate(
            path=f"{test_name}__private",
            description=f"Private namespace for test {request.node.name}",
            public=False,
        ),
        obj_meta=base_ctx.meta,
    )
    yield TestContext(
        db=base_ctx.db,
        client=base_ctx.client,
        meta=base_ctx.meta,
        admin_meta=base_ctx.admin_meta,
        user=base_ctx.user,
        admin_user=base_ctx.admin_user,
        namespace=namespace,
    )


@pytest.fixture
def ctx_private_namespace_read_write(ctx_private_namespace_read_only):
    """Context with an API client with NAMESPACE_READ scope in a private namespace."""
    ctx = ctx_private_namespace_read_only
    grant_scope(ctx.db, ctx.meta, ScopeType.LOCALITY_WRITE)
    yield ctx


@pytest.fixture
def pop_column_meta():
    """Example metadata for a population column."""
    return {
        "canonical_path": "total_pop",
        "description": "2020 Census total population",
        "source_url": "https://www.census.gov/",
        "kind": "count",
        "type": "int",
        "aliases": ["totpop", "p001001", "p0001001"],
    }


@pytest.fixture
def vap_column_meta():
    """Example metadata for a voting-age population column."""
    return {
        "canonical_path": "total_vap",
        "description": "2020 Census total voting-age population (VAP)",
        "source_url": "https://www.census.gov/",
        "kind": "count",
        "type": "float",
        "aliases": ["totvap", "p003001", "p0003001"],
    }
