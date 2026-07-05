"""CRUD operations and transformations for geographic imports."""

import binascii
import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Collection

import numpy as np
import shapely
from geoalchemy2.elements import WKBElement, WKTElement
from shapely.geometry import Polygon
from sqlalchemy import and_, exc, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import BulkCreateError, BulkPatchError

# Canonical coordinate grid, in degrees (~0.11 m; accuracy requirement is
# ~1/3 m). Geometries are snapped to this grid before hashing AND storage, so
# pull -> reproject -> upload round trips re-snap to identical bytes and dedup
# against stored bins. The client applies the same snap before serializing.
# PERMANENT: changing the grid invalidates every stored geometry hash.
GEO_GRID_SIZE = 1e-6


def _canonicalize_geos(objs_in):
    """Snaps every geography in `objs_in` to the canonical grid.

    Returns (new objs, max per-axis snap displacement in degrees). Snapping
    must happen before the dedup hash: snapping only inside the insert would
    store snapped bytes while the lookup hashed raw ones, so off-grid uploads
    would miss dedup forever.

    Census-published coordinates are integer microdegrees (TIGER/Line
    technical documentation sec. 3.3.6), so the expected displacement for
    census sources is ~0; up to half-grid is normal for derived products
    (clips, dissolves). A large systematic displacement flags a
    finer-than-grid source that deserves a deliberate precision decision
    instead of a silent truncation, which is why the maximum is logged
    per batch.
    """
    with_geo = [i for i, obj in enumerate(objs_in) if obj.geography is not None]
    if not with_geo:
        return list(objs_in), 0.0

    try:
        geoms = shapely.from_wkb([objs_in[i].geography for i in with_geo])
    except shapely.errors.ShapelyError as ex:
        log.exception("Failed to parse geometries for canonicalization.")
        raise BulkCreateError(
            "Failed to insert geometries. This is likely due to invalid Geometries; please"
            " ensure geometries can be encoded in WKB format."
        ) from ex
    coords = shapely.get_coordinates(geoms)
    max_disp = 0.0
    if coords.size:
        scaled = coords / GEO_GRID_SIZE
        max_disp = float(np.abs(scaled - np.round(scaled)).max()) * GEO_GRID_SIZE
    # Pointwise: on-grid (census-published) coordinates round-trip
    # byte-identically and vertex order is preserved; the default valid_output
    # mode rebuilds rings, breaking that identity. Empty geometries pass
    # through unchanged (pointwise reduction rewrites their bytes).
    empties = shapely.is_empty(geoms)
    canonical = shapely.to_wkb(shapely.set_precision(geoms, GEO_GRID_SIZE, mode="pointwise"))

    out = list(objs_in)
    for pos, i in enumerate(with_geo):
        if empties[pos]:
            continue
        out[i] = objs_in[i].model_copy(update={"geography": bytes(canonical[pos])})
    return out, max_disp


def _internal_point_elements(objs_in) -> dict[str, WKBElement | WKTElement]:
    """Maps each object's path to its internal point element (POINT EMPTY when
    none was provided)."""
    empty_point = WKTElement("POINT EMPTY", srid=4269)
    return {
        obj.path: (
            empty_point
            if obj.internal_point is None
            else WKBElement(obj.internal_point, srid=4269)
        )
        for obj in objs_in
    }


