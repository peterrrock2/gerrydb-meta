import hashlib
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import WKBElement
from shapely import Polygon
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

import gerrydb_meta.models as models
import gerrydb_meta.schemas as schemas
from gerrydb_meta import crud
from gerrydb_meta.api.deps import (
    can_read_localities,
    get_db,
    get_scopes,
    get_user,
)
from gerrydb_meta.scopes import ScopeManager

from .list_geos import _get_path_hash_pairs

fork_router = APIRouter()


def __validate_source_and_target_namespaces(
    source_namespace: str, target_namespace: str, db: Session, scopes: ScopeManager
):
    """
    Validates that the user can fork between namespaces. Specifically, this function
    checks to make sure that the user has read permissions in the source namespace
    and write permissions in the target namespace.

    Args:
        source_namespace: The namespace of the source layer.
        target_namespace: The namespace of the target layer.
        db: The database session.
        scopes: The authorization context.

    Returns:
        None

    Raises:
        HTTPException: If the source or target namespaces are not found or the user
            does not have sufficient permissions to read or write in the namespaces.
    """
    source_namespace_obj = crud.namespace.get(db=db, path=source_namespace)

    if source_namespace_obj is None or not scopes.can_read_in_namespace(source_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{source_namespace}" not found, or you do not have '
                "sufficient permissions to read geometries in this namespace."
            ),
        )

    target_namespace_obj = crud.namespace.get(db=db, path=target_namespace)

    # We enforce that the target namespace is writeable, because the only
    # reason that you would want to check if you can fork from one namespace
    # to another is to check if you can write new things to the target namespace.
    if target_namespace_obj is None or not scopes.can_write_in_namespace(target_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{target_namespace}" not found, or you do not have '
                "sufficient permissions to write geometries in this namespace."
            ),
        )

    return source_namespace_obj, target_namespace_obj


def __validate_forkability(
    source_namespace: str,
    source_layer: str,
    target_namespace: str,
    target_layer: str,
    source_geo_hash_pairs: set[tuple[str, str]],
    target_geo_hash_pairs: set[tuple[str, str]],
    allow_extra_source_geos: bool = False,
    allow_empty_polys: bool = False,
):
    """
    Checks whether or not the data in the source namespace/layer can be 'forked' to the
    target namespace/layer. In order for data to be 'forkable' we require that all geometries
    that exist in the target namespace/layer are identical to the geometries in the source
    namespace/layer that share the same path relative to the namespace. We do not make any
    assumptions about whether or not the source namespace/layer contains geometries that have
    not been previously added to the target namespace/layer, and instead require that the
    function caller explicitly determine what should be done in this case (error or allow).
    The function will also raise an error when forking data from a source layer that contains
    empty geometries and `allow_empty_polys` is `False` because the user will generally want
    meaningful geometries to be attached to the data that they are working with.

    Args:
        source_namespace: The namespace of the source layer.
        source_layer: The path of the source layer.
        target_namespace: The namespace of the target layer.
        target_layer: The path of the target layer.
        source_geo_hash_pairs: The set of (path, hash) pairs of the source layer.
        target_geo_hash_pairs: The set of (path, hash) pairs of the target layer.
        allow_extra_source_geos: Whether or not to allow for the source layer to contain
            geometries that are not present in the target layer.
        allow_empty_polys: Whether or not to allow for the source layer to contain empty
            polygons that will be forked over to the target layer.

    Returns:
        None

    Raises:
        HTTPException: If the source and target layers are not forkable.
    """
    empty_polygon_wkb = Polygon().wkb
    empty_hash = hashlib.md5(WKBElement(empty_polygon_wkb, srid=4269).data).hexdigest()

    log.debug("Comparing geo path hash pairs")
    if len(source_geo_hash_pairs) == 0 and len(target_geo_hash_pairs) == 0:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in "
                f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
                f"both the source and target layers do not contain any geographies."
            ),
        )

    # This should never happen, but it's possible if the source and target namespaces
    # get switched on accident.
    if len(source_geo_hash_pairs) == 0:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in "
                f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
                f"the source layer does not contain any geographies. Please check to make sure "
                f"that the source and target namespaces are correct."
            ),
        )

    if not allow_empty_polys and any([pair[1] == empty_hash for pair in source_geo_hash_pairs]):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in "
                f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
                f"some of the source geographies have empty polygons and `allow_empty_polys` "
                f"is False."
            ),
        )

    if source_geo_hash_pairs == target_geo_hash_pairs:
        return

    diff_ts = target_geo_hash_pairs - source_geo_hash_pairs
    diff_st = source_geo_hash_pairs - target_geo_hash_pairs
    if len(diff_st) > 0 and len(diff_ts) > 0:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
                f"to layer '{target_layer}' in '{target_namespace}' because some "
                f"geometries in the target namespace/layer are different from the geometries "
                f"in the source namespace/layer. Forking should only be used when attempting "
                f"to add geometries from the source namespace/layer that were not previously "
                f"present in the target namespace/layer to the target namespace/layer."
            ),
        )
    if len(diff_ts) > 0:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
                f"to layer '{target_layer}' in '{target_namespace}' because some "
                f"geometries in the target namespace/layer are not present in the "
                f"source namespace/layer."
            ),
        )

    if not allow_extra_source_geos and len(diff_st) > 0:
        if len(target_geo_hash_pairs) == 0:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail=(
                    f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
                    f"to layer '{target_layer}' in '{target_namespace}' because "
                    f"no geometries are present in the target namespace/layer and the parameter "
                    f"`allow_extra_source_geos` was not passed as `True`."
                ),
            )

        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=(
                f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' to layer "
                f"'{target_layer}' in '{target_namespace}' because some geometries in the source "
                f"namespace/layer are not present in the target namespace/layer and the "
                f"parameter `allow_extra_source_geos` was not passed as `True`."
            ),
        )


