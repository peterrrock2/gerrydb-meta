"""API operations for manipulating column values."""

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import geos_from_paths, namespace_write_error_msg
from gerrydb_meta.api.deps import get_db, get_obj_meta, get_scopes
from gerrydb_meta.crud.base import normalize_path
from gerrydb_meta.scopes import ScopeManager

router = APIRouter()


@router.put(
    "/{namespace}/{path:path}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
)
def set_column_values(
    *,
    namespace: str,
    path: str,
    values: list[schemas.ColumnValue],
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
    scopes: ScopeManager = Depends(get_scopes),
):
    log.debug("IN THE PUT METHOD OF COLUMN VALUES")
    col_path = normalize_path(path)
    col_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if col_namespace_obj is None or not scopes.can_write_in_namespace(col_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=namespace_write_error_msg("column values"),
        )

    col = crud.column.get(db, path=col_path, namespace=col_namespace_obj)
    if col is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Column not found.")
    if col.namespace_id != col_namespace_obj.namespace_id:
        # The path resolved through a cross-namespace reference. References
        # are immutable aliases: writing through one would mutate the source
        # column with only the referencing namespace's write scope.
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=(
                f"'{col_path}' is a reference to a column in namespace "
                f"'{col.namespace.path}'; values cannot be written through a "
                "reference. Upload under a different column name to diverge."
            ),
        )

    geos = geos_from_paths(
        paths=[val.path for val in values], namespace=namespace, db=db, scopes=scopes
    )

    # Pair the geography objects with their values.
    geos_values = [(geo, val.value) for geo, val in zip(geos, values)]
    crud.column.set_values(db, col=col, values=geos_values, obj_meta=obj_meta)
