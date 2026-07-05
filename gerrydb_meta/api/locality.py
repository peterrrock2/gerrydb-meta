"""Endpoints for locality metadata."""

from http import HTTPStatus

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import add_etag, check_etag
from gerrydb_meta.api.deps import (
    can_read_localities,
    can_write_localities,
    get_db,
    get_obj_meta,
)

router = APIRouter()


@router.get(
    "/",
    response_model=list[schemas.Locality],
    dependencies=[Depends(can_read_localities)],
)
def read_localities(
    *,
    response: Response,
    db: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None),
) -> list[schemas.Locality]:
    etag = check_etag(db=db, crud_obj=crud.locality, header=if_none_match)
    add_etag(response, etag)
    objs = crud.locality.all(db=db)
    return [schemas.Locality.from_attributes(obj) for obj in objs]


@router.get(
    "/{path:path}",
    response_model=schemas.Locality,
    dependencies=[Depends(can_read_localities)],
)
def read_locality(
    *,
    path: str,
    response: Response,
    db: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None),
) -> schemas.Locality:
    loc = crud.locality.get_by_ref(db=db, path=path)
    if loc is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Locality not found.")

    etag = check_etag(db=db, crud_obj=crud.locality, header=if_none_match)

    # Aliases serve the canonical body directly. The old 308 redirect built
    # its URL with str.replace on the whole request URL, which corrupted any
    # URL where the alias string also appeared elsewhere (an alias like "ca"
    # rewrote the "ca" inside "localhost"), and clients handled the redirect
    # inconsistently.
    add_etag(response, etag)
    return schemas.Locality.from_attributes(loc)


@router.patch(
    "/{path:path}",
    response_model=schemas.Locality,
    dependencies=[Depends(can_write_localities)],
)
def patch_locality(
    *,
    response: Response,
    path: str,
    loc_patch: schemas.LocalityPatch,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
) -> schemas.Locality:
    loc = crud.locality.get_by_ref(db=db, path=path)
    if loc is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Locality not found.")
    patched, etag = crud.locality.patch(db=db, obj=loc, obj_meta=obj_meta, patch=loc_patch)
    add_etag(response, etag)
    return schemas.Locality.from_attributes(patched)


@router.post(
    "/",
    response_model=list[schemas.Locality],
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_write_localities)],
)
def create_localities(
    *,
    response: Response,
    locs_in: list[schemas.LocalityCreate],
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
) -> list[schemas.Locality]:
    locs, etag = crud.locality.create_bulk(db=db, objs_in=locs_in, obj_meta=obj_meta)
    add_etag(response, etag)
    return [schemas.Locality.from_attributes(loc) for loc in locs]
