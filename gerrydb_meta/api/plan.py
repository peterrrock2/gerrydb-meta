"""Endpoints for districting plans."""

from http import HTTPStatus
from typing import Callable

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import (
    NamespacedObjectApi,
    add_etag,
    geo_set_from_paths,
    geos_from_paths,
)
from gerrydb_meta.api.deps import can_read_localities, get_db, get_obj_meta, get_scopes
from gerrydb_meta.scopes import ScopeManager


class PlanApi(NamespacedObjectApi):
    def _create(self, router: APIRouter) -> Callable:
        @router.post(
            "/{namespace}",
            response_model=self.get_schema,
            name=f"Create {self.obj_name_singular}",
            status_code=HTTPStatus.CREATED,
            dependencies=[Depends(can_read_localities)],
        )
        def create_route(
            *,
            response: Response,
            namespace: str,
            obj_in: schemas.PlanCreate,
            db: Session = Depends(get_db),
            obj_meta: models.ObjectMeta = Depends(get_obj_meta),
            scopes: ScopeManager = Depends(get_scopes),
        ):
            plan_namespace_obj = self._namespace_with_write(db=db, scopes=scopes, path=namespace)

            geo_set_version = geo_set_from_paths(
                locality=obj_in.locality,
                layer=obj_in.layer,
                namespace=namespace,
                db=db,
                scopes=scopes,
            )

            # Assemble geographies from assignment keys; verify that they exist
            # and are a subset of the geographies in the `GeoSetVersion`.
            plan_geo_paths = list(obj_in.assignments)
            plan_geos = geos_from_paths(
                paths=plan_geo_paths, namespace=namespace, db=db, scopes=scopes
            )
            plan_geo_assignments = dict(zip(plan_geos, obj_in.assignments.values()))
            # TODO: verify subset property.

            plan, etag = self.crud.create(
                db=db,
                obj_in=obj_in,
                geo_set_version=geo_set_version,
                assignments=plan_geo_assignments,
                obj_meta=obj_meta,
                namespace=plan_namespace_obj,
            )
            add_etag(response, etag)
            return schemas.Plan.from_attributes(plan)

        return create_route


router = PlanApi(
    crud=crud.plan,
    get_schema=schemas.Plan,
    create_schema=schemas.PlanCreate,
    obj_name_singular="Plan",
    obj_name_plural="Plans",
).router()
