"""Utilities for granting API permissions to test users."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from gerrydb_meta import enums, models


def grant_scope(
    db: Session,
    user_or_meta: models.User | models.ObjectMeta,
    scope: enums.ScopeType,
    *,
    namespace_group: enums.NamespaceGroup | None = None,
) -> None:
    """Grants a scope to a test user (no-op if already held)."""
    if isinstance(user_or_meta, models.ObjectMeta):
        user = user_or_meta.user
        meta = user_or_meta
    else:
        user = user_or_meta
        meta = models.ObjectMeta(
            created_by=user.user_id,
            notes="Used for authorization configuration only.",
        )
        db.add(meta)
        db.flush()

    db.execute(
        pg_insert(models.UserScope)
        .values(
            user_id=user.user_id,
            scope=scope,
            namespace_group=namespace_group,
            namespace_id=None,
            meta_id=meta.meta_id,
        )
        .on_conflict_do_nothing(constraint="uq_user_scope_grant")
    )
    db.flush()
    db.refresh(user)


def grant_namespaced_scope(
    db: Session,
    user_or_meta: models.User | models.ObjectMeta,
    namespace: models.Namespace,
    scope: enums.ScopeType,
) -> None:
    """Grants a namespaced scope to a test user (no-op if already held)."""
    if isinstance(user_or_meta, models.ObjectMeta):
        user = user_or_meta.user
        meta = user_or_meta
    else:
        user = user_or_meta
        meta = models.ObjectMeta(
            created_by=user.user_id,
            notes="Used for authorization configuration only.",
        )
        db.add(meta)
        db.flush()

    db.execute(
        pg_insert(models.UserScope)
        .values(
            user_id=user.user_id,
            scope=scope,
            namespace_group=None,
            namespace_id=namespace.namespace_id,
            meta_id=meta.meta_id,
        )
        .on_conflict_do_nothing(constraint="uq_user_scope_grant")
    )
    db.flush()
    db.refresh(user)


def revoke_scope_type(
    db: Session,
    user_or_meta: models.User | models.ObjectMeta,
    scope: enums.ScopeType,
) -> None:
    """Revokes all scopes of type `scope` for a test user."""
    user = user_or_meta.user if isinstance(user_or_meta, models.ObjectMeta) else user_or_meta
    db.query(models.UserScope).filter(
        models.UserScope.scope == scope, models.UserScope.user_id == user.user_id
    ).delete()
    db.flush()
    db.refresh(user)
