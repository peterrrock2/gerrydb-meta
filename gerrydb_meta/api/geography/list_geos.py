"""
This file contains a router that allows us to run some simpler queries on the
Geographies of a namespace without needing to either send or receive a full set of compressed
Geography binaries.

The main endpoint is /{namespace}/{loc_ref}/{layer} which returns a list of paths for the Geography
objects in the specified layer and locality. This has some query parameters that allow for a raw
return of the path, the path-hash pair, or a comparison of layers in two different namespaces.
"""

from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

import gerrydb_meta.models as models
from gerrydb_meta import crud
from gerrydb_meta.api.deps import (
    can_read_localities,
    get_db,
    get_scopes,
)
from gerrydb_meta.scopes import ScopeManager

list_router = APIRouter()


class GetMode(str, Enum):
    list_paths = "list_paths"
    path_hash_pair = "path_hash_pair"


def _get_path_hash_pairs(
    namespace: str, loc_ref: str, layer: str, db: Session, valid_at: datetime
) -> list[tuple[str, str]]:

    log.debug("Getting path hash pairs for %s %s %s", namespace, loc_ref, layer)
    query = (
        db.query(models.Geography.path, models.GeoBin.geometry_hash)
        .join(
            models.GeoSetMember,
            models.Geography.geo_id == models.GeoSetMember.geo_id,
        )
        .join(
            models.GeoSetVersion,
            models.GeoSetMember.set_version_id == models.GeoSetVersion.set_version_id,
        )
        .join(models.GeoVersion, models.Geography.geo_id == models.GeoVersion.geo_id)
        .join(
            models.GeoLayer,
            models.GeoSetVersion.layer_id == models.GeoLayer.layer_id,
        )
        .join(models.Locality, models.GeoSetVersion.loc_id == models.Locality.loc_id)
        .join(models.LocalityRef, models.LocalityRef.loc_id == models.Locality.loc_id)
        .join(
            models.Namespace,
            models.GeoLayer.namespace_id == models.Namespace.namespace_id,
        )
        .join(models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id)
        .filter(models.Namespace.path == namespace)
        .filter(models.GeoLayer.path == layer)
        .filter(models.LocalityRef.path == loc_ref)
        .filter(
            models.GeoVersion.valid_from <= valid_at,
            (
                or_(
                    models.GeoVersion.valid_to.is_(None),
                    models.GeoVersion.valid_to >= valid_at,
                )
            ),
        )
    )

    log.debug("Querying")
    log.debug(query)
    geo_objs = [(pair[0], pair[1].hex()) for pair in (query.all())]
    return geo_objs


def __get_paths(
    namespace: str, loc_ref: str, layer: str, db: Session, valid_at: datetime
) -> list[str]:
    log.debug("Getting paths")
    geo_objs = [
        obj[0]
        for obj in (
            db.query(
                models.Geography.path,
            )
            .join(
                models.GeoSetMember,
                models.Geography.geo_id == models.GeoSetMember.geo_id,
            )
            .join(
                models.GeoSetVersion,
                models.GeoSetMember.set_version_id == models.GeoSetVersion.set_version_id,
            )
            .join(models.GeoVersion, models.Geography.geo_id == models.GeoVersion.geo_id)
            .join(
                models.GeoLayer,
                models.GeoSetVersion.layer_id == models.GeoLayer.layer_id,
            )
            .join(models.Locality, models.GeoSetVersion.loc_id == models.Locality.loc_id)
            .join(models.LocalityRef, models.LocalityRef.loc_id == models.Locality.loc_id)
            .join(
                models.Namespace,
                models.GeoLayer.namespace_id == models.Namespace.namespace_id,
            )
            .join(models.GeoBin, models.GeoVersion.geo_bin_id == models.GeoBin.geo_bin_id)
            .filter(models.Namespace.path == namespace)
            .filter(models.GeoLayer.path == layer)
            .filter(models.LocalityRef.path == loc_ref)
            .filter(
                models.GeoVersion.valid_from <= valid_at,
                (
                    or_(
                        models.GeoVersion.valid_to.is_(None),
                        models.GeoVersion.valid_to > valid_at,
                    )
                ),
            )
            .all()
        )
    ]
    return geo_objs


@list_router.get(
    "/{namespace}/{loc_ref}/{layer}",
    response_model=None,
    dependencies=[Depends(can_read_localities)],
)
def all_paths(
    *,
    namespace: str,
    loc_ref: str,
    layer: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
    mode: GetMode = Query(default=GetMode.list_paths),
    valid_at: Annotated[Optional[datetime], Query] = None,
):
    if valid_at is None:
        valid_at = datetime.now(timezone.utc)

    log.debug("Getting all paths")
    view_namespace_obj = crud.namespace.get(db=db, path=namespace)

    log.debug("IN THE ALL PATHS WITH MODE %s", mode)
    if view_namespace_obj is None or not scopes.can_read_in_namespace(view_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read data in this namespace."
            ),
        )

    if mode == GetMode.list_paths:
        log.debug("Getting geo paths")
        return __get_paths(namespace, loc_ref, layer, db, valid_at)

    if mode == GetMode.path_hash_pair:
        log.debug("Getting geo path hash pair")
        return _get_path_hash_pairs(namespace, loc_ref, layer, db, valid_at)
