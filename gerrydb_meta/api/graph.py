"""Endpoints for districting graphs."""

import os
import subprocess
import time
from datetime import timedelta
from http import HTTPStatus
from typing import Union
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import storage
from google.oauth2.service_account import Credentials
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api import render_cache
from gerrydb_meta.api.base import (
    add_etag,
    geo_set_from_paths,
    geo_refs_from_paths,
)
from gerrydb_meta.api.deps import (
    can_read_localities,
    get_db,
    get_obj_meta,
    get_ogr2ogr_db_config,
    get_scopes,
    get_user,
)
from gerrydb_meta.render import graph_to_gpkg
from gerrydb_meta.scopes import ScopeManager

GPKG_MEDIA_TYPE = "application/geopackage+sqlite3"


router = APIRouter()


@router.post(
    "/{namespace}",
    response_model=Union[schemas.Graph, schemas.GraphMeta],
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_read_localities)],
)
def create_graph(
    *,
    response: Response,
    namespace: str,
    obj_in: schemas.GraphCreate,
    include_edges: bool = False,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
    scopes: ScopeManager = Depends(get_scopes),
) -> Union[schemas.Graph, schemas.GraphMeta]:
    log.debug("TOP OF API CREATE GRAPH")
    start = time.perf_counter()
    namespace_obj = crud.namespace.get(db=db, path=namespace)

    if namespace_obj is None or not scopes.can_write_derived_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read data in this namespace."
            ),
        )
    log.debug("Time to get namespace: %s", time.perf_counter() - start)
    start = time.perf_counter()

    # This will raise the relevent errors if the locality or layer are not found.
    geo_set_version = geo_set_from_paths(
        locality=obj_in.locality,
        layer=obj_in.layer,
        namespace=namespace,
        db=db,
        scopes=scopes,
    )

    log.debug("Time to get geo set version: %s", time.perf_counter() - start)
    start = time.perf_counter()
    # Assemble geographies from edges; verify that they exist
    # and are a subset of the geographies in the `GeoSetVersion`.
    edge_geo_paths = list(
        set(edge[0] for edge in obj_in.edges) | set(edge[1] for edge in obj_in.edges)
    )
    edge_geos = geo_refs_from_paths(
        paths=edge_geo_paths, namespace=namespace, db=db, scopes=scopes
    )
    edge_geos_by_path = dict(zip(edge_geo_paths, edge_geos))

    log.debug("Time to get edge_geos: %s", time.perf_counter() - start)
    start = time.perf_counter()

    graph, etag = crud.graph.create(
        db=db,
        obj_in=obj_in,
        geo_set_version=geo_set_version,
        edge_geos=edge_geos_by_path,
        obj_meta=obj_meta,
        namespace=namespace_obj,
    )
    log.debug("Time to create graph: %s", time.perf_counter() - start)
    add_etag(response, etag)
    if include_edges:
        # Echoing every edge back is expensive for large graphs (it reloads
        # the edge rows and both geographies per edge); bulk imports pass
        # include_edges=false to get metadata only.
        return schemas.Graph.from_attributes(graph)
    return schemas.GraphMeta.from_attributes(graph)


@router.get(
    "/{namespace}",
    response_model=list[schemas.GraphMeta],
    dependencies=[Depends(can_read_localities)],
)
def all_graphs(
    *,
    response: Response,
    namespace: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
):
    graph_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if graph_namespace_obj is None or not scopes.can_read_in_namespace(graph_namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read data in this namespace."
            ),
        )
    graph_objs = crud.graph.all(db=db, namespace=graph_namespace_obj)
    etag = crud.graph.etag(db, graph_namespace_obj)
    add_etag(response, etag)
    return [schemas.GraphMeta.from_attributes(graph_obj) for graph_obj in graph_objs]


@router.get(
    "/{namespace}/{path:path}",
    response_model=schemas.GraphMeta,
    dependencies=[Depends(can_read_localities)],
)
def get_graph(
    *,
    response: Response,
    namespace: str,
    path: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
):
    """
    Returns a GraphMeta object containing information about a graph, but not the
    graph itself.
    """
    log.debug("TOP OF API GET GRAPH")
    start = time.perf_counter()

    namespace_obj = crud.namespace.get(db=db, path=namespace)
    if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read data in this namespace."
            ),
        )
    log.debug("Time to get namespace: %s", time.perf_counter() - start)
    start = time.perf_counter()

    graph_obj = crud.graph.get(db=db, path=path, namespace=namespace_obj)
    if graph_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"Graph not found in namespace.",
        )

    etag = crud.graph.etag(db, namespace_obj)
    add_etag(response, etag)
    return schemas.GraphMeta.from_attributes(graph_obj)