@fork_router.get(
    "/{target_namespace}/{loc_ref}/{target_layer}",
    response_model=None,
    dependencies=[Depends(can_read_localities)],
)
def check_forkability(
    target_namespace: str,
    loc_ref: str,
    target_layer: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
    source_namespace: Optional[str] = Query(default=None),
    source_layer: Optional[str] = Query(default=None),
    allow_extra_source_geos: bool = Query(default=False),
    allow_empty_polys: bool = Query(default=False),
    return_target_hashes: bool = Query(default=False),
):
    """
    Checks whether or not the data in the source namespace/layer can be 'forked' to the
    target namespace/layer. In order for data to be 'forkable' we require that all geometries
    that exist in the target namespace/layer are identical to the geometries in the source
    namespace/layer that share the same path relative to the namespace. We do not make any
    assumptions about whether or not the source namespace/layer contains geometries that have
    not been previously added to the target namespace/layer, and instead require that the
    function caller explicitly determine what should be done in this case (error or allow).
    The function will also raise an error when forking data from a source layer that contains
    empty geometries and `allow_empty_polys` is `False` because the user will generally want
    meaningful geometries to be attached to the data that they are working with.

    Note: The locality of the source and target namespace/layer pairs must be the same.

    Args:
        target_namespace: The namespace of the target layer.
        loc_ref: The path of the locality to be forked.
        target_layer: The path of the target layer.
        source_namespace: The namespace of the source layer.
        source_layer: The path of the source layer.
        source_geo_hash_pairs: The set of (path, hash) pairs of the source layer.
        target_geo_hash_pairs: The set of (path, hash) pairs of the target layer.
        allow_extra_source_geos: Whether or not to allow for the source layer to contain
            geometries that are not present in the target layer.
        allow_empty_polys: Whether or not to allow for the source layer to contain empty
            polygons that will be forked over to the target layer.

    Returns:
        list[Tuple[str, str]]: A list of (path, hash) pairs of the source layer.

    Raises:
        HTTPException: If the source and target layers are not forkable.
    """
    (
        source_namespace_obj,
        target_namespace_obj,
    ) = __validate_source_and_target_namespaces(source_namespace, target_namespace, db, scopes)

    locality = crud.locality.get_by_ref(db=db, path=loc_ref)
    layer = crud.geo_layer.get(db=db, path=target_layer, namespace=target_namespace_obj)

    if locality is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(f"Locality '{loc_ref}' not found in namespace '{target_namespace}'."),
        )

    if layer is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(f"Layer '{target_layer}' not found in namespace '{target_namespace}'."),
        )

    # Now check that you are migrating from a public namespace.
    # At this point, the user has already shown that they have read access to
    # the source namespace, so we can give them information about that namespace
    # NOTE: We do not allow for migration from private namespaces to help prevent
    # leaking protected data to other users of the target namespace.
    if not source_namespace_obj.public:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=(
                f"Namespace '{source_namespace}' is not public, so you cannot fork "
                "values or geographies from it."
            ),
        )

    valid_at = datetime.now(timezone.utc)

    source_geo_hash_pairs = set(
        _get_path_hash_pairs(
            namespace=source_namespace,
            loc_ref=loc_ref,
            layer=source_layer,
            db=db,
            valid_at=valid_at,
        )
    )
    target_geo_hash_pairs = set(
        _get_path_hash_pairs(
            namespace=target_namespace,
            loc_ref=loc_ref,
            layer=target_layer,
            db=db,
            valid_at=valid_at,
        )
    )

    _ = __validate_forkability(
        source_namespace=source_namespace,
        source_layer=source_layer,
        target_namespace=target_namespace,
        target_layer=target_layer,
        source_geo_hash_pairs=source_geo_hash_pairs,
        target_geo_hash_pairs=target_geo_hash_pairs,
        allow_extra_source_geos=allow_extra_source_geos,
        allow_empty_polys=allow_empty_polys,
    )

    if return_target_hashes:
        return source_geo_hash_pairs, target_geo_hash_pairs

    return source_geo_hash_pairs  # pragma: no cover


