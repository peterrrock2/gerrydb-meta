"""CRUD operations and transformations for geographic layers."""

import uuid
from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy import exc, func, insert, text, update
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError


class CRGeoLayer(NamespacedCRBase[models.GeoLayer, schemas.GeoLayerCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.GeoLayerCreate,
        namespace: models.Namespace,
        obj_meta: models.ObjectMeta,
    ) -> Tuple[models.GeoLayer, uuid.UUID]:
        """Creates a new geographic layer."""
        log.debug("TOP OF CREATE GEO LAYER")

        with db.begin(nested=True):
            # Create a path to the column.
            canonical_path = normalize_path(obj_in.path)
            log.debug("CANONICAL PATH: %s", canonical_path)
            geo_layer = models.GeoLayer(
                path=canonical_path,
                description=obj_in.description,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
                source_url=(str(obj_in.source_url) if obj_in.source_url is not None else None),
            )
            db.add(geo_layer)

            try:
                db.flush()
            except exc.SQLAlchemyError:
                log.exception(
                    "Failed to create geographic layer '%s'.",
                    canonical_path,
                )
                raise CreateValueError(
                    f"Failed to create geographic layer '{canonical_path}'."
                    "(The path may already exist in the namespace.)"
                )
            etag = self._update_etag(db, namespace)

        db.refresh(geo_layer)
        return geo_layer, etag

    def get(self, db: Session, *, path: str, namespace: models.Namespace) -> models.GeoLayer | None:
        """Retrieves a geographic layer by reference path.

        Args:
            path: Path to geographic layer (namespace excluded).
            namespace: Geographic layer's namespace.
        """
        return (
            db.query(models.GeoLayer)
            .filter(
                models.GeoLayer.namespace_id == namespace.namespace_id,
                models.GeoLayer.path == normalize_path(path),
            )
            .first()
        )

    def __members_match(self, db: Session, set_version_id: int, new_geo_ids: set[int]) -> bool:
        """SQL-side equality check between an existing set's members and `new_geo_ids`."""
        old_count = (
            db.query(func.count(models.GeoSetMember.geo_id))
            .filter(models.GeoSetMember.set_version_id == set_version_id)
            .scalar()
        )
        if old_count != len(new_geo_ids):
            return False

        # Counts match, so a one-way probe suffices: old minus new empty => equal.
        # An array bind handles block scale (~1M ids, ~10 MB); move to a COPY
        # temp table if sets grow an order of magnitude past that.
        stray = db.execute(
            text(
                "SELECT geo_id FROM gerrydb.geo_set_member "
                "WHERE set_version_id = :set_version_id "
                "EXCEPT SELECT unnest(CAST(:geo_ids AS integer[])) "
                "LIMIT 1"
            ),
            {"set_version_id": set_version_id, "geo_ids": list(new_geo_ids)},
        ).first()
        return stray is None

    def map_locality(
        self,
        db: Session,
        *,
        layer: models.GeoLayer,
        locality: models.Locality,
        geographies: list[models.Geography],
        obj_meta: models.ObjectMeta,
    ) -> None:
        """Maps a set of `geographies` to `layer` in `locality`."""
        now = datetime.now(timezone.utc)

        if len(set(geo.namespace_id for geo in geographies)) > 1:
            raise CreateValueError(
                "Cannot map geographies in multiple namespaces to a geographic layer."
            )

        new_geo_ids = set(geo.geo_id for geo in geographies)

        with db.begin(nested=True):
            # Compare against the current set for THIS (layer, locality) only; the
            # old query joined every member of every set version in the database.
            current_row = (
                db.query(models.GeoSetVersion.set_version_id)
                .filter(
                    models.GeoSetVersion.layer_id == layer.layer_id,
                    models.GeoSetVersion.loc_id == locality.loc_id,
                    models.GeoSetVersion.valid_to.is_(None),
                )
                .order_by(models.GeoSetVersion.set_version_id.desc())
                .first()
            )

            if current_row is not None and self.__members_match(
                db, current_row.set_version_id, new_geo_ids
            ):
                # No need to create a new set
                log.debug(
                    f"Attempted to create a new geo set for layer {layer.full_path}"
                    f" in the namespace {layer.namespace.path} at locality "
                    f" {locality.canonical_ref} but the new set is identical"
                    f" to the old set."
                )
                db.flush()
                return

            # Deprecate old version if present.
            db.execute(
                update(models.GeoSetVersion)
                .where(
                    models.GeoSetVersion.layer_id == layer.layer_id,
                    models.GeoSetVersion.loc_id == locality.loc_id,
                    models.GeoSetVersion.valid_to.is_(None),
                )
                .values(valid_to=now)
            )

            set_version = models.GeoSetVersion(
                layer_id=layer.layer_id,
                loc_id=locality.loc_id,
                meta_id=obj_meta.meta_id,
                valid_from=now,
            )
            db.add(set_version)
            db.flush()
            db.refresh(set_version)

            db.execute(
                insert(models.GeoSetMember),
                [
                    {
                        "set_version_id": set_version.set_version_id,
                        "geo_id": geo.geo_id,
                    }
                    for geo in geographies
                ],
            )

    def get_set_by_locality(
        self,
        db: Session,
        *,
        layer: models.GeoLayer,
        locality: models.Locality,
    ) -> models.GeoSetVersion | None:
        """Retrieves the latest `GeoSetVersion` associated with a locality."""
        return (
            db.query(models.GeoSetVersion)
            .filter(
                models.GeoSetVersion.valid_to.is_(None),
                models.GeoSetVersion.layer_id == layer.layer_id,
                models.GeoSetVersion.loc_id == locality.loc_id,
            )
            .first()
        )


geo_layer = CRGeoLayer(models.GeoLayer)
