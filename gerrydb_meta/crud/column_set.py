"""CRUD operations and transformations for column sets."""

import uuid
from typing import Tuple

from sqlalchemy import exc
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.crud.column import column as crud_column
from gerrydb_meta.exceptions import CreateValueError


class CRColumnSet(NamespacedCRBase[models.ColumnSet, schemas.ColumnSetCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.ColumnSetCreate,
        namespace: models.Namespace,
        obj_meta: models.ObjectMeta,
    ) -> Tuple[models.ColumnSet, uuid.UUID]:
        """Creates a new column set."""
        with db.begin(nested=True):
            canonical_path = normalize_path(obj_in.path)
            column_set = models.ColumnSet(
                path=canonical_path,
                description=obj_in.description,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(column_set)

            try:
                db.flush()
            except exc.SQLAlchemyError:
                log.exception(
                    "Failed to create column set '%s'.",
                    canonical_path,
                )
                raise CreateValueError(
                    f"Failed to create column set '{canonical_path}'. "
                    "(The path may already exist in the namespace.)"
                )
            db.refresh(column_set)

            path_list = list(obj_in.columns)
            ref_by_path = {
                ref.path: ref
                for ref in crud_column.get_ref_bulk(
                    db,
                    namespaced_paths=[(namespace.path, p) for p in path_list],
                )
            }
            refs = []
            for column_path in path_list:
                ref_obj = ref_by_path.get(normalize_path(column_path))
                if ref_obj is None:
                    raise CreateValueError(f"Failed to resolve column '{column_path}'.")
                refs.append(ref_obj)

            ref_ids = [ref_obj.column.canonical_ref_id for ref_obj in refs]
            if len(ref_ids) > len(set(ref_ids)):
                ref_to_path_dict = {}
                for ref_obj in refs:
                    if ref_obj.column.canonical_ref_id not in ref_to_path_dict:
                        ref_to_path_dict[ref_obj.column.canonical_ref_id] = []
                    ref_to_path_dict[ref_obj.column.canonical_ref_id].append(ref_obj.path)

                raise CreateValueError(
                    "Columns in a column set must be unique. Found "
                    "duplicate column references: "
                    f"{[tuple(paths) for paths in ref_to_path_dict.values() if len(paths) > 1]}"
                    f"{path_list}"
                )

            for idx, ref_obj in enumerate(refs):
                db.add(
                    models.ColumnSetMember(
                        set_id=column_set.set_id,
                        ref_id=ref_obj.ref_id,
                        order=idx,
                    )
                )

            etag = self._update_etag(db, namespace)

        db.refresh(column_set)
        return column_set, etag

    def get(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.ColumnSet | None:
        """Retrieves a column set by reference path.

        Args:
            path: Path to column set (namespace excluded).
            namespace: Column set's namespace.
        """
        return (
            db.query(models.ColumnSet)
            .filter(
                models.ColumnSet.namespace_id == namespace.namespace_id,
                models.ColumnSet.path == normalize_path(path),
            )
            .first()
        )


column_set = CRColumnSet(models.ColumnSet)