class CRGeography(NamespacedCRBase[models.Geography, None]):
    def __get_existing_geos(
        self,
        db: Session,
        obj_paths: list[str],
        namespace: models.Namespace,
    ) -> list[models.Geography]:
        return (
            db.query(models.Geography)
            .filter(
                models.Geography.path.in_(
                    normalize_path(path, case_sensitive_uid=True) for path in obj_paths
                ),
                models.Geography.namespace_id == namespace.namespace_id,
            )
            .all()
        )

    def __get_existing_paths(
        self,
        db: Session,
        obj_paths: list[str],
        namespace: models.Namespace,
    ) -> list[models.Geography]:
        return list(
            item[0]
            for item in db.query(models.Geography.path)
            .filter(
                models.Geography.path.in_(
                    normalize_path(path, case_sensitive_uid=True) for path in obj_paths
                ),
                models.Geography.namespace_id == namespace.namespace_id,
            )
            .all()
        )

    def __validate_create_geos(
        self,
        db: Session,
        obj_paths: list[str],
        namespace: models.Namespace,
    ) -> None:
        # Need to check for unique paths since otherwise the db will just
        # insert the first occurrence which could be confusing. (This error
        # should almost never be raised in practice.)
        paths = [normalize_path(path, case_sensitive_uid=True) for path in obj_paths]

        if len(paths) != len(set(paths)):
            raise BulkCreateError(
                "Cannot create geographies with duplicate paths.",
                paths=[path for path in paths if paths.count(path) > 1],
            )

        existing_geos = self.__get_existing_geos(db=db, obj_paths=paths, namespace=namespace)

        if existing_geos:
            raise BulkCreateError(
                "Cannot create geographies that already exist.",
                paths=[geo.path for geo in existing_geos],
            )

        return

    def __get_missing_geo_bins(
        self, db: Session, hash_dict: dict[str, list[schemas.GeographyBase]]
    ):
        hash_keys = list(hash_dict.keys())

        # Compare raw BYTEA so the unique index is usable; wrapping the column in
        # encode() forced a full geo_bin scan that grew with table size.
        results = db.execute(
            select(models.GeoBin.geo_bin_id, models.GeoBin.geometry_hash).where(
                models.GeoBin.geometry_hash.in_([binascii.unhexlify(h) for h in hash_keys])
            )
        ).all()

        existing_hsh_to_bin_dict = {row.geometry_hash.hex(): row.geo_bin_id for row in results}

        return (
            existing_hsh_to_bin_dict,
            set(hash_keys) - set(existing_hsh_to_bin_dict.keys()),
        )

    def __insert_missing_geo_hashes(
        self,
        *,
        db: Session,
        hash_dict: dict[str, list[schemas.GeographyBase]],
        existing_hsh_to_bin_dict: dict[str, int],
        missing_hashes: set[str],
    ) -> dict[str, int]:
        empty_polygon_wkb = WKBElement(Polygon().wkb, srid=4269)

        try:
            values_list = []
            for h in missing_hashes:
                # Everything with the same hash has the same geography.
                # This is only an issue when there are empty geographies
                # Which are set to empty polygons.
                obj_in = hash_dict[h][0]

                values_list.append(
                    {
                        "geography": (
                            empty_polygon_wkb
                            if obj_in.geography is None
                            else WKBElement(obj_in.geography, srid=4269)
                        ),
                    }
                )
            result = db.execute(
                pg_insert(models.GeoBin)
                .on_conflict_do_nothing(index_elements=["geometry_hash"])
                .returning(models.GeoBin.geo_bin_id, models.GeoBin.geometry_hash),
                values_list,
            )
            bin_hash_list = [(bin_id, hsh.hex()) for bin_id, hsh in result.all()]
        # StatementError covers DBAPI errors and bind-processing failures
        # (geoalchemy2 parses WKB during execution), without swallowing
        # arbitrary Python bugs the way the old blanket except did.
        except exc.StatementError as ex:
            log.exception(
                "Geography insert failed, likely due to invalid geometries. Full error below: %s",
                ex,
            )
            raise BulkCreateError(
                "Failed to insert geometries. This is likely due to invalid Geometries; please"
                " ensure geometries can be encoded in WKB format."
            ) from ex

        for bin_id, hsh in bin_hash_list:
            assert hsh not in existing_hsh_to_bin_dict, "Duplicate hash in db"
            existing_hsh_to_bin_dict[hsh] = bin_id

        # ON CONFLICT DO NOTHING drops hashes a concurrent batch committed between
        # our lookup and this insert; fetch the winners' bin ids.
        lost_hashes = missing_hashes - set(existing_hsh_to_bin_dict.keys())
        if lost_hashes:
            rows = db.execute(
                select(models.GeoBin.geo_bin_id, models.GeoBin.geometry_hash).where(
                    models.GeoBin.geometry_hash.in_([binascii.unhexlify(h) for h in lost_hashes])
                )
            ).all()
            for row in rows:
                existing_hsh_to_bin_dict[row.geometry_hash.hex()] = row.geo_bin_id

        return existing_hsh_to_bin_dict

    def __update_geo_hashes(
        self,
        db: Session,
        objs_in: list[schemas.GeographyBase],
    ) -> tuple[dict[str, int], dict[str, str]]:
        empty_polygon_wkb = Polygon().wkb
        empty_poly_hash = hashlib.md5(WKBElement(empty_polygon_wkb, srid=4269).data).hexdigest()

        hash_obj_dict = {}

        for obj_in in objs_in:
            new_hash = (
                hashlib.md5(WKBElement(obj_in.geography, srid=4269).data).hexdigest()
                if obj_in.geography
                else empty_poly_hash
            )
            if new_hash not in hash_obj_dict:
                hash_obj_dict[new_hash] = [obj_in]
            else:
                hash_obj_dict[new_hash].append(obj_in)

        hash_bin_dict, missing_hashes = self.__get_missing_geo_bins(db=db, hash_dict=hash_obj_dict)
        if missing_hashes:
            hash_bin_dict = self.__insert_missing_geo_hashes(
                db=db,
                hash_dict=hash_obj_dict,
                existing_hsh_to_bin_dict=hash_bin_dict,
                missing_hashes=missing_hashes,
            )

        path_hash_dict = {o.path: hsh for hsh, objs_lst in hash_obj_dict.items() for o in objs_lst}

        # The following error should never fire. If it does, really bad things have happened.
        try:
            assert set(hash_bin_dict.keys()) == set(hash_obj_dict.keys())
            assert len(path_hash_dict) == len(objs_in)
        except AssertionError as ex:  # pragma: no cover
            log.exception(ex)
            raise BulkCreateError("Unexpected error when creating geometry hashes.") from ex

        return hash_bin_dict, path_hash_dict

    def __insert_geo_versions(
        self,
        db: Session,
        *,
        hash_bin_dict: dict[str, models.GeoBin],
        path_geos_dict: dict[str, models.Geography],
        path_hash_dict: dict[str, str],
        path_point_dict: dict,
        geo_import: models.GeoImport,
        valid_from: datetime,
    ):
        try:
            geo_id_to_version_dict = {
                ver.geo_id: ver
                for ver in list(
                    db.scalars(
                        insert(models.GeoVersion).returning(models.GeoVersion),
                        [
                            {
                                "import_id": geo_import.import_id,
                                "geo_id": geo.geo_id,
                                "valid_from": valid_from,
                                "geo_bin_id": hash_bin_dict[path_hash_dict[path]],
                                "internal_point": path_point_dict.get(path),
                            }
                            for path, geo in path_geos_dict.items()
                        ],
                    )
                )
            }

        except Exception as ex:  # pragma: no cover
            log.exception(ex)
            raise BulkCreateError("Failed at inserting GeoVersions.") from ex

        return geo_id_to_version_dict

    def __insert_geos(
        self,
        db: Session,
        *,
        insert_paths: list[str],
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
    ) -> dict[str, models.Geography]:
        return {
            geo.path: geo
            for geo in list(
                db.scalars(
                    insert(models.Geography).returning(models.Geography),
                    [
                        {
                            "path": normalize_path(path, case_sensitive_uid=True),
                            "meta_id": obj_meta.meta_id,
                            "namespace_id": namespace.namespace_id,
                        }
                        for path in insert_paths
                    ],
                )
            )
        }

    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.GeographyCreate,
        obj_meta: models.ObjectMeta,
        geo_import: models.GeoImport,
        namespace: models.Namespace,
    ) -> tuple[models.Geography, models.GeoVersion, uuid.UUID]:
        """Creates a new geography."""
        geo_list, etag = self.create_bulk(
            db=db,
            objs_in=[obj_in],
            obj_meta=obj_meta,
            geo_import=geo_import,
            namespace=namespace,
        )

        return geo_list[0], etag

    def create_bulk(
        self,
        db: Session,
        *,
        objs_in: list[schemas.GeographyCreate],
        obj_meta: models.ObjectMeta,
        geo_import: models.GeoImport,
        namespace: models.Namespace,
    ) -> tuple[list[tuple[models.Geography, models.GeoVersion]], uuid.UUID]:
        """Creates new geographies in bulk."""
        self.__validate_create_geos(
            db=db, obj_paths=[obj.path for obj in objs_in], namespace=namespace
        )

        objs_in, max_disp = _canonicalize_geos(objs_in)
        log.info(
            "Geo import %s: max snap displacement %.3e degrees over %d geographies.",
            geo_import.uuid,
            max_disp,
            len(objs_in),
        )

        valid_from = datetime.now(timezone.utc)

        with db.begin(nested=True):
            # Need this dict because the order of the returns from the inserts does
            # not have defined behaviour.
            path_geos_dict = self.__insert_geos(
                db=db,
                insert_paths=[o.path for o in objs_in],
                obj_meta=obj_meta,
                namespace=namespace,
            )

            hash_bin_dict, path_hash_dict = self.__update_geo_hashes(db=db, objs_in=objs_in)

            geo_id_to_version_dict = self.__insert_geo_versions(
                db=db,
                hash_bin_dict=hash_bin_dict,
                path_geos_dict=path_geos_dict,
                path_hash_dict=path_hash_dict,
                path_point_dict=_internal_point_elements(objs_in),
                geo_import=geo_import,
                valid_from=valid_from,
            )
            etag = self._update_etag(db, namespace)
        db.flush()

        return [(geo, geo_id_to_version_dict[geo.geo_id]) for geo in path_geos_dict.values()], etag

    def __validate_patch_geos(
        self,
        db: Session,
        *,
        obj_paths: list[str],
        namespace: models.Namespace,
    ) -> list[models.Geography]:
        # This is technically caught by the next error, but this is more
        # informative.
        paths = [normalize_path(path, case_sensitive_uid=True) for path in obj_paths]

        if len(paths) != len(set(paths)):
            raise BulkPatchError(
                "Cannot patch geographies with duplicate paths.",
                paths=[path for path in paths if paths.count(path) > 1],
            )

        existing_geos = self.__get_existing_geos(db=db, obj_paths=paths, namespace=namespace)

        if len(existing_geos) < len(paths):
            missing = set(paths) - set(geo.path for geo in existing_geos)
            raise BulkPatchError(
                "Cannot update geographies that do not exist.", paths=list(missing)
            )

        return existing_geos

    def __get_geoid_to_version_dict(
        self,
        db: Session,
        *,
        geo_id_list: list[int],
    ) -> dict[int, models.GeoVersion]:
        """Gets a mapping from geo_id to GeoVersion."""
        return {
            geo_id: version
            for geo_id, version in (
                db.query(models.GeoVersion.geo_id, models.GeoVersion)
                .filter(
                    models.GeoVersion.geo_id.in_(geo_id_list),
                    models.GeoVersion.valid_to.is_(None),
                )
                .all()
            )
        }

    def __get_path_hashes_to_patch(
        self,
        db: Session,
        *,
        objs_in: list[schemas.GeographyPatch],
        namespace: models.Namespace,
        allow_empty_polys: bool,
    ) -> dict[str, str]:
        empty_polygon_wkb = Polygon().wkb
        empty_hash = hashlib.md5(WKBElement(empty_polygon_wkb, srid=4269).data).hexdigest()

        new_path_hash_set = set({})

        for obj_in in objs_in:
            new_hash = (
                hashlib.md5(WKBElement(obj_in.geography, srid=4269).data).hexdigest()
                if obj_in.geography
                else empty_hash
            )
            new_path_hash_set.add((normalize_path(obj_in.path, case_sensitive_uid=True), new_hash))

        old_path_hash_set = set(
            (pair[0], pair[1].hex())
            for pair in (
                db.query(models.Geography.path, models.GeoBin.geometry_hash)
                .join(
                    models.GeoVersion,
                    models.Geography.geo_id == models.GeoVersion.geo_id,
                )
                .join(
                    models.GeoBin,
                    models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id,
                )
                .filter(
                    models.Geography.namespace_id == namespace.namespace_id,
                    models.GeoVersion.valid_to.is_(None),
                    models.Geography.path.in_(
                        normalize_path(obj.path, case_sensitive_uid=True) for obj in objs_in
                    ),
                )
                .all()
            )
        )

        missing = set(dict(new_path_hash_set).keys()) - set(dict(old_path_hash_set).keys())
        if missing:
            raise BulkPatchError(
                "Cannot patch geographies without a current version in the target "
                f"namespace: {sorted(missing)[:10]}"
            )

        diff_set = new_path_hash_set - old_path_hash_set
        if any([pair[1] == empty_hash for pair in diff_set]) and not allow_empty_polys:
            raise BulkPatchError(
                "When updating geographies, found that some new geographies are empty polygons "
                "when a previous version of the same geography in the target namespace was not "
                "empty. To allow for this, set the `allow_empty_polys` parameter to "
                "`True`."
            )

        return dict(diff_set)

    def patch_bulk(
        self,
        db: Session,
        *,
        objs_in: list[schemas.GeographyPatch],
        geo_import: models.GeoImport,
        namespace: models.Namespace,
        allow_empty_polys: bool = False,
    ) -> tuple[list[tuple[models.Geography, models.GeoVersion]], uuid.UUID]:
        """Updates geographies in bulk."""
        existing_geos = self.__validate_patch_geos(
            db=db, obj_paths=[obj.path for obj in objs_in], namespace=namespace
        )
        objs_in, max_disp = _canonicalize_geos(objs_in)
        log.info(
            "Geo patch: max snap displacement %.3e degrees over %d geographies.",
            max_disp,
            len(objs_in),
        )
        path_hash_dict = self.__get_path_hashes_to_patch(
            db=db,
            objs_in=objs_in,
            namespace=namespace,
            allow_empty_polys=allow_empty_polys,
        )
        log.debug("BEFORE GETTING GEOID TO VERSION DICT")
        # This tells me all of the versions in my target namespace
        geo_id_to_version_dict = self.__get_geoid_to_version_dict(
            db=db, geo_id_list=[geo.geo_id for geo in existing_geos]
        )

        with db.begin(nested=True):
            if len(path_hash_dict) > 0:
                path_geos_dict = {
                    geo.path: geo for geo in existing_geos if geo.path in path_hash_dict
                }

                with db.begin(nested=True):
                    valid_time = datetime.now(timezone.utc)
                    db.execute(
                        update(models.GeoVersion)
                        .where(
                            models.GeoVersion.geo_id.in_(
                                [geo.geo_id for geo in path_geos_dict.values()]
                            ),
                            models.GeoVersion.valid_to.is_(None),
                        )
                        .values(valid_to=valid_time)
                    )

                    hash_bin_dict, _path_hash_dict = self.__update_geo_hashes(
                        db=db,
                        objs_in=[obj for obj in objs_in if obj.path in path_hash_dict],
                    )

                    if path_hash_dict != _path_hash_dict:
                        raise BulkPatchError(
                            "Internal inconsistency while hashing patched "
                            "geographies; no changes were committed."
                        )

                    geo_id_to_version_dict.update(
                        self.__insert_geo_versions(
                            db=db,
                            hash_bin_dict=hash_bin_dict,
                            path_geos_dict=path_geos_dict,
                            path_hash_dict=path_hash_dict,
                            path_point_dict=_internal_point_elements(
                                [obj for obj in objs_in if obj.path in path_hash_dict]
                            ),
                            geo_import=geo_import,
                            valid_from=valid_time,
                        )
                    )

            etag = self._update_etag(db, namespace)
        db.flush()

        return [(geo, geo_id_to_version_dict[geo.geo_id]) for geo in existing_geos], etag

    # TODO: Finish this method
    def __validate_upsert_geos(
        self,
        db: Session,
        objs_in: list[schemas.GeographyUpsert],
        namespace: models.Namespace,
    ) -> None:  # pragma: no cover
        existing_geos_paths = set(
            self.__get_existing_paths(
                db=db, obj_paths=[obj.path for obj in objs_in], namespace=namespace
            )
        )
        # Need to check for unique paths since otherwise the db will just
        # insert the first occurrence which could be confusing. (This error
        # should almost never be raised in practice.)
        paths = [normalize_path(obj_in.path, case_sensitive_uid=True) for obj_in in objs_in]
        if len(paths) != len(set(paths)):
            raise BulkPatchError(
                "Cannot create or update geographies with duplicate paths.",
                paths=[path for path in paths if paths.count(path) > 1],
            )

        missing_paths = set(paths) - existing_geos_paths

        objs_to_create = [obj for obj in objs_in if obj.path in missing_paths]
        objs_to_update = [obj for obj in objs_in if obj.path in existing_geos_paths]

        self.__validate_create_geos(
            db=db, obj_paths=[obj.path for obj in objs_to_create], namespace=namespace
        )
        self.__validate_patch_geos(db=db, objs_in=objs_to_update, namespace=namespace)

        raise NotImplementedError("This method is not finished yet.")

    def upsert_bulk(
        self,
        db: Session,
        *,
        objs_in: list[schemas.GeographyUpsert],
        obj_meta: models.ObjectMeta,
        geo_import: models.GeoImport,
        namespace: models.Namespace,
    ) -> tuple[list[tuple[models.Geography, models.GeoVersion]], uuid.UUID]:  # pragma: no cover
        """Updates geographies in bulk."""
        _ = self.__validate_upsert_geos(
            db=db,
            objs_in=objs_in,
            namespace=namespace,
        )
        raise NotImplementedError("This method is not finished yet.")

    def fork_bulk(
        self,
        db: Session,
        *,
        source_namespace: models.Namespace,
        target_namespace: models.Namespace,
        create_geos_path_hash: list[tuple[str, str]],
        geo_import: models.GeoImport,
        obj_meta: models.ObjectMeta,
    ) -> tuple[list[tuple[models.Geography, models.GeoVersion]], models.ObjectMeta]:
        """Forks geographies from one namespace to another."""
        # Sanity check to make sure that the paths don't already exist before we start
        self.__validate_create_geos(
            db=db,
            obj_paths=list([pair[0] for pair in create_geos_path_hash]),
            namespace=target_namespace,
        )

        log.debug(f"Forking geographies from {source_namespace} to {target_namespace}")
        log.debug(f"Need to create geos: {create_geos_path_hash}")

        valid_from = datetime.now(timezone.utc)

        path_hash_dict = dict(create_geos_path_hash)
        with db.begin(nested=True):
            path_geos_dict = self.__insert_geos(
                db=db,
                insert_paths=list(path_hash_dict.keys()),
                obj_meta=obj_meta,
                namespace=target_namespace,
            )

            hash_bin_dict = {
                k.hex(): v
                for k, v in db.query(models.GeoBin.geometry_hash, models.GeoBin.geo_bin_id).filter(
                    models.GeoBin.geometry_hash.in_(
                        list(map(lambda x: binascii.unhexlify(x), path_hash_dict.values()))
                    )
                )
            }

            # Forked namespaces share bins, but internal points are
            # per-version: copy the source's current points onto the forks.
            source_points = dict(
                db.query(models.Geography.path, models.GeoVersion.internal_point)
                .join(
                    models.GeoVersion,
                    models.GeoVersion.geo_id == models.Geography.geo_id,
                )
                .filter(
                    models.Geography.namespace_id == source_namespace.namespace_id,
                    models.GeoVersion.valid_to.is_(None),
                    models.Geography.path.in_(list(path_hash_dict.keys())),
                )
                .all()
            )

            geo_id_to_version_dict = self.__insert_geo_versions(
                db=db,
                hash_bin_dict=hash_bin_dict,
                path_geos_dict=path_geos_dict,
                path_hash_dict=path_hash_dict,
                path_point_dict=source_points,
                geo_import=geo_import,
                valid_from=valid_from,
            )

            etag = self._update_etag(db, target_namespace)
        db.flush()

        return [(geo, geo_id_to_version_dict[geo.geo_id]) for geo in path_geos_dict.values()], etag

    def get(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.Geography | None:
        """Gets a geography by path."""
        return (
            db.query(models.Geography)
            .filter(
                models.Geography.namespace_id == namespace.namespace_id,
                models.Geography.path == path,
            )
            .first()
        )

    def get_bulk(
        self, db: Session, *, namespaced_paths: Collection[tuple[str, str]]
    ) -> list[models.Geography]:
        """Gets all geographies referenced by `namespaced_paths`."""
        # Group paths by namespace.
        paths_by_namespace: dict[str, list[str]] = defaultdict(lambda: [])
        for namespace, path in namespaced_paths:
            paths_by_namespace[namespace].append(path)

        namespaces = (
            db.query(models.Namespace.path, models.Namespace.namespace_id)
            .filter(models.Namespace.path.in_(paths_by_namespace))
            .all()
        )
        namespace_ids = {row.path: row.namespace_id for row in namespaces}

        namespace_clauses = [
            and_(
                models.Geography.namespace_id == namespace_ids[namespace],
                models.Geography.path.in_(paths),
            )
            for namespace, paths in paths_by_namespace.items()
        ]

        return db.query(models.Geography).filter(or_(*namespace_clauses)).all()


geography = CRGeography(models.Geography)
