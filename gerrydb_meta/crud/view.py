"""CRUD operations and transformations for views."""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import (
    Sequence,
    bindparam,
    exc,
    exists,
    func,
    insert,
    label,
    or_,
    select,
    union,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import column
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.crud.column import COLUMN_TYPE_TO_VALUE_COLUMN
from gerrydb_meta.enums import ViewRenderStatus
from gerrydb_meta.exceptions import CreateValueError, ViewConflictError

_ST_ASBINARY_REGEX = re.compile(r"ST\_AsBinary\(([a-zA-Z0-9_.]+)\)")


PLAN_BATCH_SIZE = 10000
GRAPH_BATCH_SIZE = 100000


def _view_columns(db: Session, template_version_id: int) -> dict[str, models.DataColumn]:
    """Gets the unique columns associated with a `ViewTemplateVersion` by canonical path."""
    column_ref_ids = select(models.ViewTemplateColumnMember.ref_id).filter(
        models.ViewTemplateColumnMember.template_version_id == template_version_id
    )
    column_set_ids = select(models.ViewTemplateColumnSetMember.set_id).filter(
        models.ViewTemplateColumnSetMember.template_version_id == template_version_id
    )
    column_set_ref_ids = select(models.ColumnSetMember.ref_id).filter(
        models.ColumnSetMember.set_id.in_(column_set_ids)
    )

    column_ids_with_paths = db.execute(
        select(
            models.ColumnRef.path,
            models.Namespace.path.label("namespace"),
            models.ColumnRef.col_id,
        )
        .join(
            models.Namespace,
            models.Namespace.namespace_id == models.ColumnRef.namespace_id,
        )
        .where(models.ColumnRef.ref_id.in_(union(column_set_ref_ids, column_ref_ids)))
    ).all()
    column_ids = [row.col_id for row in column_ids_with_paths]

    raw_columns = db.query(models.DataColumn).filter(models.DataColumn.col_id.in_(column_ids)).all()

    # Label columns by canonical path, not the alias the template referenced:
    # rendered column names must not depend on which alias was used.
    namespaces_by_path = defaultdict(set)
    for col in raw_columns:
        namespaces_by_path[col.canonical_ref.path].add(col.namespace.path)
    return {
        (
            f"{col.namespace.path}__{col.canonical_ref.path}"
            if len(namespaces_by_path[col.canonical_ref.path]) > 1
            else col.canonical_ref.path
        ): col
        for col in raw_columns
    }


@dataclass(frozen=True)
class ViewRenderContext:
    """Context for rendering a view's data and metadata."""

    view: models.View
    columns: dict[str, models.DataColumn]
    plans: list[models.Plan]
    plan_labels: list[str]
    plan_assignments: Sequence | None
    graph_edges: Sequence | None
    geo_meta: dict[int, models.ObjectMeta]
    geo_meta_ids: dict[str, int]  # by path
    geo_valid_from_dates: dict[str, datetime]

    # Bulk queries for `ogr2ogr`.
    geo_query: str
    internal_point_query: str

    def __repr__(self) -> str:  # pragma: no cover
        return f"ViewRenderContext(view={self.view.path}, columns={list(self.columns.keys())})"


class CRView(NamespacedCRBase[models.View, schemas.ViewCreate]):
    def __get_all_path_hashes_in_set_version(
        self, db: Session, valid_at: datetime, set_version_id: int
    ):
        return [
            (item[0], item[1])
            for item in (
                db.query(models.Geography.path, models.GeoBin.geometry_hash)
                .select_from(models.GeoSetVersion)
                .filter(
                    models.GeoSetVersion.set_version_id == set_version_id,
                )
                .join(
                    models.GeoSetMember,
                    models.GeoSetVersion.set_version_id == models.GeoSetMember.set_version_id,
                )
                .join(
                    models.GeoVersion,
                    models.GeoSetMember.geo_id == models.GeoVersion.geo_id,
                )
                .filter(
                    models.GeoVersion.valid_from <= valid_at,
                    or_(
                        models.GeoVersion.valid_to.is_(None),
                        models.GeoVersion.valid_to >= valid_at,
                    ),
                )
                .join(
                    models.Geography,
                    models.GeoVersion.geo_id == models.Geography.geo_id,
                )
                .join(
                    models.GeoBin,
                    models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id,
                )
            )
        ]

    def __get_all_set_col_ids(
        self,
        db: Session,
        available_layer_ids: list[int],
        loc_id: int,
        valid_at: datetime,
        template_version_id: int,
    ):
        log.debug("TOP OF GET_ALL_SET_COL_IDS")
        col_query = (
            db.query(models.GeoSetVersion.set_version_id, models.ColumnRef.path)
            .select_from(models.GeoSetVersion)
            .filter(
                models.GeoSetVersion.valid_from <= valid_at,
                or_(
                    models.GeoSetVersion.valid_to.is_(None),
                    models.GeoSetVersion.valid_to >= valid_at,
                ),
                models.GeoSetVersion.layer_id.in_(available_layer_ids),
                models.GeoSetVersion.loc_id == loc_id,
            )
            .join(
                models.GeoSetMember,
                models.GeoSetMember.set_version_id == models.GeoSetVersion.set_version_id,
            )
            .join(
                models.Geography,
                models.Geography.geo_id == models.GeoSetMember.geo_id,
            )
            .join(
                models.ColumnRef,
                models.ColumnRef.namespace_id == models.Geography.namespace_id,
            )
            .join(
                models.ViewTemplateColumnMember,
                models.ViewTemplateColumnMember.ref_id == models.ColumnRef.ref_id,
            )
            .filter(
                or_(
                    models.ViewTemplateColumnMember.template_version_id == template_version_id,
                )
            )
        )

        col_set_query = (
            db.query(models.GeoSetVersion.set_version_id, models.ColumnRef.path)
            .select_from(models.GeoSetVersion)
            .filter(
                models.GeoSetVersion.valid_from <= valid_at,
                or_(
                    models.GeoSetVersion.valid_to.is_(None),
                    models.GeoSetVersion.valid_to >= valid_at,
                ),
                models.GeoSetVersion.layer_id.in_(available_layer_ids),
                models.GeoSetVersion.loc_id == loc_id,
            )
            .join(
                models.GeoSetMember,
                models.GeoSetMember.set_version_id == models.GeoSetVersion.set_version_id,
            )
            .join(
                models.Geography,
                models.Geography.geo_id == models.GeoSetMember.geo_id,
            )
            .join(
                models.ColumnRef,
                models.ColumnRef.namespace_id == models.Geography.namespace_id,
            )
            .join(
                models.ColumnSetMember,
                models.ColumnSetMember.ref_id == models.ColumnRef.ref_id,
            )
            .join(
                models.ViewTemplateColumnSetMember,
                models.ViewTemplateColumnSetMember.set_id == models.ColumnSetMember.set_id,
            )
            .filter(
                or_(
                    models.ViewTemplateColumnSetMember.template_version_id == template_version_id,
                )
            )
        )

        col_results = [(item[0], item[1]) for item in col_query.distinct()]
        col_set_resuls = [(item[0], item[1]) for item in col_set_query.distinct()]

        log.debug("COL RESULTS: %s", col_results)
        log.debug("COL SET RESULTS: %s", col_set_resuls)

        ret = col_results + col_set_resuls

        return ret

    def __validate_geo_set_compatabilty(
        self,
        db: Session,
        namespace: models.Namespace,
        locality: models.Locality,
        layer: models.GeoLayer,
        valid_at: datetime,
        template_version_id: int,
    ) -> tuple[list[int], int]:

        log.debug("TOP OF VALIDATE GEO SET COMPATABILITY")
        available_layer_ids = list(
            item[0]
            for item in db.query(models.GeoLayer.layer_id)
            .filter(models.GeoLayer.path == layer.path)
            .all()
        )

        log.debug("AVAILABLE LAYER IDS: %s", available_layer_ids)
        curr_ns_query = (
            db.query(models.GeoSetVersion.set_version_id)
            .select_from(models.GeoSetVersion)
            .filter(
                models.GeoSetVersion.valid_from <= valid_at,
                or_(
                    models.GeoSetVersion.valid_to.is_(None),
                    models.GeoSetVersion.valid_to >= valid_at,
                ),
                models.GeoSetVersion.loc_id == locality.loc_id,
                models.GeoSetVersion.layer_id.in_(available_layer_ids),
            )
            .join(
                models.GeoSetMember,
                models.GeoSetMember.set_version_id == models.GeoSetVersion.set_version_id,
            )
            .join(
                models.Geography,
                models.Geography.geo_id == models.GeoSetMember.geo_id,
            )
            .join(
                models.Namespace,
                models.Geography.namespace_id == models.Namespace.namespace_id,
            )
            .filter(
                models.Namespace.path == namespace.path,
            )
            .first()
        )
        log.debug("curr_ns_query return: %s", curr_ns_query)

        if curr_ns_query is None:
            raise CreateValueError(
                "No set of geographies exists in the current namespace "
                "satisfying locality and layer constraints."
            )

        curr_ns_set_version_id = list(curr_ns_query)

        assert len(curr_ns_set_version_id) == 1
        curr_ns_set_version_id = curr_ns_set_version_id[0]

        set_version_to_cols_dict = {}
        for set_version_id, col_id in self.__get_all_set_col_ids(
            db=db,
            available_layer_ids=available_layer_ids,
            loc_id=locality.loc_id,
            valid_at=valid_at,
            template_version_id=template_version_id,
        ):
            set_version_to_cols_dict.setdefault(set_version_id, set()).add(col_id)

        all_set_version_ids = set(set_version_to_cols_dict.keys())
        log.debug("ALL SET VERSION IDS: %s", all_set_version_ids)

        if len(all_set_version_ids) == 0:
            raise CreateValueError(
                "Cannot instantiate view: no set of geographies exists "
                "satisfying locality, layer, and time constraints "
                "for the columns in the view template."
            )

        all_set_version_ids.discard(curr_ns_set_version_id)

        if len(all_set_version_ids) == 0:
            return [curr_ns_set_version_id], curr_ns_set_version_id

        # Check that all of the sets have the same geo_hashes as the current namespace
        orig_set_dict = {
            item[0]: item[1]
            for item in self.__get_all_path_hashes_in_set_version(
                db=db,
                valid_at=valid_at,
                set_version_id=curr_ns_set_version_id,
            )
        }

        log.debug("ALL SET VERSION IDS: %s", all_set_version_ids)
        log.debug("CURR NS SET VERSION ID: %s", curr_ns_set_version_id)
        for set_version_id in all_set_version_ids:
            new_set_dict = {
                item[0]: item[1]
                for item in self.__get_all_path_hashes_in_set_version(
                    db=db, valid_at=valid_at, set_version_id=set_version_id
                )
            }
            if new_set_dict != orig_set_dict:
                raise ViewConflictError(
                    "Cannot create view. Some of the geographies are defined "
                    "on a geo_layer that does not have the same geometries as "
                    "the geo_layer in the namespace. Please ensure that all of the "
                    "columns that you are trying to make a view for have the same "
                    "geographies. The following columns sets have different "
                    "geographies: \n"
                    f"\t{set_version_to_cols_dict[list(all_set_version_ids)[0]]}"
                )
        all_set_version_ids.add(curr_ns_set_version_id)
        return (
            list(all_set_version_ids),
            curr_ns_set_version_id,
        )

    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.ViewCreate,
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
        template: models.ViewTemplate | models.ViewTemplateVersion,
        locality: models.Locality,
        layer: models.GeoLayer,
        graph: Optional[models.Graph] = None,
    ) -> Tuple[models.View, uuid.UUID]:
        """Creates a new view."""
        log.debug("TOP OF CR CREATE")
        valid_at = datetime.now(timezone.utc) if obj_in.valid_at is None else obj_in.valid_at
        if valid_at > datetime.now(timezone.utc):
            raise CreateValueError("Cannot instantiate view in the future.")

        # Now go get view_template from the view_template_version
        template_version_id = (
            db.query(models.ViewTemplateVersion.template_version_id)
            .filter(
                models.ViewTemplateVersion.template_id == template.template_id,
                models.ViewTemplateVersion.valid_from <= valid_at,
                or_(
                    models.ViewTemplateVersion.valid_to.is_(None),
                    models.ViewTemplateVersion.valid_to >= valid_at,
                ),
            )
            .scalar()
        )
        if template_version_id is None:
            raise CreateValueError("No template version found satisfying time constraints.")

        (
            all_set_version_ids,
            curr_ns_set_version_id,
        ) = self.__validate_geo_set_compatabilty(
            db=db,
            namespace=namespace,
            locality=locality,
            layer=layer,
            valid_at=valid_at,
            template_version_id=template_version_id,
        )

        # Run the set version check on the db side of things
        if graph is not None and graph.set_version_id != curr_ns_set_version_id:
            raise CreateValueError(
                f'Cannot instantiate view: graph "{graph.full_path}" does not match '
                f'locality "{locality.canonical_ref.path}" and geographic layer '
                f'"{layer.full_path}".'
            )
        if graph is not None and graph.created_at > valid_at:
            raise CreateValueError(
                f'Cannot instantiate view: graph "{graph.full_path}" exists '
                f"in the future relative to view timestamp ({valid_at})."
            )

        columns = _view_columns(db, template_version_id)

        geo_set_members = (
            db.query(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id.in_(all_set_version_ids))
            .subquery()
        )

        value_counts = (
            db.query(
                models.ColumnValue.col_id,
                label("num_geos", func.count(models.ColumnValue.geo_id)),
            )
            .join(geo_set_members, geo_set_members.c.geo_id == models.ColumnValue.geo_id)
            .filter(
                models.ColumnValue.col_id.in_(bindparam("col_ids", expanding=True)),
                models.ColumnValue.valid_from <= valid_at,
                (
                    (models.ColumnValue.valid_to.is_(None))
                    | (models.ColumnValue.valid_to >= valid_at)
                ),
            )
            .params(col_ids=[col.col_id for col in columns.values()])
            .group_by(models.ColumnValue.col_id)
            .all()
        )
        value_counts_by_col = {group.col_id: group.num_geos for group in value_counts}

        log.debug("VALUE COUNTS: %s", value_counts_by_col)

        bad_cols = []

        num_geos = len(
            db.query(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id == curr_ns_set_version_id)
            .all()
        )

        for column in columns.values():
            value_count = value_counts_by_col.get(column.col_id, 0)
            if value_count != num_geos:
                bad_cols.append((column.canonical_ref.full_path, value_count))

        if bad_cols:
            bad_cols_formatted = ", ".join(
                f"{col_path} ({count} values found, {num_geos} values expected)"
                for col_path, count in bad_cols
            )
            raise CreateValueError(
                "Cannot instantiate view: column values satisfying all constraints "
                "constraints not available for all geographies. Bad columns: " + bad_cols_formatted
            )

        canonical_path = normalize_path(obj_in.path)
        with db.begin(nested=True):
            view = models.View(
                path=canonical_path,
                namespace_id=namespace.namespace_id,
                meta_id=obj_meta.meta_id,
                template_id=template.template_id,
                template_version_id=template_version_id,
                loc_id=locality.loc_id,
                layer_id=layer.layer_id,
                graph_id=None if graph is None else graph.graph_id,
                at=valid_at,
                proj=obj_in.proj,
                num_geos=num_geos,
            )

            db.add(view)

            try:
                # Need this to get the view_id
                db.flush()
            except exc.SQLAlchemyError:
                log.exception(
                    "Failed to create view '%s'.",
                    canonical_path,
                )
                raise CreateValueError(
                    f"Failed to create view '{canonical_path}'. "
                    "(The path may already exist in the namespace.)"
                )

            etag = self._update_etag(db, namespace)

            db.refresh(view)

            try:
                with db.begin_nested():
                    geo_set_version_data = [
                        {"view_id": view.view_id, "set_version_id": set_ver_id}
                        for set_ver_id in set(all_set_version_ids)
                    ]
                    db.execute(insert(models.ViewGeoSetVersions).values(geo_set_version_data))
            except SQLAlchemyError as e:  # pragma: no cover
                log.exception("Failed to insert view_set_versions for view '%s'.", view.view_id)
                # Raise a new error (or your custom error) if the insert fails.
                raise CreateValueError(
                    f"Failed to create view set versions for view '{view.view_id}'."
                ) from e

        log.debug("VIEW!!!!: %s", view.view_id)

        return view, etag

    def get(self, db: Session, *, path: str, namespace: models.Namespace) -> models.View | None:
        """Retrieves a view by reference path.

        Args:
            path: Path to view (namespace excluded).
            namespace: View's namespace.
        """
        return (
            db.query(models.View)
            .filter(
                models.View.namespace_id == namespace.namespace_id,
                models.View.path == normalize_path(path),
            )
            .first()
        )

    def all(self, db: Session, *, namespace: models.Namespace) -> list[models.View]:
        """Retrieves all views in a namespace."""
        return (
            db.query(models.View).filter(models.View.namespace_id == namespace.namespace_id).all()
        )

    def _create_render(
        self,
        db: Session,
        *,
        view: models.View,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
        status: ViewRenderStatus,
    ) -> models.ViewRender:
        """Creates view render metadata."""
        render = models.ViewRender(
            view_id=view.view_id,
            render_id=render_id,
            created_by=created_by.user_id,
            path=path,
            status=status,
        )
        db.add(render)
        db.flush()
        db.refresh(render)
        return render

    def cache_render(
        self,
        db: Session,
        *,
        view: models.View,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
    ) -> models.ViewRender:
        """Saves metadata for a successful render."""
        return self._create_render(
            db=db,
            view=view,
            created_by=created_by,
            render_id=render_id,
            path=path,
            status=ViewRenderStatus.SUCCEEDED,
        )

    def queue_render(
        self,
        db: Session,
        *,
        view: models.View,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
    ) -> models.ViewRender:  # pragma: no cover
        """Adds a render to the job queue."""
        return self._create_render(
            db=db,
            view=view,
            created_by=created_by,
            render_id=render_id,
            path=path,
            status=ViewRenderStatus.PENDING,
        )

    def get_cached_render(self, db: Session, *, view: models.View) -> models.ViewRender | None:
        """Retrieves metadata for a cached view render, if available."""
        return (
            db.query(models.ViewRender)
            .filter(
                models.ViewRender.view_id == view.view_id,
                models.ViewRender.status == ViewRenderStatus.SUCCEEDED,
            )
            .order_by(models.ViewRender.created_at.desc())
            .first()
        )

    # def render(self, db: Session, *, view: models.View) -> ViewRenderContext:
    #     """Generates queries to retrieve view data.

    #     Used for bulk exports via `ogr2ogr`.
    #     """
    #     log.debug("TOP OF CR RENDER")
    #     columns = _view_columns(db, view.template_version_id)

    #     view_set_version_ids = [
    #         item[0]
    #         for item in (
    #             db.query(models.ViewGeoSetVersions.set_version_id)
    #             .filter(models.ViewGeoSetVersions.view_id == view.view_id)
    #             .distinct()
    #             .all()
    #         )
    #     ]

    #     members_sub = (
    #         select(
    #             models.GeoSetMember.geo_id,
    #         )
    #         .where(models.GeoSetMember.set_version_id.in_(view_set_version_ids))
    #         .distinct()
    #         .subquery("members_sub")
    #     )
    #     geo_sub = (
    #         select(models.Geography.geo_id, models.Geography.path)
    #         .distinct()
    #         .subquery("geo_sub")
    #     )

    #     agg_selects = []
    #     column_labels = []
    #     col_ids = []
    #     for _, col in columns.items():
    #         agg_selects.append(
    #             func.max(column(COLUMN_TYPE_TO_VALUE_COLUMN[col.type]))
    #             .filter(models.ColumnValue.col_id == col.col_id)
    #             .label(col.canonical_ref.path)
    #         )
    #         column_labels.append(column(col.canonical_ref.path))
    #         col_ids.append(col.col_id)

    #     column_sub = (
    #         select(models.Geography.path, *agg_selects)
    #         .select_from(models.Geography)
    #         .join(members_sub, members_sub.c.geo_id == models.Geography.geo_id)
    #         .join(models.ColumnValue, models.ColumnValue.geo_id == members_sub.c.geo_id)
    #         .where(
    #             models.ColumnValue.col_id.in_(col_ids),
    #             models.ColumnValue.valid_from <= view.at,
    #             or_(
    #                 models.ColumnValue.valid_to.is_(None),
    #                 models.ColumnValue.valid_to >= view.at,
    #             ),
    #         )
    #         .group_by(models.Geography.path)
    #         .subquery("column_value")
    #     )

    #     timestamp_clauses = [
    #         models.GeoVersion.valid_from <= view.at,
    #         or_(
    #             models.GeoVersion.valid_to.is_(None),
    #             models.GeoVersion.valid_to >= view.at,
    #         ),
    #     ]

    #     geo_query = (
    #         select(
    #             geo_sub.c.path,
    #             models.GeoBin.geography,
    #             *column_labels,
    #         )
    #         .select_from(models.GeoVersion)
    #         .join(
    #             members_sub,
    #             members_sub.c.geo_id == models.GeoVersion.geo_id,
    #         )
    #         .join(geo_sub, geo_sub.c.geo_id == models.GeoVersion.geo_id)
    #         .join(
    #             models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id
    #         )
    #     )

    #     geo_query = geo_query.join(column_sub, column_sub.c.path == geo_sub.c.path)
    #     geo_query = geo_query.distinct().where(*timestamp_clauses)

    #     log.debug(
    #         "GEO QUERY: %s",
    #         str(
    #             geo_query.compile(
    #                 dialect=postgresql.dialect(),
    #                 compile_kwargs={"literal_binds": True},
    #             )
    #         ),
    #     )

    #     geo_id_query = (
    #         select(models.Geography.geo_id)
    #         .select_from(models.Geography)
    #         .join(
    #             models.GeoSetMember,
    #             models.Geography.geo_id == models.GeoSetMember.geo_id,
    #         )
    #         .join(
    #             models.GeoSetVersion,
    #             models.GeoSetMember.set_version_id
    #             == models.GeoSetVersion.set_version_id,
    #         )
    #         .where(models.GeoSetVersion.set_version_id.in_(view_set_version_ids))
    #         .distinct()
    #         .subquery("geo_id_query")
    #     )

    #     internal_point_query = (
    #         select(models.Geography.path, models.GeoBin.internal_point)
    #         .select_from(models.Geography)
    #         .join(
    #             models.GeoVersion, models.Geography.geo_id == models.GeoVersion.geo_id
    #         )
    #         .join(
    #             models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id
    #         )
    #         .where(exists().where(geo_id_query.c.geo_id == models.Geography.geo_id))
    #         .where(*timestamp_clauses)
    #         .distinct()
    #     )

    #     plans, plan_labels, plan_assignments = self._plans(db, view)
    #     geo_meta_ids, geo_meta = self._geo_meta(db, view)
    #     geo_valid_from_dates = self._geo_valid_dates(db, view)

    #     # Query generation: substitute in literals and remove the
    #     # ST_AsBinary() calls added by GeoAlchemy2.
    #     full_geo_query = re.sub(
    #         _ST_ASBINARY_REGEX,
    #         r"\1",
    #         str(
    #             geo_query.compile(
    #                 dialect=postgresql.dialect(),
    #                 compile_kwargs={"literal_binds": True},
    #             )
    #         ),
    #     )

    #     log.debug("The new geo query is %s", full_geo_query)

    #     full_internal_point_query = re.sub(
    #         _ST_ASBINARY_REGEX,
    #         r"\1",
    #         str(
    #             internal_point_query.compile(
    #                 dialect=postgresql.dialect(),
    #                 compile_kwargs={"literal_binds": True},
    #             )
    #         ),
    #     )

    #     log.debug("The new internal point query is %s", full_internal_point_query)

    #     ret = ViewRenderContext(
    #         view=view,
    #         columns=columns,
    #         plans=plans,
    #         plan_labels=plan_labels,
    #         plan_assignments=plan_assignments,
    #         graph_edges=self._graph_edges(db, view),
    #         geo_meta=geo_meta,
    #         geo_meta_ids=geo_meta_ids,
    #         geo_valid_from_dates=geo_valid_from_dates,
    #         geo_query=full_geo_query,
    #         internal_point_query=full_internal_point_query,
    #     )
    #     return ret

    def _view_set_version_ids(self, db: Session, view_id: int) -> list[int]:
        """Gets all geography-set versions associated with a view."""
        return [
            item[0]
            for item in (
                db.query(models.ViewGeoSetVersions.set_version_id)
                .filter(models.ViewGeoSetVersions.view_id == view_id)
                .distinct()
                .all()
            )
        ]

    def render(self, db: Session, *, view: models.View) -> ViewRenderContext:
        """Generates queries to retrieve view data.

        Used for bulk exports via `ogr2ogr`.
        """
        log.debug("TOP OF CR RENDER")
        columns = _view_columns(db, view.template_version_id)
        view_set_version_ids = self._view_set_version_ids(db, view.view_id)
        col_ids = [col.col_id for col in columns.values()]

        geo_id_query = (
            select(models.GeoSetMember.geo_id)
            .where(models.GeoSetMember.set_version_id.in_(view_set_version_ids))
            .distinct()
            .subquery("geo_id_query")
        )

        col_agg_selects = []
        column_aliases = []
        for alias, col in columns.items():
            value_col = getattr(models.ColumnValue, COLUMN_TYPE_TO_VALUE_COLUMN[col.type])
            col_agg_selects.append(
                func.max(value_col).filter(models.ColumnValue.col_id == col.col_id).label(alias)
            )
            column_aliases.append(alias)

        # Grouped by geography *path*, not geo_id: cross-namespace views hold one
        # geo_id per namespace for the same path, and their values must merge into
        # a single output row.
        col_table_sub = (
            select(models.Geography.path, *col_agg_selects)
            .select_from(models.ColumnValue)
            .join(models.Geography, models.Geography.geo_id == models.ColumnValue.geo_id)
            .where(models.ColumnValue.col_id.in_(col_ids))
            .where(models.ColumnValue.geo_id.in_(select(geo_id_query.c.geo_id)))
            .where(
                models.ColumnValue.valid_from <= view.at,
                or_(
                    models.ColumnValue.valid_to.is_(None),
                    models.ColumnValue.valid_to >= view.at,
                ),
            )
            .group_by(models.Geography.path)
            .subquery("col_table_sub")
        )

        current_geo_version_sub = (
            select(
                models.GeoVersion.geo_id,
                models.GeoVersion.geo_bin_id,
                func.row_number()
                .over(
                    partition_by=models.GeoVersion.geo_id,
                    order_by=models.GeoVersion.valid_from.desc(),
                )
                .label("row_num"),
            )
            .where(models.GeoVersion.geo_id.in_(select(geo_id_query.c.geo_id)))
            .where(
                models.GeoVersion.valid_from <= view.at,
                or_(
                    models.GeoVersion.valid_to.is_(None),
                    models.GeoVersion.valid_to >= view.at,
                ),
            )
            .subquery("current_geo_version_sub")
        )

        geo_sub = (
            select(
                models.Geography.geo_id,
                models.Geography.path,
                models.GeoBin.geography,
                models.GeoBin.internal_point,
                # One geometry row per path: cross-namespace views carry the same
                # path once per namespace (bin-deduped, so byte-identical); pick
                # deterministically by lowest geo_id.
                func.row_number()
                .over(
                    partition_by=models.Geography.path,
                    order_by=models.Geography.geo_id,
                )
                .label("path_row_num"),
            )
            .select_from(models.Geography)
            .join(
                current_geo_version_sub,
                (models.Geography.geo_id == current_geo_version_sub.c.geo_id)
                & (current_geo_version_sub.c.row_num == 1),
            )
            .join(
                models.GeoBin,
                current_geo_version_sub.c.geo_bin_id == models.GeoBin.geo_bin_id,
            )
            .subquery("geo_sub")
        )

        geo_query = (
            select(
                geo_sub.c.path,
                geo_sub.c.geography,
                *[col_table_sub.c[alias] for alias in column_aliases],
            )
            .select_from(geo_sub)
            .join(col_table_sub, geo_sub.c.path == col_table_sub.c.path)
            .where(geo_sub.c.path_row_num == 1)
        )

        internal_point_query = select(geo_sub.c.path, geo_sub.c.internal_point).where(
            geo_sub.c.path_row_num == 1
        )

        plans, plan_labels, plan_assignments = self._plans(
            db, view, view_set_version_ids=view_set_version_ids
        )
        geo_meta_ids, geo_meta = self._geo_meta(db, view, view_set_version_ids=view_set_version_ids)
        geo_valid_from_dates = self._geo_valid_dates(
            db, view, view_set_version_ids=view_set_version_ids
        )

        # Query generation: substitute in literals and remove the
        # ST_AsBinary() calls added by GeoAlchemy2.
        full_geo_query = re.sub(
            _ST_ASBINARY_REGEX,
            r"\1",
            str(
                geo_query.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ),
        )

        log.debug("The new geo query is %s", full_geo_query)

        full_internal_point_query = re.sub(
            _ST_ASBINARY_REGEX,
            r"\1",
            str(
                internal_point_query.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ),
        )

        log.debug("The new internal point query is %s", full_internal_point_query)

        ret = ViewRenderContext(
            view=view,
            columns=columns,
            plans=plans,
            plan_labels=plan_labels,
            plan_assignments=plan_assignments,
            graph_edges=self._graph_edges(db, view),
            geo_meta=geo_meta,
            geo_meta_ids=geo_meta_ids,
            geo_valid_from_dates=geo_valid_from_dates,
            geo_query=full_geo_query,
            internal_point_query=full_internal_point_query,
        )
        return ret

    def _geo_meta(
        self,
        db: Session,
        view: models.View,
        view_set_version_ids: list[int] | None = None,
    ) -> tuple[dict[str, int], dict[int, models.ObjectMeta]]:
        """Gets object metadata associated with a view's geographies.

        Returns:
            (1) Mapping from geography paths to metadata IDs.
            (2) Mapping from metadata IDs to metadata objects.
        """
        if view_set_version_ids is None:
            view_set_version_ids = self._view_set_version_ids(db, view.view_id)

        members_sub = (
            select(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id.in_(view_set_version_ids))
            .subquery()
        )
        raw_geo_meta_ids = db.execute(
            select(models.Geography.path, models.Geography.meta_id).join(
                members_sub, members_sub.c.geo_id == models.Geography.geo_id
            )
        ).fetchall()
        geo_meta_ids = {row.path: row.meta_id for row in raw_geo_meta_ids}

        distinct_meta_ids = set(geo_meta_ids.values())
        raw_distinct_meta = (
            db.query(models.ObjectMeta)
            .where(models.ObjectMeta.meta_id.in_(distinct_meta_ids))
            .all()
        )
        distinct_meta = {meta.meta_id: meta for meta in raw_distinct_meta}

        return geo_meta_ids, distinct_meta

    def _geo_valid_dates(
        self,
        db: Session,
        view: models.View,
        view_set_version_ids: list[int] | None = None,
    ) -> dict[str, datetime]:
        """Gets the valid dates for each geometry.

        Returns:
            A dictionary mapping geometry IDs to valid dates.
        """
        if view_set_version_ids is None:
            view_set_version_ids = self._view_set_version_ids(db, view.view_id)

        members_sub = (
            select(models.GeoSetMember.geo_id)
            .where(models.GeoSetMember.set_version_id.in_(view_set_version_ids))
            .distinct()
            .subquery("members_sub")
        )
        current_geo_version_sub = (
            select(
                models.GeoVersion.geo_id,
                models.GeoVersion.valid_from,
                func.row_number()
                .over(
                    partition_by=models.GeoVersion.geo_id,
                    order_by=models.GeoVersion.valid_from.desc(),
                )
                .label("row_num"),
            )
            .join(members_sub, members_sub.c.geo_id == models.GeoVersion.geo_id)
            .where(
                models.GeoVersion.valid_from <= view.at,
                or_(
                    models.GeoVersion.valid_to.is_(None),
                    models.GeoVersion.valid_to >= view.at,
                ),
            )
            .subquery("current_geo_version_sub")
        )

        query = (
            select(models.Geography.path, current_geo_version_sub.c.valid_from)
            .join(
                current_geo_version_sub,
                models.Geography.geo_id == current_geo_version_sub.c.geo_id,
            )
            .where(current_geo_version_sub.c.row_num == 1)
        )

        result = db.execute(query)

        return {row.path: row.valid_from for row in result}

    def _plans(
        self,
        db: Session,
        view: models.View,
        view_set_version_ids: list[int] | None = None,
    ) -> tuple[list[models.Plan], list[str], Sequence | None]:
        """Gets plans associated with a view.

        Returns:
            (1) A list of plans compatible with the view.
                (These plans also satisfy the view's public join constraint.)
            (2) A list of column labels for the plans.
            (3) A database iterator for the plan assignments, if any assignments
                are available.
        """
        if view_set_version_ids is None:
            view_set_version_ids = self._view_set_version_ids(db, view.view_id)

        # Get plans that existed when the view was created.
        plans = (
            db.query(models.Plan)
            .filter(
                models.Plan.set_version_id.in_(view_set_version_ids),
                models.Plan.created_at <= view.at,
            )
            .all()
        )
        # Apply the public join constraint: don't leak any private plans.
        visible_plans = [
            plan
            for plan in plans
            if (plan.namespace.public or plan.namespace.namespace_id == view.namespace.namespace_id)
        ]

        # Get plan assignments as a table.
        plan_labels = []
        if len(visible_plans) == 0:  # pragma: no cover
            return [], [], None

        # Determine the shortest unambiguous alias for each plan.
        namespaces_by_path = defaultdict(set)
        for plan in visible_plans:
            namespaces_by_path[plan.path].add(plan.namespace.path)

        # Generate query clauses for each plan.
        plan_subs = []
        for plan in visible_plans:
            label = (
                f"{plan.namespace.path}__{plan.path}"
                if len(namespaces_by_path[plan.path]) > 1
                else plan.path
            )
            plan_labels.append(label)
            plan_subs.append(
                select(models.PlanAssignment.geo_id, models.PlanAssignment.assignment)
                .where(
                    models.PlanAssignment.plan_id == plan.plan_id,
                )
                .subquery()
            )

        geo_sub = select(models.Geography.geo_id, models.Geography.path).subquery()
        members_sub = (
            select(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id.in_(view_set_version_ids))
            .subquery()
        )
        plan_cols = [
            plan_sub.c.assignment.label(plan_label)
            for plan_sub, plan_label in zip(plan_subs, plan_labels)
        ]
        plan_assignment_query = (
            select(members_sub.c.geo_id, geo_sub.c.path, *plan_cols)
            .select_from(members_sub)
            .join(geo_sub, geo_sub.c.geo_id == members_sub.c.geo_id)
        )
        for plan_sub in plan_subs:
            plan_assignment_query = plan_assignment_query.outerjoin(
                plan_sub,
                plan_sub.c.geo_id == members_sub.c.geo_id,
            )
        plan_assignments = db.execute(plan_assignment_query).fetchall()

        return visible_plans, plan_labels, plan_assignments

    def _graph_edges(self, db: Session, view: models.View) -> Sequence | None:
        """Gets graph edges by path, if applicable."""
        if view.graph_id is None:  # pragma: no cover
            return None

        path_sub_1 = select(models.Geography.geo_id, models.Geography.path).subquery()
        path_sub_2 = select(models.Geography.geo_id, models.Geography.path).subquery()
        graph_edges_query = (
            select(
                path_sub_1.c.path.label("path_1"),
                path_sub_2.c.path.label("path_2"),
                models.GraphEdge.weights,
            )
            .join(
                path_sub_1,
                path_sub_1.c.geo_id == models.GraphEdge.geo_id_1,
            )
            .join(
                path_sub_2,
                path_sub_2.c.geo_id == models.GraphEdge.geo_id_2,
            )
            .where(
                models.GraphEdge.graph_id == view.graph_id,
            )
        )

        return db.execute(graph_edges_query).fetchall()


view = CRView(models.View)
