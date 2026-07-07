"""API operations for duplicate-column detection and column references."""

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import namespace_write_error_msg
from gerrydb_meta.api.deps import get_db, get_obj_meta, get_scopes
from gerrydb_meta.exceptions import CreateValueError
from gerrydb_meta.scopes import ScopeManager

router = APIRouter()


def _readable_namespace_ids(db: Session, scopes: ScopeManager) -> list[int]:
    return [
        ns.namespace_id
        for ns in db.query(models.Namespace).all()
        if scopes.can_read_in_namespace(ns)
    ]


@router.post("/{namespace}/preflight", response_model=schemas.ColumnPreflightResponse)
def preflight_columns(
    *,
    namespace: str,
    body: schemas.ColumnPreflightRequest,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
):
    """Reports which candidate columns' content already exists in a readable
    namespace under the same name/alias and (locality, layer) context."""
    namespace_obj = crud.namespace.get(db=db, path=namespace)
    if namespace_obj is None or not scopes.can_write_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=namespace_write_error_msg("column preflight"),
        )
    readable = _readable_namespace_ids(db, scopes)
    matches = crud.column.find_duplicates(
        db,
        candidates=[
            {
                "name": cand.name,
                "locality": cand.locality,
                "layer": cand.layer,
                "hash_hi": cand.hash_hi,
                "hash_lo": cand.hash_lo,
            }
            for cand in body.candidates
        ],
        readable_namespace_ids=readable,
        # Deterministic tie-break: a same-namespace duplicate beats any
        # cross-namespace one.
        preferred_namespace_id=namespace_obj.namespace_id,
    )
    results = [
        schemas.ColumnDuplicateMatch(
            name=cand.name,
            namespace=None if col is None else col.namespace.path,
            path=None if col is None else col.canonical_ref.path,
        )
        for cand, col in zip(body.candidates, matches)
    ]
    return schemas.ColumnPreflightResponse(results=results)


@router.post("/{namespace}", status_code=HTTPStatus.CREATED)
def create_column_reference(
    *,
    namespace: str,
    body: schemas.ColumnReferenceCreate,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
    scopes: ScopeManager = Depends(get_scopes),
):
    """Creates a reference to an existing column in the caller's namespace.

    References may only target columns in public namespaces (or the caller's
    own), so private data can never be reachable through a reference.
    """
    namespace_obj = crud.namespace.get(db=db, path=namespace)
    if namespace_obj is None or not scopes.can_write_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=namespace_write_error_msg("column references"),
        )
    target_ns = crud.namespace.get(db=db, path=body.target_namespace)
    if target_ns is None or not scopes.can_read_in_namespace(target_ns):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Target namespace not found.")
    col = crud.column.get(db, path=body.target_path, namespace=target_ns)
    if col is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Target column not found.")
    if body.validate_paths:
        missing = crud.column.missing_value_paths(db, col=col, namespace=namespace_obj)
        if missing:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail=(
                    f"Target column has current values on geography paths missing "
                    f"from namespace '{namespace_obj.path}' (sample: {missing})."
                ),
            )
    try:
        crud.column.create_reference(
            db, path=body.path, namespace=namespace_obj, col=col, obj_meta=obj_meta
        )
    except CreateValueError as ex:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(ex))
    return {
        "path": body.path,
        "target_namespace": target_ns.path,
        "target_path": col.canonical_ref.path,
    }
