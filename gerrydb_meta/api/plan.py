"""Endpoints for districting plans."""

from http import HTTPStatus
from typing import Callable

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import (
    NamespacedObjectApi,
    add_etag,
    geo_set_from_paths,
    geo_refs_from_paths,
)
from gerrydb_meta.api.deps import can_read_localities, get_db, get_obj_meta, get_scopes
from gerrydb_meta.scopes import ScopeManager


class PlanApi(NamespacedObjectApi):
    def _get(self, router: APIRouter) -> Callable:
        @router.get(
            "/{namespace}/{path:path}",
            response_model=schemas.Plan,
            name="Read Plan",
        )
        def get_route(
            *,
            response: Response,
            namespace: str,
            path: str,
            db: Session = Depends(get_db),
            scopes: ScopeManager = Depends(get_scopes),
            if_none_match: str | None = Header(default=None),
        ):
            namespace_obj = self._namespace_with_read(db=db, scopes=scopes, path=namespace)
            etag = self._check_etag(db=db, namespace=namespace_obj, header=if_none_match)
            plan = self._obj(db=db, namespace=namespace_obj, path=path)
            add_etag(response, etag)
            return schemas.Plan.from_attributes_with_assignments(
                plan, crud.plan.assignments_dict(db=db, plan=plan)
            )

        return get_route

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
            plan_geos = geo_refs_from_paths(
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
            return schemas.Plan.from_attributes_with_assignments(
                plan, crud.plan.assignments_dict(db=db, plan=plan)
            )

        return create_route


router = PlanApi(
    crud=crud.plan,
    get_schema=schemas.Plan,
    create_schema=schemas.PlanCreate,
    obj_name_singular="Plan",
    obj_name_plural="Plans",
    list_schema=schemas.PlanMeta,
).router()
