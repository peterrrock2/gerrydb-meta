"""Endpoints for view templates."""

from http import HTTPStatus
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import NamespacedObjectApi, add_etag, from_resource_paths
from gerrydb_meta.api.deps import get_db, get_obj_meta, get_scopes
from gerrydb_meta.scopes import ScopeManager

MAX_VIEW_TEMPLATE_COLUMNS = 100


class ViewTemplateApi(NamespacedObjectApi):
    def _check_public(self, scopes: ScopeManager) -> None:
        """Checks read access to public namespaces."""
        if not scopes.can_read_in_public_namespaces():
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=("Cannot read in public namespaces (required for view template access)."),
            )

    def _namespace_with_read(
        self, *, db: Session, scopes: ScopeManager, path: str
    ) -> models.Namespace:
        """Loads a namespace with read access or raises an HTTP error.

        Also verifies read access to all public namespaces.
        """
        self._check_public(scopes)
        return super()._namespace_with_read(db=db, scopes=scopes, path=path)

    def _namespace_with_write(
        self, *, db: Session, scopes: ScopeManager, path: str
    ) -> models.Namespace:
        """Loads a namespace write read access or raises an HTTP error.

        Also verifies read access to all public namespaces.
        """
        self._check_public(scopes)
        return super()._namespace_with_write(db=db, scopes=scopes, path=path)

    def _create(self, router: APIRouter) -> Callable:
        @router.post(
            "/{namespace}",
            response_model=self.get_schema,
            name=f"Create {self.obj_name_singular}",
            status_code=HTTPStatus.CREATED,
        )
        def create_route(
            *,
            response: Response,
            namespace: str,
            obj_in: schemas.ViewTemplateCreate,
            db: Session = Depends(get_db),
            obj_meta: models.ObjectMeta = Depends(get_obj_meta),
            scopes: ScopeManager = Depends(get_scopes),
        ):
            log.debug("TOP OF CREATE VIEW TEMPLATE")
            namespace_obj = self._namespace_with_write(db=db, scopes=scopes, path=namespace)
            resolved_objs = from_resource_paths(
                paths=obj_in.members, db=db, scopes=scopes, follow_refs=False
            )

            total_objs = 0
            for item in resolved_objs:
                if isinstance(item, models.ColumnSet):
                    total_objs += len(item.columns)
                else:
                    total_objs += 1

            if total_objs > MAX_VIEW_TEMPLATE_COLUMNS:
                log.error(
                    f"Cannot create view template with more than {MAX_VIEW_TEMPLATE_COLUMNS} columns."
                )
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail=(
                        f"Maximum view template column count exceeded. Found {total_objs} columns. "
                        f"Maximum is {MAX_VIEW_TEMPLATE_COLUMNS}."
                    ),
                )

            template_obj, etag = self.crud.create(
                db=db,
                obj_in=obj_in,
                resolved_members=resolved_objs,
                obj_meta=obj_meta,
                namespace=namespace_obj,
            )
            add_etag(response, etag)
            return schemas.ViewTemplate.from_attributes(template_obj)

        return create_route

    # TODO: _patch()?


router = ViewTemplateApi(
    crud=crud.view_template,
    get_schema=schemas.ViewTemplate,
    create_schema=schemas.ViewTemplateCreate,
    patch_schema=schemas.ViewTemplatePatch,
    obj_name_singular="ViewTemplate",
    obj_name_plural="ViewTemplates",
).router()
