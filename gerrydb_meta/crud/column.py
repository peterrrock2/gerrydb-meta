"""CRUD operations and transformations for column metadata."""

import uuid
from datetime import datetime, timezone
from typing import Any, Collection, Tuple

from sqlalchemy import exc, insert, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.enums import ColumnType
from gerrydb_meta.exceptions import ColumnValueTypeError, CreateValueError
from gerrydb_meta.utils import create_column_value_partition_text
from gerrydb_meta.value_hash import pair_digest

def increment_column_value_counts(db: Session, *, col_id: int, geo_ids: Collection[int]) -> None:
    """Bumps per-(column, set version) current-value counts after `geo_ids`
    gain their first current value for `col_id`.

    Only geographies that previously had no current value belong in `geo_ids`:
    a value change replaces a version and leaves the count unchanged. Counts
    are maintained for current set versions only; deprecated versions keep the
    counts they had when deprecated.
    """
    if not geo_ids:
        return
    db.execute(
        text(
            f"INSERT INTO {models.SCHEMA}.column_value_count "
            "(col_id, set_version_id, count) "
            "SELECT :col_id, m.set_version_id, COUNT(*) "
            f"FROM {models.SCHEMA}.geo_set_member m "
            f"JOIN {models.SCHEMA}.geo_set_version sv "
            "ON sv.set_version_id = m.set_version_id "
            "WHERE m.geo_id = ANY(CAST(:geo_ids AS integer[])) "
            "AND sv.valid_to IS NULL "
            "GROUP BY m.set_version_id "
            "ON CONFLICT (col_id, set_version_id) DO UPDATE "
            "SET count = column_value_count.count + EXCLUDED.count"
        ),
        {"col_id": col_id, "geo_ids": list(geo_ids)},
    )


def apply_value_hash_deltas(
    db: Session, *, col_id: int, deltas: dict[int, tuple[int, int]]
) -> None:
    """XORs per-geography digest deltas into the fingerprints of every
    current set version containing those geographies.

    A delta is digest(new pair) for a first value, or
    digest(old) XOR digest(new) for a change (the old pair XORs out).
    """
    if not deltas:
        return
    geo_ids = list(deltas)
    db.execute(
        text(
            "WITH deltas AS ("
            "  SELECT unnest(CAST(:gids AS integer[])) AS geo_id,"
            "         unnest(CAST(:his AS bigint[])) AS hi,"
            "         unnest(CAST(:los AS bigint[])) AS lo"
            "), agg AS ("
            "  SELECT m.set_version_id, bit_xor(d.hi) AS hi, bit_xor(d.lo) AS lo "
            f" FROM deltas d JOIN {models.SCHEMA}.geo_set_member m USING (geo_id) "
            f" JOIN {models.SCHEMA}.geo_set_version sv "
            "    ON sv.set_version_id = m.set_version_id "
            "  WHERE sv.valid_to IS NULL GROUP BY m.set_version_id"
            ") "
            f"INSERT INTO {models.SCHEMA}.column_value_count "
            "  (col_id, set_version_id, count, value_hash_hi, value_hash_lo) "
            "SELECT :col_id, agg.set_version_id, 0, agg.hi, agg.lo FROM agg "
            "ON CONFLICT (col_id, set_version_id) DO UPDATE "
            "SET value_hash_hi = COALESCE(column_value_count.value_hash_hi, 0) # EXCLUDED.value_hash_hi, "
            "    value_hash_lo = COALESCE(column_value_count.value_hash_lo, 0) # EXCLUDED.value_hash_lo"
        ),
        {
            "col_id": col_id,
            "gids": geo_ids,
            "his": [deltas[g][0] for g in geo_ids],
            "los": [deltas[g][1] for g in geo_ids],
        },
    )


# Maps the `ColumnType` enum to columns in `ColumnValue`.
COLUMN_TYPE_TO_VALUE_COLUMN = {
    ColumnType.FLOAT: "val_float",
    ColumnType.INT: "val_int",
    ColumnType.STR: "val_str",
    ColumnType.BOOL: "val_bool",
}


