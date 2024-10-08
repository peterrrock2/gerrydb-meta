"""CRUD operations and transformations for districting plans."""

import logging
import uuid
from typing import Tuple

from sqlalchemy import exc, insert, select
from sqlalchemy.orm import Session

from gerrydb_meta import models, schemas
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError

log = logging.getLogger()


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
                    models.GeoSetMember.set_version_id
                    == geo_set_version.set_version_id,
                )
            )
        )
        not_in_geo_set = set(geo.geo_id for geo in edge_geos.values()) - set_geo_ids

        if not_in_geo_set:
            bad_geo_paths = [
                geo.full_path for geo in edge_geos if geo.geo_id in not_in_geo_set
            ]
            raise CreateValueError(
                "Geographies not associated with locality and layer: "
                f"{', '.join(bad_geo_paths)}"
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
                f"with the underlying graph. Missing edge geographies: {', '.join(missing_geos)}"
            )

        with db.begin(nested=True):
            graph = models.Graph(
                set_version_id=geo_set_version.set_version_id,
                namespace_id=namespace.namespace_id,
                path=normalize_path(obj_in.path),
                description=obj_in.description,
                meta_id=obj_meta.meta_id,
            )
            db.add(graph)

            try:
                db.flush()
            except exc.SQLAlchemyError:
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

    def get(
        self, db: Session, *, path: str, namespace: models.Namespace
    ) -> models.View | None:
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


graph = CRGraph(models.Graph)
