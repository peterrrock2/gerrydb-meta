"""CRUD operations and transformations for location metadata."""

import logging
import uuid
from typing import Collection, Tuple

from sqlalchemy import bindparam, exc, insert, update
from sqlalchemy.orm import Session

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import CRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError

log = logging.getLogger()


class CRLocality(CRBase[models.Locality, schemas.LocalityCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.LocalityCreate,
        obj_meta: models.ObjectMeta,
    ) -> Tuple[models.Locality, uuid.UUID]:
        locality_list, locality_etag = self.create_bulk(
            db=db,
            objs_in=[obj_in],
            obj_meta=obj_meta,
        )
        return locality_list[0], locality_etag

    def create_bulk(
        self,
        db: Session,
        *,
        objs_in: list[schemas.LocalityCreate],
        obj_meta: models.ObjectMeta,
    ) -> Tuple[list[models.Locality], uuid.UUID]:
        """Creates a new location with a canonical reference."""
        parent_paths = {
            normalize_path(obj_in.parent_path)
            for obj_in in objs_in
            if obj_in.parent_path is not None
        }
        parent_ref_loc_ids = dict(
            db.query(models.LocalityRef.path, models.LocalityRef.loc_id)
            .filter(
                models.LocalityRef.path.in_(parent_paths),
            )
            .all()
        )

        if len(parent_ref_loc_ids) < len(parent_paths):
            missing = ", ".join(parent_paths - set(parent_ref_loc_ids))
            raise CreateValueError(f"Reference to unknown parent locations {missing}.")
        if None in parent_ref_loc_ids.values():
            raise CreateValueError("Dangling locality reference found.")

        with db.begin(nested=True):
            try:
                canonical_refs = list(
                    db.scalars(
                        insert(models.LocalityRef).returning(models.LocalityRef),
                        [
                            {
                                "path": normalize_path(obj_in.canonical_path),
                                "meta_id": obj_meta.meta_id,
                            }
                            for obj_in in objs_in
                        ],
                    )
                )
            except exc.SQLAlchemyError:
                # TODO: Make this more specific--the primary goal is to capture the case
                # where the reference already exists.
                log.exception("Failed to create references to new location.")
                raise CreateValueError(
                    "Failed to create canonical path to new location(s). "
                    "(The path(s) may already exist.)"
                )

            canonical_ref_ids = {ref.path: ref.ref_id for ref in canonical_refs}
            canonical_ref_paths = {ref.ref_id: ref.path for ref in canonical_refs}

            # Create the locations.
            try:
                locs = list(
                    db.scalars(
                        insert(models.Locality).returning(models.Locality),
                        [
                            {
                                "canonical_ref_id": canonical_ref_ids[
                                    normalize_path(obj_in.canonical_path)
                                ],
                                "parent_id": (
                                    None
                                    if obj_in.parent_path is None
                                    else parent_ref_loc_ids[normalize_path(obj_in.parent_path)]
                                ),
                                "meta_id": obj_meta.meta_id,
                                "name": obj_in.name,
                                "default_proj": obj_in.default_proj,
                            }
                            for obj_in in objs_in
                        ],
                    )
                )
            except exc.SQLAlchemyError:  # pragma: no cover
                log.exception("Failed to create new location(s).")
                raise CreateValueError("Failed to create new location(s).")

            loc_ids_by_path = {
                canonical_ref_paths[loc.canonical_ref_id]: loc.loc_id for loc in locs
            }

            # Backport location references.
            # bulk updates: see https://stackoverflow.com/a/25720751
            db.connection().execute(
                update(models.LocalityRef)
                .where(models.LocalityRef.ref_id == bindparam("_ref_id"))
                .values({"loc_id": bindparam("loc_id")}),
                [{"loc_id": loc.loc_id, "_ref_id": loc.canonical_ref_id} for loc in locs],
            )

            # Add aliases in bulk.
            aliases = []
            for obj_in in objs_in:
                if obj_in.aliases:
                    for alias in obj_in.aliases:
                        aliases.append(
                            {
                                "path": normalize_path(alias),
                                "meta_id": obj_meta.meta_id,
                                "loc_id": loc_ids_by_path[normalize_path(obj_in.canonical_path)],
                            }
                        )

            if aliases:
                try:
                    db.execute(insert(models.LocalityRef), aliases)
                except exc.SQLAlchemyError:  # pragma: no cover
                    log.exception("Failed to create aliases for new location(s).")
                    raise CreateValueError("Failed to create aliases for new location(s).")

            etag = self._update_etag(db)

        # Refresh localities with new aliases, etc. before returning.
        refreshed_locs = (
            db.query(models.Locality)
            .filter(models.Locality.loc_id.in_(loc_ids_by_path.values()))
            .all()
        )
        return refreshed_locs, etag

    def get_by_ref(self, db: Session, *, path: str) -> models.Locality | None:
        return self.get(db=db, path=path)

    def get(self, db: Session, *, path: str) -> models.Locality | None:
        """Retrieves a location by reference path."""
        ref = (
            db.query(models.LocalityRef)
            .filter(models.LocalityRef.path == normalize_path(path))
            .first()
        )
        return None if ref is None else ref.loc

    def patch(
        self,
        db: Session,
        *,
        obj: models.Locality,
        obj_meta: models.ObjectMeta,
        patch: schemas.LocalityPatch,
    ) -> Tuple[models.Locality, uuid.UUID]:
        """Patches a location (adds new aliases)."""
        new_aliases = set(normalize_path(path) for path in patch.aliases) - set(
            ref.path for ref in obj.refs
        )
        if not new_aliases:
            return obj

        etag = self._update_etag(db)
        db.flush()
        self._add_aliases(db=db, alias_paths=new_aliases, loc=obj, obj_meta=obj_meta)
        db.refresh(obj)
        return obj, etag

    def _add_aliases(
        self,
        *,
        db: Session,
        alias_paths: Collection[str],
        loc: models.Locality,
        obj_meta: models.ObjectMeta,
    ) -> None:
        """Adds aliases to a location."""
        for alias_path in alias_paths:
            alias_ref = models.LocalityRef(
                path=normalize_path(alias_path),
                loc_id=loc.loc_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(alias_ref)

            try:
                db.flush()
            except exc.SQLAlchemyError:
                # TODO: Make this more specific--the primary goal is to capture the case
                # where the reference already exists.
                log.error(f"Failed to create aliases for new location.")
                raise CreateValueError(
                    "Failed to create aliases for new location. "
                    "(One or more aliases may already exist.)"
                )


locality = CRLocality(models.Locality)
