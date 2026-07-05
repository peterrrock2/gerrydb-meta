"""Endpoints for namespace metadata."""

from http import HTTPStatus

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import add_etag, check_etag
from gerrydb_meta.api.deps import (
    can_create_namespace,
    get_db,
    get_obj_meta,
    get_scopes,
)
from gerrydb_meta.scopes import ScopeManager

router = APIRouter()


@router.get("/", response_model=list[schemas.Namespace])
def read_namespaces(
    *,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
) -> list[schemas.Namespace]:
    return [
        schemas.Namespace.from_attributes(namespace)
        for namespace in crud.namespace.all(db=db)
        if scopes.can_read_in_namespace(namespace)
    ]


@router.get("/{namespace}", response_model=schemas.Namespace)
def read_namespace(
    *,
    response: Response,
    namespace: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
    if_none_match: str | None = Header(default=None),
) -> schemas.Namespace:
    namespace_obj = crud.namespace.get(db=db, path=namespace)

    if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                "Namespace not found, or you do not have sufficient "
                "permissions to access this namespace."
            ),
        )

    etag = check_etag(db=db, crud_obj=crud.namespace, header=if_none_match)
    add_etag(response, etag)
    return schemas.Namespace.from_attributes(namespace_obj)


@router.post(
    "/",
    response_model=schemas.Namespace,
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_create_namespace)],
)
def create_namespace(
    *,
    response: Response,
    loc_in: schemas.NamespaceCreate,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
) -> schemas.Namespace:
    namespace, etag = crud.namespace.create(db=db, obj_in=loc_in, obj_meta=obj_meta)
    add_etag(response, etag)

    return schemas.Namespace.from_attributes(namespace)