class CRColumn(NamespacedCRBase[models.DataColumn, schemas.ColumnCreate]):
    """CRUD operations and transformations for column metadata."""

    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.ColumnCreate,
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
    ) -> Tuple[models.DataColumn, uuid.UUID]:
        """Creates a new column with a canonical reference."""
        with db.begin(nested=True):
            # Create a path to the column.
            canonical_path = normalize_path(obj_in.canonical_path)
            canonical_ref = models.ColumnRef(
                path=canonical_path,
                meta_id=obj_meta.meta_id,
                namespace_id=namespace.namespace_id,
            )
            db.add(canonical_ref)
            try:
                db.flush()
            except exc.SQLAlchemyError:
                # TODO: Make this more specific--the primary goal is to capture the case
                # where the reference already exists.
                log.exception(
                    "Failed to create reference '%s' to new column.",
                    obj_in.canonical_path,
                )
                raise CreateValueError(
                    f"Failed to create canonical path '{canonical_path}' to new column. "
                    "(The path may already exist.)"
                )

            # Create the column itself.
            col = models.DataColumn(
                canonical_ref_id=canonical_ref.ref_id,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
                description=obj_in.description,
                source_url=(str(obj_in.source_url) if obj_in.source_url is not None else None),
                kind=obj_in.kind,
                type=obj_in.type,
            )
            db.add(col)
            try:
                db.flush()
            except exc.SQLAlchemyError:  # pragma: no cover
                log.exception("Failed to create new column.")
                raise CreateValueError("Failed to create new column.")

            canonical_ref.col_id = col.col_id
            db.flush()

            # create partition
            db.execute(create_column_value_partition_text(column_id=col.col_id))

            # Create additional aliases (non-canonical references) to the column.
            if obj_in.aliases:
                self._add_aliases(
                    db=db,
                    alias_paths=obj_in.aliases,
                    col=col,
                    obj_meta=obj_meta,
                )
            etag = self._update_etag(db, namespace)

        return col, etag

    def get_ref(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.ColumnRef | None:
        """Retrieves a column reference by reference path.

        Args:
            path: Path to column (namespace excluded).
            namespace: Column namespace.
        """
        normalized_path = normalize_path(path)

        return (
            db.query(models.ColumnRef)
            .filter(
                (models.ColumnRef.path == normalized_path)
                & (models.ColumnRef.namespace_id == namespace.namespace_id)
            )
            .first()
        )

    def get(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.DataColumn | None:
        """Retrieves a column by reference path.

        Args:
            path: Path to column (namespace excluded).
            namespace: Column namespace.
        """
        ref = self.get_ref(db, path=path, namespace=namespace)
        return None if ref is None else ref.column

    def get_global_ref(
        self, db: Session, *, path: tuple[str, str], namespace: models.Namespace
    ) -> models.DataColumn | None:
        """Retrieves a column by reference path, potentially within a different
        namespace than `namespace`.

        Only public namespaces can be addressed with a global path.

        Args:
            path: Path to column, either global-style (two parts) or local-style.
            namespace: Default column namespace.
        """
        namespace_path, column_path = path
        if namespace_path is not None:
            alt_namespace = (
                db.query(models.Namespace)
                .filter(
                    models.Namespace.path == namespace_path,
                    models.Namespace.public.is_(True),
                )
                .first()
            )
            return (
                None
                if alt_namespace is None
                else self.get_ref(db, path=column_path, namespace=alt_namespace)
            )

        return self.get_ref(db, path=column_path, namespace=namespace)

    def set_values(
        self,
        db: Session,
        *,
        col: models.DataColumn,
        values: list[Tuple[models.Geography, Any]],
        obj_meta: models.ObjectMeta,
    ) -> None:
        """Sets column values across geographies. This is tied to a specific
        geoimport for auditing purposes.

        Raises:
            ColumnValueTypeError: If column types do not match expected types.
        """
        val_column = COLUMN_TYPE_TO_VALUE_COLUMN[col.type]
        now = datetime.now(timezone.utc)

        # Validate column data.
        rows_dict = {}
        new_row_pairs = set()
        validation_errors = []
        for geo, value in values:
            suffix = f"column value for geography {geo.full_path} found {type(value)}"
            if geo.geo_id in rows_dict:
                raise ValueError(f"Duplicate geography path '{geo.path}' found.")

            if col.type == ColumnType.FLOAT and isinstance(value, int):
                # Silently promote int -> float.
                value = float(value)

            if col.type == ColumnType.FLOAT and not isinstance(value, float):
                validation_errors.append(f"Expected integer or floating-point {suffix}")
            elif col.type == ColumnType.INT and not isinstance(value, int):
                validation_errors.append(f"Expected integer {suffix}")
            elif col.type == ColumnType.STR and not isinstance(value, str):
                validation_errors.append(f"Expected string {suffix}")
            elif col.type == ColumnType.BOOL and not isinstance(value, bool):
                validation_errors.append(f"Expected boolean {suffix}")
            else:
                rows_dict[geo.geo_id] = {
                    "col_id": col.col_id,
                    "geo_id": geo.geo_id,
                    "meta_id": obj_meta.meta_id,
                    "valid_from": now,
                    val_column: value,
                }
                new_row_pairs.add((geo.geo_id, value))

        if validation_errors:
            log.error(validation_errors)
            raise ColumnValueTypeError(errors=validation_errors)

        # Add the new column values and invalidate the old ones where present.
        geo_ids = [geo.geo_id for geo, _ in values]

        # make sure partition exists for column
        db.execute(create_column_value_partition_text(column_id=col.col_id))

        old_values = {}
        for item in (
            db.query(models.ColumnValue)
            .filter(
                models.ColumnValue.col_id == col.col_id,
                models.ColumnValue.geo_id.in_(geo_ids),
                models.ColumnValue.valid_to.is_(None),
            )
            .all()
        ):
            if item.val_float is not None:
                old_values[item.geo_id] = item.val_float
            elif item.val_int is not None:
                old_values[item.geo_id] = item.val_int
            elif item.val_str is not None:
                old_values[item.geo_id] = item.val_str
            elif item.val_bool is not None:
                old_values[item.geo_id] = item.val_bool
            else:  # pragma: no cover
                # TODO: If this ever happens, add something that pings an admin.
                assert False, "Critical Error: No column value found."  # This should never happen

        # A geography needs a new version if it has no current value or its
        # current value differs; unchanged values are skipped. Partial
        # overlaps (some geographies covered, some fresh) are fine.
        old_row_pairs = set(old_values.items())
        geo_ids_to_insert = {gid for gid, value in new_row_pairs - old_row_pairs}

        # No values have changed, so we can skip the insert.
        if geo_ids_to_insert == set():  # pragma: no cover
            return

        rows = [rows_dict[geo_id] for geo_id in geo_ids_to_insert]

        with_tuples = (
            db.query(
                models.ColumnValue.col_id,
                models.ColumnValue.geo_id,
                models.ColumnValue.valid_from,
            )
            .filter(
                models.ColumnValue.col_id == col.col_id,
                models.ColumnValue.geo_id.in_(geo_ids_to_insert),
                models.ColumnValue.valid_to.is_(None),
            )
            .all()
        )

        with db.begin(nested=True):
            db.execute(insert(models.ColumnValue), rows)
            # Optimization: most column values are only set once, so we don't
            # need to invalidate old versions unless we previously detected them.
            if with_tuples:
                db.execute(
                    update(models.ColumnValue)
                    .where(
                        tuple_(
                            models.ColumnValue.col_id,
                            models.ColumnValue.geo_id,
                            models.ColumnValue.valid_from,
                        ).in_(with_tuples)
                    )
                    .values(valid_to=now)
                )
            stale_geo_ids = {t.geo_id for t in with_tuples}
            increment_column_value_counts(
                db,
                col_id=col.col_id,
                geo_ids=[g for g in geo_ids_to_insert if g not in stale_geo_ids],
            )
            path_by_id = {geo.geo_id: geo.path for geo, _ in values}
            deltas = {}
            for gid in geo_ids_to_insert:
                hi, lo = pair_digest(
                    path_by_id[gid], col.type, rows_dict[gid][val_column]
                )
                if gid in old_values:
                    ohi, olo = pair_digest(path_by_id[gid], col.type, old_values[gid])
                    hi, lo = hi ^ ohi, lo ^ olo
                deltas[gid] = (hi, lo)
            apply_value_hash_deltas(db, col_id=col.col_id, deltas=deltas)

    def create_reference(
        self,
        db: Session,
        *,
        path: str,
        namespace: models.Namespace,
        col: models.DataColumn,
        obj_meta: models.ObjectMeta,
    ) -> Tuple[models.ColumnRef, uuid.UUID]:
        """Creates a reference to `col` in `namespace` under `path`.

        Cross-namespace references may only target columns in PUBLIC
        namespaces: references resolve to the target's values at read time,
        so a reference from a public namespace to a private column would
        leak private data. Same-namespace references (plain aliases) are
        unrestricted.
        """
        if col.namespace_id != namespace.namespace_id and not col.namespace.public:
            raise CreateValueError(
                "Cannot create a reference to a column in a private namespace."
            )
        canon_path = normalize_path(path)
        existing = (
            db.query(models.ColumnRef)
            .filter_by(path=canon_path, namespace_id=namespace.namespace_id)
            .first()
        )
        if existing is not None:
            raise CreateValueError(
                f"Reference or column '{canon_path}' already exists in namespace."
            )
        with db.begin(nested=True):
            ref = models.ColumnRef(
                path=canon_path,
                col_id=col.col_id,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(ref)
            etag = self._update_etag(db, namespace)
        db.flush()
        return ref, etag

    def find_duplicate(
        self,
        db: Session,
        *,
        name: str,
        locality_path: str,
        layer_path: str,
        hash_hi: int,
        hash_lo: int,
        readable_namespace_ids: Collection[int],
    ) -> models.DataColumn | None:
        """Finds a readable column whose name/alias and content fingerprint
        match a candidate upload over (locality, layer).

        The fingerprint is compared against the stored hash for the current
        set version of (locality, layer) in the matching column's own
        namespace; name matching plus geo-set context makes accidental
        collisions (e.g. degenerate all-zero columns) implausible.
        """
        canon = normalize_path(name)
        refs = (
            db.query(models.ColumnRef)
            .filter(
                models.ColumnRef.path == canon,
                models.ColumnRef.namespace_id.in_(readable_namespace_ids),
            )
            .all()
        )
        seen_cols = set()
        for ref in refs:
            col = ref.column
            if col.col_id in seen_cols:
                continue
            seen_cols.add(col.col_id)
            row = db.execute(
                text(
                    f"SELECT c.value_hash_hi, c.value_hash_lo "
                    f"FROM {models.SCHEMA}.column_value_count c "
                    f"JOIN {models.SCHEMA}.geo_set_version sv "
                    "   ON sv.set_version_id = c.set_version_id "
                    f"JOIN {models.SCHEMA}.locality_ref lr ON lr.loc_id = sv.loc_id "
                    f"JOIN {models.SCHEMA}.geo_layer gl ON gl.layer_id = sv.layer_id "
                    "WHERE c.col_id = :col_id AND sv.valid_to IS NULL "
                    "  AND lr.path = :loc AND gl.path = :layer "
                    "  AND gl.namespace_id = :col_ns"
                ),
                {
                    "col_id": col.col_id,
                    "loc": normalize_path(locality_path),
                    "layer": normalize_path(layer_path),
                    "col_ns": col.namespace_id,
                },
            ).first()
            if row is not None and row[0] == hash_hi and row[1] == hash_lo:
                return col
        return None

    def patch(
        self,
        db: Session,
        *,
        obj: models.DataColumn,
        obj_meta: models.ObjectMeta,
        patch: schemas.ColumnPatch,
    ) -> Tuple[models.DataColumn, uuid.UUID]:
        """Patches a column (adds new aliases)."""
        new_aliases = set(normalize_path(path) for path in patch.aliases) - set(
            ref.path for ref in obj.refs
        )
        if not new_aliases:
            return obj

        db.flush()
        self._add_aliases(db=db, alias_paths=new_aliases, col=obj, obj_meta=obj_meta)
        etag = self._update_etag(db, obj.namespace)
        db.refresh(obj)
        return obj, etag

    def _add_aliases(
        self,
        *,
        db: Session,
        alias_paths: Collection[str],
        col: models.DataColumn,
        obj_meta: models.ObjectMeta,
    ) -> None:
        """Adds aliases to a column, skipping existing ones."""

        # Fetch existing alias paths as a set of strings (not ORM objects)
        existing_aliases = set(
            db.execute(
                select(models.ColumnRef.path)
                .where(models.ColumnRef.namespace_id == col.namespace_id)
                .where(models.ColumnRef.path.in_(alias_paths))
            ).scalars()
        )

        alias_paths = set(alias_paths) - existing_aliases

        for alias_path in alias_paths:
            normalized_path = normalize_path(alias_path)

            alias_ref = models.ColumnRef(
                path=normalized_path,
                col_id=col.col_id,
                namespace_id=col.namespace_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(alias_ref)

            try:
                db.flush()  # Try to commit this alias
            except IntegrityError:  # pragma: no cover
                db.rollback()  # Rollback only this failed insert
                log.error(f"Failed to add alias {alias_path} for column {col.col_id}. Skipping.")


column = CRColumn(models.DataColumn)