@fork_router.post(
    "/{target_namespace}/{loc_ref}/{target_layer}",
    response_model=None,
    dependencies=[Depends(can_read_localities)],
)
def fork_geos_between_namespaces(
    *,
    target_namespace: str,
    loc_ref: str,
    target_layer: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_user),
    scopes: ScopeManager = Depends(get_scopes),
    source_namespace: Optional[str] = Query(default=None),
    source_layer: Optional[str] = Query(default=None),
    allow_extra_source_geos: bool = Query(default=False),
    allow_empty_polys: bool = Query(default=False),
    notes: str = Query(default="THERE ARE NO NOTES"),
):
    log.debug("Checking if forking is possible")

    source_geo_hash_pairs, target_geo_hash_pairs = check_forkability(
        target_namespace=target_namespace,
        loc_ref=loc_ref,
        target_layer=target_layer,
        db=db,
        scopes=scopes,
        source_namespace=source_namespace,
        source_layer=source_layer,
        allow_extra_source_geos=allow_extra_source_geos,
        allow_empty_polys=allow_empty_polys,
        return_target_hashes=True,
    )

    # We are doing some double work here, but it's not a big deal because
    # getting namespaces, localities, and layers is fast in the DB.
    (
        source_namespace_obj,
        target_namespace_obj,
    ) = __validate_source_and_target_namespaces(source_namespace, target_namespace, db, scopes)

    locality = crud.locality.get_by_ref(db=db, path=loc_ref)
    layer = crud.geo_layer.get(db=db, path=target_layer, namespace=target_namespace_obj)

    # We are now guaranteed that the missing paths do not have a conflicting
    # geography in the target namespace.

    create_geos_path_hash = source_geo_hash_pairs - target_geo_hash_pairs
    if not create_geos_path_hash:
        # Everything already exists in the target (e.g. a re-run against a
        # layer a previous load forked): forking zero geographies must be a
        # no-op, not a bulk insert of zero rows.
        log.debug("Nothing to fork; target already has all source geographies")
        return []

    log.debug("Forking the geos")

    if notes == "THERE ARE NO NOTES":
        notes = (
            f"Forked {len(source_geo_hash_pairs)} geographies from "
            f"{source_namespace}/{loc_ref}/{source_layer} to "
            f"{target_namespace}/{loc_ref}/{target_layer} "
            f"by a direct call to the API."
        )

    schema_meta_obj = schemas.ObjectMetaCreate(notes=notes)
    meta_obj = crud.obj_meta.create(db=db, obj_in=schema_meta_obj, user=user)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta_obj, namespace=target_namespace_obj)

    geo_ret = crud.geography.fork_bulk(
        db=db,
        source_namespace=source_namespace_obj,
        target_namespace=target_namespace_obj,
        create_geos_path_hash=create_geos_path_hash,
        geo_import=geo_import,
        obj_meta=meta_obj,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=layer,
        locality=locality,
        geographies=[item[0] for item in geo_ret[0]],
        obj_meta=meta_obj,
    )

    # ORM objects don't JSON-encode (raw WKBElement columns); the client only
    # checks the status code, so return the forked paths.
    return [geo.path for geo, _version in geo_ret[0]]
