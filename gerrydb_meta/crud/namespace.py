"""CRUD operations and transformations for namespace metadata."""

import uuid
from typing import Tuple

from sqlalchemy import exc
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

import gerrydb_meta.admin as admin_module
from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import CRBase
from gerrydb_meta.enums import ScopeType
from gerrydb_meta.exceptions import CreateValueError
from gerrydb_meta.scopes import ScopeManager


class CRNamespace(CRBase[models.Namespace, schemas.NamespaceCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.NamespaceCreate,
        obj_meta: models.ObjectMeta,
    ) -> Tuple[models.Namespace, uuid.UUID]:
        canonical_path = obj_in.path.lower()

        # Check if there is a limit on the creation yet
        namespace_limit = (
            db.query(models.NamespaceLimit)
            .filter(models.NamespaceLimit.user_id == obj_meta.created_by)
            .first()
        )
        namespace_creator = (
            db.query(models.User).filter(models.User.user_id == obj_meta.created_by).first()
        )

        if namespace_limit is None:
            namespace_limit = models.NamespaceLimit(
                user_id=obj_meta.created_by,
                max_ns_creation=(None if admin_module.check_admin(db, namespace_creator) else 10),
            )

            db.add(namespace_limit)
            db.flush()
            db.refresh(namespace_limit)

        if (
            namespace_limit.max_ns_creation is not None
            and namespace_limit.curr_creation_count + 1 > namespace_limit.max_ns_creation
        ):
            raise CreateValueError(
                f"{namespace_creator} has reached the maximum number of "
                f"namespaces ({namespace_limit.max_ns_creation}) that they can create."
            )

        namespace = models.Namespace(
            path=canonical_path,
            description=obj_in.description,
            public=obj_in.public,
            meta_id=obj_meta.meta_id,
        )
        db.add(namespace)
        namespace_limit.curr_creation_count += 1
        db.add(namespace_limit)

        try:
            db.flush()
        except exc.SQLAlchemyError:
            log.exception("Failed to create namespace '%s'.", canonical_path)
            raise CreateValueError(
                f"Failed to create namespace '{canonical_path}'. (The namespace may already exist.)"
            )

        etag = self._update_etag(db)
        db.flush()

        # Now grant the appropriate scopes to the user.
        user = db.query(models.User).filter(models.User.user_id == obj_meta.created_by).one()

        if not ScopeManager(user=user).can_read_in_namespace(namespace):
            admin_module.grant_scope(
                db=db,
                user=user,
                scopes=[
                    ScopeType.NAMESPACE_READ,
                    ScopeType.NAMESPACE_WRITE,
                    ScopeType.NAMESPACE_WRITE_DERIVED,
                ],
                namespace_id=namespace.namespace_id,
                meta=obj_meta,
            )
        return namespace, etag

    def get(self, db: Session, path: str) -> models.Namespace:
        return db.query(self.model).filter(self.model.path == path.lower()).first()


namespace = CRNamespace(models.Namespace)
