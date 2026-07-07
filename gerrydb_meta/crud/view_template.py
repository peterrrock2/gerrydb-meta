"""CRUD operations and transformations for view templates."""

import uuid
from datetime import datetime, timezone
from typing import Tuple, Union

from sqlalchemy import exc, select
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError


class CRViewTemplate(NamespacedCRBase[models.ViewTemplate, schemas.ViewTemplateCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.ViewTemplateCreate,
        resolved_members: list[Union[models.ColumnRef, models.ColumnSet]],
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
    ) -> Tuple[models.ViewTemplateVersion, uuid.UUID]:
        """Creates a new view template."""
        if not all(
            isinstance(member, models.ColumnRef) or isinstance(member, models.ColumnSet)
            for member in resolved_members
        ):
            raise CreateValueError("View templates may only contain columns and column sets.")

        with db.begin(nested=True):
            canonical_path = normalize_path(obj_in.path)
            view_template = models.ViewTemplate(
                path=canonical_path,
                description=obj_in.description,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(view_template)

            try:
                db.flush()
            except exc.SQLAlchemyError:
                log.exception(
                    "Failed to create view template '%s'.",
                    canonical_path,
                )
                raise CreateValueError(
                    f"Failed to create view template '{canonical_path}'. "
                    "(The path may already exist in the namespace.)"
                )
            db.refresh(view_template)

            template_version = models.ViewTemplateVersion(
                template_id=view_template.template_id,
                meta_id=obj_meta.meta_id,
                valid_from=datetime.now(timezone.utc),
            )
            db.add(template_version)
            db.flush()

            # Check for conflicting canonical refs.
            found_columns_paths = set()
            for idx, member in enumerate(resolved_members):
                if member.namespace_id != namespace.namespace_id and not member.namespace.public:
                    raise CreateValueError(
                        "Cannot create cross-namespace reference to an object in "
                        "a private namespace."
                    )

                if isinstance(member, models.ColumnRef):
                    # Now get the canonical path of the column.
                    canon_paths = set(
                        item[0]
                        for item in db.query(models.ColumnRef.path)
                        .filter(models.ColumnRef.col_id == member.col_id)
                        .all()
                    )
                    if any(canon_paths.intersection(found_columns_paths)):
                        raise CreateValueError(
                            "Error creating view template the following column "
                            "was referenced elsewhere either in "
                            f"the column list or in the column set: {member.path}"
                        )
                    found_columns_paths.update(canon_paths)
                    # col_id is pinned at creation: data resolution must not
                    # follow the ref later, or repointing it (materialization)
                    # would retroactively change this version's views.
                    db.add(
                        models.ViewTemplateColumnMember(
                            template_version_id=template_version.template_version_id,
                            ref_id=member.ref_id,
                            order=idx,
                            col_id=member.col_id,
                            direct=True,
                        )
                    )
                else:
                    set_members = (
                        db.query(models.ColumnSetMember.ref_id, models.ColumnRef.col_id)
                        .join(
                            models.ColumnRef,
                            models.ColumnRef.ref_id == models.ColumnSetMember.ref_id,
                        )
                        .filter(
                            models.ColumnSetMember.set_id == member.set_id,
                        )
                        .all()
                    )
                    col_ids = [row.col_id for row in set_members]

                    canon_paths = set(
                        item[0]
                        for item in db.query(models.ColumnRef.path)
                        .filter(models.ColumnRef.col_id.in_(col_ids))
                        .all()
                    )

                    if any(canon_paths.intersection(found_columns_paths)):
                        raise CreateValueError(
                            f"Cannot create view template. Found column "
                            f"'{tuple(canon_paths.intersection(found_columns_paths))}' in "
                            f"column set '{member.path}' that was previously added or appears in "
                            "another column set."
                        )

                    found_columns_paths.update(canon_paths)
                    db.add(
                        models.ViewTemplateColumnSetMember(
                            template_version_id=template_version.template_version_id,
                            set_id=member.set_id,
                            order=idx,
                        )
                    )
                    # Pin each set member's current column too (direct=False:
                    # hidden from the serialized member list, read by data
                    # resolution). Column sets themselves stay unpinned, so a
                    # version created later re-resolves the set fresh.
                    for row in set_members:
                        db.add(
                            models.ViewTemplateColumnMember(
                                template_version_id=template_version.template_version_id,
                                ref_id=row.ref_id,
                                order=idx,
                                col_id=row.col_id,
                                direct=False,
                            )
                        )

            etag = self._update_etag(db, namespace)

        db.refresh(template_version)
        return template_version, etag

    # TODO: patch()

    def get(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.ViewTemplateVersion | None:
        """Retrieves a view template by reference path.

        Args:
            path: Path to view template (namespace excluded).
            namespace: view template's namespace.
        """
        template = (
            db.query(models.ViewTemplate.template_id)
            .filter(
                models.ViewTemplate.namespace_id == namespace.namespace_id,
                models.ViewTemplate.path == normalize_path(path),
            )
            .first()
        )
        if template is None:
            return None

        return (
            db.query(models.ViewTemplateVersion)
            .filter(
                models.ViewTemplateVersion.template_id == template.template_id,
                models.ViewTemplateVersion.valid_to.is_(None),
            )
            .first()
        )

    def all_in_namespace(
        self,
        db: Session,
        *,
        namespace: models.Namespace,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[models.ViewTemplateVersion]:
        query = (
            db.query(models.ViewTemplateVersion)
            .filter(
                models.ViewTemplateVersion.template_id.in_(
                    select(models.ViewTemplate.template_id).filter(
                        self.model.namespace_id == namespace.namespace_id
                    )
                ),
                models.ViewTemplateVersion.valid_to.is_(None),
            )
        )
        if limit is not None or offset:
            query = query.order_by(models.ViewTemplateVersion.template_version_id).offset(offset)
            if limit is not None:
                query = query.limit(limit)
        return query.all()


view_template = CRViewTemplate(models.ViewTemplate)
