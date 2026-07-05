"""API endpoints for `GeoSets`, which are managed through `GeoLayers`.

A `GeoSet` defines a `GeoLayer` on a `Locality`.
"""

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import geo_refs_from_paths, namespace_write_error_msg
from gerrydb_meta.api.deps import can_read_localities, get_db, get_obj_meta, get_scopes
from gerrydb_meta.crud.base import normalize_path
from gerrydb_meta.scopes import ScopeManager

router = APIRouter()


@router.put(
    "/{namespace}/{path:path}",
    response_model=None,
    name="Map Locality to GeoLayer",
    status_code=HTTPStatus.NO_CONTENT,
    dependencies=[Depends(can_read_localities)],
)
def map_locality(
    *,
    namespace: str,
    path: str,
    locality: str,
    geographies: schemas.GeoSetCreate,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
    scopes: ScopeManager = Depends(get_scopes),
):
    log.debug("TOP OF MAP LOCALITY")
    layer_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if layer_namespace_obj is None or not scopes.can_write_in_namespace(layer_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=namespace_write_error_msg("geographic layers"),
        )

    loc_obj = crud.locality.get_by_ref(db, path=normalize_path(locality))
    if loc_obj is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Locality not found.")

    geo_objs = geo_refs_from_paths(
        paths=geographies.paths, namespace=namespace, db=db, scopes=scopes
    )

    layer_obj = crud.geo_layer.get(db=db, path=path, namespace=layer_namespace_obj)
    if layer_obj is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Geographic layer not found.")

    log.debug("Mapping locality %s to layer %s", loc_obj, layer_obj)

    crud.geo_layer.map_locality(
        db=db,
        layer=layer_obj,
        locality=loc_obj,
        geographies=geo_objs,
        obj_meta=obj_meta,
    )
