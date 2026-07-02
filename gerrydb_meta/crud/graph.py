"""CRUD operations and transformations for districting plans."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple

from sqlalchemy import (
    Sequence,
    exc,
    insert,
    or_,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError

_ST_ASBINARY_REGEX = re.compile(r"ST\_AsBinary\(([a-zA-Z0-9_.]+)\)")


@dataclass(frozen=True)
class GraphRenderContext:
    graph: models.Graph
    graph_edges: Sequence | None
    geo_meta: dict[int, models.ObjectMeta]
    geo_meta_ids: dict[str, int]  # by path
    geo_valid_from_dates: dict[str, datetime]

    # Bulk queries for `ogr2ogr`.
    geo_query: str
    internal_point_query: str

    def __repr__(self):  # pragma: no cover
        return f"GraphRenderContext(graph={self.graph})"


class CRGraph(NamespacedCRBase[models.Graph, schemas.GraphCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.GraphCreate,
        geo_set_version: models.GeoSetVersion,
        edge_geos: dict[str, models.Geography],
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
    ) -> Tuple[models.Graph, uuid.UUID]:
        """Creates a new graph."""
        set_geo_ids = set(
            db.scalars(
                select(models.GeoSetMember.geo_id).filter(
                    models.GeoSetMember.set_version_id == geo_set_version.set_version_id,
                )
            )
        )
        not_in_geo_set = set(geo.geo_id for geo in edge_geos.values()) - set_geo_ids

        if not_in_geo_set:
            bad_geo_paths = [
                geo.full_path for geo in edge_geos.values() if geo.geo_id in not_in_geo_set
            ]
            raise CreateValueError(
                f"Geographies not associated with locality and layer: {', '.join(bad_geo_paths)}"
            )

        # Check to make sure that all of the edges exist in the set of geographies
        # associated with the locality and layer.
        missing_geos = set()
        for geo_path_1, geo_path_2, _ in obj_in.edges:
            if geo_path_1 not in edge_geos:
                missing_geos.add(geo_path_1)
            if geo_path_2 not in edge_geos:
                missing_geos.add(geo_path_2)

        if len(missing_geos) > 0:
            raise CreateValueError(
                "Passed edge geographies do not match the geographies associated "
                f"with the underlying graph. Missing edge geographies: [{', '.join(missing_geos)}]"
            )

        with db.begin(nested=True):
            graph = models.Graph(
                set_version_id=geo_set_version.set_version_id,
                namespace_id=namespace.namespace_id,
                path=normalize_path(obj_in.path),
                description=obj_in.description,
                meta_id=obj_meta.meta_id,
                proj=obj_in.proj,
            )
            db.add(graph)

            try:
                db.flush()
            except exc.SQLAlchemyError:  # pragma: no cover
                # TODO: Make this more specific--the primary goal is to capture the case
                # where the reference already exists.
                log.exception("Failed to create new graph.")
                raise CreateValueError(
                    "Failed to create new graph. (The path(s) may already exist.)"
                )

            db.refresh(graph)
            db.execute(
                insert(models.GraphEdge),
                [
                    {
                        "graph_id": graph.graph_id,
                        "geo_id_1": edge_geos[geo_path_1].geo_id,
                        "geo_id_2": edge_geos[geo_path_2].geo_id,
                        "weights": weights,
                    }
                    for geo_path_1, geo_path_2, weights in obj_in.edges
                ],
            )
            etag = self._update_etag(db, namespace)

        return graph, etag

    def all(self, db: Session, *, namespace: models.Namespace) -> list[models.View]:
        """Retrieves all views in a namespace."""
        return (
            db.query(models.Graph).filter(models.Graph.namespace_id == namespace.namespace_id).all()
        )

    def get(self, db: Session, *, path: str, namespace: models.Namespace) -> models.Graph | None:
        """Retrieves a graph by path.

        Args:
            path: Path to graph (namespace excluded).
            namespace: Graph's namespace.
        """
        return (
            db.query(models.Graph)
            .filter(
                models.Graph.namespace_id == namespace.namespace_id,
                models.Graph.path == normalize_path(path),
            )
            .first()
        )

    def _graph_edges(self, db: Session, graph: models.Graph) -> Sequence | None:
        """Gets graph edges by path, if applicable."""
        log.debug("Getting graph edges for graph %s", graph.graph_id)
        if graph.graph_id is None:  # pragma: no cover
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
                models.GraphEdge.graph_id == graph.graph_id,
            )
        )
        log.debug("GRAPH EDGES QUERY %s", graph_edges_query)
        ret = db.execute(graph_edges_query).fetchall()
        log.debug("GRAPH EDGES QUERY RET %s", len(ret))
        return ret

    def _geo_meta(
        self, db: Session, graph: models.Graph
    ) -> tuple[dict[str, int], dict[int, models.ObjectMeta]]:
        """Gets object metadata associated with a view's geographies.

        Returns:
            (1) Mapping from geography paths to metadata IDs.
            (2) Mapping from metadata IDs to metadata objects.
        """
        members_sub = (
            select(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id == graph.set_version_id)
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

    def _geo_valid_dates(self, db: Session, graph: models.Graph) -> dict[str, datetime]:
        """Gets the valid dates for each geometry.

        Returns:
            A dictionary mapping geometry IDs to valid dates.
        """

        query = (
            select(models.Geography.path, models.GeoVersion.valid_from)
            .join(
                models.GeoSetMember,
                models.Geography.geo_id == models.GeoSetMember.geo_id,
            )
            .join(models.GeoVersion, models.Geography.geo_id == models.GeoVersion.geo_id)
            .where(models.GeoSetMember.set_version_id == graph.set_version_id)
        )

        result = db.execute(query)

        return {row.path: row.valid_from for row in result}

    def render(self, db: Session, graph: models.Graph) -> GraphRenderContext:
        timestamp_clauses = [
            models.GeoVersion.valid_from <= graph.created_at,
            or_(
                models.GeoVersion.valid_to.is_(None),
                models.GeoVersion.valid_to >= graph.created_at,
            ),
        ]

        members_sub = (
            select(models.GeoSetMember.geo_id)
            .filter(models.GeoSetMember.set_version_id == graph.set_version_id)
            .subquery("members_sub")
        )

        geo_sub = (
            select(
                models.Geography.geo_id,
                models.Geography.path,
            )
            .where(
                models.Geography.namespace_id == graph.namespace_id,
            )
            .subquery("geo_sub")
        )

        geo_query = (
            select(
                geo_sub.c.path,
                models.GeoBin.geography,
            )
            .select_from(models.GeoVersion)
            .join(members_sub, members_sub.c.geo_id == models.GeoVersion.geo_id)
            .join(geo_sub, geo_sub.c.geo_id == models.GeoVersion.geo_id)
            .join(models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id)
        )

        geo_query = geo_query.distinct().where(*timestamp_clauses)

        internal_point_query = (
            select(
                geo_sub.c.path,
                models.GeoBin.internal_point,
            )
            .select_from(models.GeoVersion)
            .join(members_sub, members_sub.c.geo_id == models.GeoVersion.geo_id)
            .join(geo_sub, geo_sub.c.geo_id == models.GeoVersion.geo_id)
            .join(models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id)
            .where(*timestamp_clauses)
        )

        geo_meta_ids, geo_meta = self._geo_meta(db, graph)
        geo_valid_from_dates = self._geo_valid_dates(db, graph)

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
        ret = GraphRenderContext(
            graph=graph,
            graph_edges=self._graph_edges(db, graph),
            geo_meta=geo_meta,
            geo_meta_ids=geo_meta_ids,
            geo_valid_from_dates=geo_valid_from_dates,
            geo_query=full_geo_query,
            internal_point_query=full_internal_point_query,
        )

        return ret

    def _create_render(
        self,
        db: Session,
        *,
        graph: models.Graph,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
        status: models.GraphRenderStatus,
    ) -> models.GraphRender:  # pragma: no cover
        """Creates graph render metadata."""
        render = models.GraphRender(
            graph_id=graph.graph_id,
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
        graph: models.Graph,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
    ) -> models.GraphRender:  # pragma: no cover
        """Saves metadata for a successful render"""
        self._create_render(
            db=db,
            graph=graph,
            created_by=created_by,
            render_id=render_id,
            path=path,
            status=models.GraphRenderStatus.SUCCEEDED,
        )

    def queue_render(
        self,
        db: Session,
        *,
        graph: models.Graph,
        created_by: models.User,
        render_id: uuid.UUID,
        path: Path | str,
    ) -> models.GraphRender:  # pragma: no cover
        """Adds a render to the job queue."""
        return self._create_render(
            db=db,
            graph=graph,
            created_by=created_by,
            render_id=render_id,
            path=path,
            status=models.GraphRenderStatus.PENDING,
        )

    def get_cached_render(
        self, db: Session, *, graph: models.Graph
    ) -> models.GraphRender | None:  # pragma: no cover
        return (
            db.query(models.GraphRender)
            .filter(
                models.GraphRender.graph_id == graph.graph_id,
                models.GraphRender.status == models.GraphRenderStatus.SUCCEEDED,
            )
            .order_by(models.GraphRender.created_at.desc())
            .first()
        )


graph = CRGraph(models.Graph)
