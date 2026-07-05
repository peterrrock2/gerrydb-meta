"""CRUD operations and transformations for districting plans."""

import uuid
from typing import Tuple

from sqlalchemy import exc, select
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import models, schemas
from gerrydb_meta.utils import copy_rows
from gerrydb_meta.crud.base import NamespacedCRBase, normalize_path
from gerrydb_meta.exceptions import CreateValueError


class CRPlan(NamespacedCRBase[models.Plan, schemas.PlanCreate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: schemas.PlanCreate,
        geo_set_version: models.GeoSetVersion,
        assignments: dict[models.Geography, str],
        obj_meta: models.ObjectMeta,
        namespace: models.Namespace,
    ) -> Tuple[models.Plan, uuid.UUID]:
        """Creates a new districting plan."""
        # Check if you can create a plan at all
        plan_limit = (
            db.query(models.PlanLimit)
            .filter(
                models.PlanLimit.namespace_id == namespace.namespace_id,
                models.PlanLimit.layer_id == geo_set_version.layer.layer_id,
                models.PlanLimit.loc_id == geo_set_version.loc_id,
            )
            .first()
        )

        if plan_limit is None:
            with db.begin(nested=True):
                plan_limit = models.PlanLimit(
                    namespace_id=namespace.namespace_id,
                    layer_id=geo_set_version.layer.layer_id,
                    loc_id=geo_set_version.loc_id,
                )
                db.add(plan_limit)
                db.flush()
                db.refresh(plan_limit)

        current_plan_count = (
            db.query(models.Plan)
            .join(
                models.GeoSetVersion,
                models.Plan.set_version_id == models.GeoSetVersion.set_version_id,
            )
            .filter(
                models.Plan.namespace_id == namespace.namespace_id,
                models.GeoSetVersion.layer_id == geo_set_version.layer.layer_id,
                models.GeoSetVersion.loc_id == geo_set_version.loc_id,
            )
            .count()
        )

        log.debug(
            "Found %d plans in namespace %s for loc %s in layer %s",
            current_plan_count,
            namespace,
            geo_set_version.loc,
            geo_set_version.layer,
        )

        if current_plan_count >= plan_limit.max_plans:
            raise CreateValueError(
                "Failed to create a plan object. The maximum number of plans "
                f"({plan_limit.max_plans}) has already been reached for "
                f"locality {geo_set_version.loc.canonical_ref.path} in layer "
                f"{geo_set_version.layer.full_path}."
            )

        set_geo_ids = set(
            db.scalars(
                select(models.GeoSetMember.geo_id).filter(
                    models.GeoSetMember.set_version_id == geo_set_version.set_version_id,
                )
            )
        )
        assignment_geo_ids = set(geo.geo_id for geo in assignments)
        geo_ids_not_in_set = assignment_geo_ids - set_geo_ids
        if geo_ids_not_in_set:
            geos_not_in_set = [geo for geo in assignments if geo.geo_id in geo_ids_not_in_set]
            raise CreateValueError(
                "Some geographies in the assigment are not in the set defined by locality "
                f'"{geo_set_version.loc.canonical_ref.path}" and geographic layer '
                f'"{geo_set_version.layer.full_path}": '
                f"{', '.join(geo.full_path for geo in geos_not_in_set)}"
            )

        unassigned_geo_ids = set_geo_ids - assignment_geo_ids

        with db.begin(nested=True):
            plan = models.Plan(
                namespace_id=namespace.namespace_id,
                path=normalize_path(obj_in.path),
                set_version_id=geo_set_version.set_version_id,
                num_districts=len(set(assignments.values())),
                complete=(len(unassigned_geo_ids) == 0),
                description=obj_in.description,
                source_url=(str(obj_in.source_url) if obj_in.source_url is not None else None),
                districtr_id=obj_in.districtr_id,
                daves_id=obj_in.daves_id,
                meta_id=obj_meta.meta_id,
            )
            db.add(plan)

            try:
                db.flush()
            except exc.SQLAlchemyError:
                log.exception("Failed to create new districting plan.")
                raise CreateValueError(
                    "Failed to create canonical path to new districting plan. "
                    "(The path may already exist.)"
                )

            db.refresh(plan)
            copy_rows(
                db,
                table=f"{models.SCHEMA}.plan_assignment",
                columns=("plan_id", "geo_id", "assignment"),
                rows=(
                    (plan.plan_id, geo.geo_id, assignment)
                    for geo, assignment in assignments.items()
                ),
                quote_all=True,
            )
            etag = self._update_etag(db, namespace)

        return plan, etag

    def assignments_dict(self, db: Session, *, plan: models.Plan) -> dict[str, str | None]:
        """Full geography path -> assignment for a plan; unassigned members are None.

        Two column projections instead of walking the ORM graph: a state-scale
        plan has hundreds of thousands of assignment rows, and each ORM row
        would drag eager-joined geography, meta, and namespace with it.
        """
        ns_path = db.scalar(
            select(models.Namespace.path).where(
                models.Namespace.namespace_id == plan.set_version.namespace_id
            )
        )
        member_paths = db.scalars(
            select(models.Geography.path).join(
                models.GeoSetMember,
                models.GeoSetMember.geo_id == models.Geography.geo_id,
            ).where(models.GeoSetMember.set_version_id == plan.set_version_id)
        )
        assignment_rows = db.execute(
            select(models.Geography.path, models.PlanAssignment.assignment).join(
                models.PlanAssignment,
                models.PlanAssignment.geo_id == models.Geography.geo_id,
            ).where(models.PlanAssignment.plan_id == plan.plan_id)
        )
        result: dict[str, str | None] = {f"/{ns_path}/{path}": None for path in member_paths}
        result.update((f"/{ns_path}/{path}", assignment) for path, assignment in assignment_rows)
        return result

    def get(self, db: Session, *, path: str, namespace: models.Namespace) -> models.Plan | None:
        """Retrieves a districting plan by reference path.

        Args:
            path: Path to plan (namespace excluded).
            namespace: Plan's namespace.
        """
        return (
            db.query(models.Plan)
            .filter(
                models.Plan.namespace_id == namespace.namespace_id,
                models.Plan.path == normalize_path(path),
            )
            .first()
        )


plan = CRPlan(models.Plan)
