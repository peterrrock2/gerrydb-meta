"""Column-specific API routes layered over the generic namespaced API."""

from http import HTTPStatus
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import NamespacedObjectApi, add_etag, namespace_write_error_msg
from gerrydb_meta.api.deps import get_db, get_obj_meta, get_scopes
from gerrydb_meta.exceptions import CreateValueError
from gerrydb_meta.scopes import ScopeManager


class ColumnApi(NamespacedObjectApi):
    """Adds `include_references` to the column listing.

    Plain listings show only columns the namespace owns. An un-materialized
    clone is a reference whose column lives in the source namespace, so
    listings-driven consumers (template builders) would silently skip it;
    the flag appends cross-namespace references labeled by their local path.
    """

    def _all(self, router: APIRouter) -> Callable:
        @router.get(
            "/{namespace}",
            response_model=list[schemas.Column],
            name=f"Read {self.obj_name_plural}",
        )
        def all_route(
            *,
            response: Response,
            namespace: str,
            limit: int | None = Query(default=None, ge=1),
            offset: int = Query(default=0, ge=0),
            include_references: bool = Query(default=False),
            db: Session = Depends(get_db),
            scopes: ScopeManager = Depends(get_scopes),
            if_none_match: str | None = Header(default=None),
        ):
            log.debug("IN GET ALL FOR COLUMNS")
            namespace_obj = self._namespace_with_read(db=db, scopes=scopes, path=namespace)
            etag = self._check_etag(db=db, namespace=namespace_obj, header=if_none_match)
            if self.list_hard_cap is not None:
                limit = min(limit or self.list_hard_cap, self.list_hard_cap)
            objs = self.crud.all_in_namespace(
                db=db, namespace=namespace_obj, limit=limit, offset=offset
            )
            results = [schemas.Column.from_attributes(obj) for obj in objs]
            if include_references:
                for ref in crud.column.cross_namespace_refs(db, namespace=namespace_obj):
                    resolved = schemas.Column.from_attributes(ref.column)
                    # Label by the LOCAL path: this is the name that template
                    # authors in this namespace address the column by. The
                    # metadata (kind/type/description) is the resolved
                    # column's.
                    results.append(
                        resolved.model_copy(
                            update={
                                "canonical_path": ref.path,
                                "namespace": namespace_obj.path,
                                "aliases": [],
                            }
                        )
                    )
            add_etag(response, etag)
            return results

        return all_route

    def _materialize(self, router: APIRouter) -> Callable:
        @router.post(
            "/{namespace}/{path:path}/materialize",
            response_model=schemas.Column,
            name="Materialize Column Reference",
        )
        def materialize_route(
            *,
            response: Response,
            namespace: str,
            path: str,
            db: Session = Depends(get_db),
            obj_meta: models.ObjectMeta = Depends(get_obj_meta),
            scopes: ScopeManager = Depends(get_scopes),
        ):
            """Materializes a cross-namespace reference into an owned column.

            Copies the source's current values onto same-path geographies in
            this namespace, then repoints the namespace's refs. Values are
            copied, so the caller must be able to read the source; existing
            template versions keep their pinned source column.
            """
            namespace_obj = crud.namespace.get(db=db, path=namespace)
            if namespace_obj is None or not scopes.can_write_in_namespace(namespace_obj):
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail=namespace_write_error_msg("columns"),
                )
            ref = crud.column.get_ref(db, path=path, namespace=namespace_obj)
            if ref is None or ref.column is None:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND, detail="Column reference not found."
                )
            source_ns = ref.column.namespace
            if source_ns.namespace_id != namespace_obj.namespace_id and not scopes.can_read_in_namespace(
                source_ns
            ):
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND, detail="Column reference not found."
                )
            try:
                col, etag = crud.column.materialize(db, ref=ref, obj_meta=obj_meta)
            except CreateValueError as ex:
                raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(ex))
            add_etag(response, etag)
            return schemas.Column.from_attributes(col)

        return materialize_route

    def router(self) -> APIRouter:
        router = super().router()
        self._materialize(router)
        return router