@router.post(
    "/{namespace}/{path:path}",
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_read_localities)],
    response_class=FileResponse,
)
def render_graph(
    *,
    namespace: str,
    path: str,
    db: Session = Depends(get_db),
    db_config: str = Depends(get_ogr2ogr_db_config),
    user: models.User = Depends(get_user),
    scopes: ScopeManager = Depends(get_scopes),
):
    log.debug("TOP OF GRAPH RENDER")
    namespace_obj = crud.namespace.get(db=db, path=namespace)
    if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read data in this namespace."
            ),
        )

    graph_obj = crud.graph.get(db=db, path=path, namespace=namespace_obj)
    if graph_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"Graph not found in namespace.",
        )
    etag = crud.graph.etag(db, namespace_obj)

    bucket_name = os.getenv("GCS_BUCKET")
    key_path = os.getenv("GCS_KEY_PATH")
    storage_credentials = storage_client = None
    if bucket_name is not None and key_path is not None:  # pragma: no cover
        try:
            storage_credentials = Credentials.from_service_account_file(key_path)
            storage_client = storage.Client(credentials=storage_credentials)
        except (GoogleAuthError, OSError, ValueError):
            log.exception("Failed to initialize Google Cloud Storage context.")
            storage_credentials = storage_client = None
    has_gcs_context = storage_client is not None

    cached_render_meta = crud.graph.get_cached_render(db=db, graph=graph_obj)
    if cached_render_meta is not None and not has_gcs_context:
        cached_path = render_cache.cached_file(cached_render_meta.path)
        if cached_path is not None:
            log.debug("Serving graph render from the local cache.")
            return FileResponse(
                cached_path,
                media_type=GPKG_MEDIA_TYPE,
                headers={
                    "ETag": etag.hex,
                    "X-GerryDB-Graph-Render-ID": cached_render_meta.render_id.hex,
                    "Content-Encoding": "identity",
                },
            )
    if cached_render_meta is not None and has_gcs_context:  # pragma: no cover
        log.debug("Found cached render")
        render_path = urlparse(cached_render_meta.path)
        try:
            bucket = storage_client.bucket(render_path.netloc)
            blob = bucket.get_blob(render_path.path[1:])
            if blob is None:
                raise FileNotFoundError(
                    f"Cached graph render not found in bucket: {render_path.path[1:]}"
                )
            redirect_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=15),
                method="GET",
                # see https://stackoverflow.com/a/64245028
                service_account_email=storage_credentials.service_account_email,
                access_token=storage_credentials.token,
            )
            return RedirectResponse(
                url=redirect_url,
                status_code=HTTPStatus.PERMANENT_REDIRECT,
            )
        except (GoogleAPIError, GoogleAuthError, OSError, ValueError):
            log.exception(
                "Failed to serve rendered graph via Google Cloud Storage. "
                "Falling back to direct streaming."
            )

    log.debug("BEFORE GRAPH RENDER")
    start = time.perf_counter()
    render_ctx = crud.graph.render(db=db, graph=graph_obj)
    # ogr2ogr connects separately: the materialized render table must be
    # committed before it runs.
    db.commit()
    log.debug("Time to render graph: %s", time.perf_counter() - start)
    start = time.perf_counter()
    try:
        render_uuid, gpkg_path = graph_to_gpkg(context=render_ctx, db_config=db_config)
    finally:
        # The GeoPackage owns the data now. If the drop is skipped (e.g. the
        # process dies mid-render), `admin.py render:sweep` collects orphans.
        try:
            db.execute(sql_text(f"DROP TABLE IF EXISTS {render_ctx.render_table}"))
            db.commit()
        except Exception:
            log.exception("Failed to drop render table %s.", render_ctx.render_table)
    log.debug("Time to write GPKG: %s", time.perf_counter() - start)
    log.debug("Created GPKG %s", gpkg_path)

    if has_gcs_context:  # pragma: no cover
        log.debug("Attempting to upload rendered graph to Google Cloud Storage")
        try:
            bucket = storage_client.bucket(bucket_name)
            gzipped_path = gpkg_path.with_suffix(".gpkg.gz")
            subprocess.run(["gzip", "-k", "-1", str(gpkg_path)], check=True)

            blob_path = f"{render_uuid.hex}.gpkg.gz"
            blob = bucket.blob(blob_path)
            blob.content_encoding = "gzip"
            blob.metadata = {"gerrydb-graph-render-id": render_uuid.hex}
            blob.upload_from_filename(gzipped_path, content_type=GPKG_MEDIA_TYPE)
            crud.graph.cache_render(
                db=db,
                graph=graph_obj,
                created_by=user,
                render_id=render_uuid,
                path=f"gs://{bucket_name}/{blob_path}",
            )

            redirect_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=15),
                method="GET",
                # see https://stackoverflow.com/a/64245028
                service_account_email=storage_credentials.service_account_email,
                access_token=storage_credentials.token,
            )
            return RedirectResponse(
                url=redirect_url,
                status_code=HTTPStatus.PERMANENT_REDIRECT,
            )
        except (
            GoogleAPIError,
            GoogleAuthError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ):
            log.exception(
                "Failed to serve rendered graph via Google Cloud Storage. "
                "Falling back to direct streaming."
            )
    cached_path = render_cache.store(render_uuid.hex, gpkg_path)
    crud.graph.cache_render(
        db=db,
        graph=graph_obj,
        created_by=user,
        render_id=render_uuid,
        path=str(cached_path),
    )
    # "identity" makes GZipMiddleware pass the GeoPackage through uncompressed.
    return FileResponse(
        cached_path,
        media_type=GPKG_MEDIA_TYPE,
        headers={
            "ETag": etag.hex,
            "X-GerryDB-Graph-Render-ID": render_uuid.hex,
            "Content-Encoding": "identity",
        },
    )
