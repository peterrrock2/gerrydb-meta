"""Endpoints for views."""

import os
import subprocess
import time
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import storage
from google.oauth2.service_account import Credentials
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.api.base import add_etag, namespace_with_read, parse_path
from gerrydb_meta.api.deps import (
    can_read_localities,
    get_db,
    get_obj_meta,
    get_ogr2ogr_db_config,
    get_scopes,
    get_user,
)
from gerrydb_meta.render import view_to_gpkg
from gerrydb_meta.scopes import ScopeManager
from gerrydb_meta.exceptions import ViewConflictError


router = APIRouter()
GPKG_MEDIA_TYPE = "application/geopackage+sqlite3"


@router.post(
    "/{namespace}",
    response_model=schemas.ViewMeta,
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_read_localities)],
)
def create_view(
    *,
    response: Response,
    namespace: str,
    obj_in: schemas.ViewCreate,
    db: Session = Depends(get_db),
    obj_meta: models.ObjectMeta = Depends(get_obj_meta),
    scopes: ScopeManager = Depends(get_scopes),
):
    view_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if view_namespace_obj is None or not scopes.can_write_derived_in_namespace(
        view_namespace_obj
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to write views in this namespace."
            ),
        )

    locality_obj = crud.locality.get_by_ref(db=db, path=obj_in.locality)
    if locality_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Locality not found."
        )

    layer_namespace, layer_path = parse_path(obj_in.layer)
    template_namespace, template_path = parse_path(obj_in.template)
    if obj_in.graph is None:
        graph_namespace = graph_path = None
    else:
        graph_namespace, graph_path = parse_path(obj_in.graph)

    namespaces = {
        "layer": namespace if layer_namespace is None else layer_namespace,
        "template": namespace if template_namespace is None else template_namespace,
        "graph": namespace if graph_namespace is None else graph_namespace,
    }
    namespace_objs = {}
    for namespace_label, resource_namespace in namespaces.items():
        namespace_objs[namespace_label] = namespace_with_read(
            db=db, scopes=scopes, path=resource_namespace, base_namespace=namespace
        )

    template_obj = crud.view_template.get(
        db, path=template_path, namespace=namespace_objs["template"]
    )
    if template_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="View template not found."
        )

    layer_obj = crud.geo_layer.get(
        db, path=layer_path, namespace=namespace_objs["layer"]
    )
    if layer_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Geographic layer not found."
        )

    if graph_path is None:
        graph_obj = None
    else:
        graph_obj = crud.graph.get(
            db, path=graph_path, namespace=namespace_objs["graph"]
        )
        if graph_obj is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail="Dual graph not found."
            )

    try:
        view_obj, etag = crud.view.create(
            db=db,
            obj_in=obj_in,
            obj_meta=obj_meta,
            namespace=view_namespace_obj,
            template=template_obj,
            locality=locality_obj,
            layer=layer_obj,
            graph=graph_obj,
        )
    except ViewConflictError as ex:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=f"Cannot create view. {ex}",
        ) from ex
    add_etag(response, etag)
    return schemas.ViewMeta.from_attributes(view_obj)


@router.get(
    "/{namespace}/{path:path}",
    response_model=schemas.ViewMeta,
    dependencies=[Depends(can_read_localities)],
)
def get_view(
    *,
    response: Response,
    namespace: str,
    path: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
):
    """
    Returns a ViewMeta object containing information about a view, but not the
    view itself.
    """
    view_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if view_namespace_obj is None or not scopes.can_read_in_namespace(
        view_namespace_obj
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read views in this namespace."
            ),
        )

    view_obj = crud.view.get(db=db, namespace=view_namespace_obj, path=path)
    if view_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"View not found in namespace.",
        )

    etag = crud.view.etag(db, view_namespace_obj)
    add_etag(response, etag)
    return schemas.ViewMeta.from_attributes(view_obj)


@router.get(
    "/{namespace}",
    response_model=list[schemas.ViewMeta],
    dependencies=[Depends(can_read_localities)],
)
def all_views(
    *,
    response: Response,
    namespace: str,
    db: Session = Depends(get_db),
    scopes: ScopeManager = Depends(get_scopes),
):
    view_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if view_namespace_obj is None or not scopes.can_read_in_namespace(
        view_namespace_obj
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to read views in this namespace."
            ),
        )

    view_objs = crud.view.all(db=db, namespace=view_namespace_obj)
    etag = crud.view.etag(db, view_namespace_obj)
    add_etag(response, etag)
    return [schemas.ViewMeta.from_attributes(view_obj) for view_obj in view_objs]


@router.post(
    "/{namespace}/{path:path}",
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(can_read_localities)],
    response_class=FileResponse,
)
def render_view(
    *,
    namespace: str,
    path: str,
    db: Session = Depends(get_db),
    db_config: str = Depends(get_ogr2ogr_db_config),
    user: models.User = Depends(get_user),
    scopes: ScopeManager = Depends(get_scopes),
):
    log.debug("TOP OF VIEW RENDER")
    view_namespace_obj = crud.namespace.get(db=db, path=namespace)
    if view_namespace_obj is None or not scopes.can_read_in_namespace(
        view_namespace_obj
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{namespace}" not found, or you do not have '
                "sufficient permissions to write views in this namespace."
            ),
        )

    view_obj = crud.view.get(db=db, namespace=view_namespace_obj, path=path)
    if view_obj is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"View not found in namespace.",
        )
    etag = crud.view.etag(db, view_namespace_obj)

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

    cached_render_meta = crud.view.get_cached_render(db=db, view=view_obj)
    if cached_render_meta is not None and has_gcs_context:  # pragma: no cover
        log.debug("Found cached render")
        render_path = urlparse(cached_render_meta.path)
        try:
            bucket = storage_client.bucket(render_path.netloc)
            blob = bucket.get_blob(render_path.path[1:])
            if blob is None:
                raise FileNotFoundError(
                    f"Cached view render not found in bucket: {render_path.path[1:]}"
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
                "Failed to serve rendered view via Google Cloud Storage. "
                "Falling back to direct streaming."
            )

    log.debug("BEFORE RENDER")
    start = time.perf_counter()
    render_ctx = crud.view.render(db=db, view=view_obj)
    log.debug("Time to render: %s", time.perf_counter() - start)
    start = time.perf_counter()
    render_uuid, gpkg_path = view_to_gpkg(context=render_ctx, db_config=db_config)
    log.debug("Time to write GPKG: %s", time.perf_counter() - start)
    log.debug("AFTER GPKG")

    if has_gcs_context:  # pragma: no cover
        log.debug("Attempting to upload rendered view to Google Cloud Storage")
        try:
            bucket = storage_client.bucket(bucket_name)
            gzipped_path = gpkg_path.with_suffix(".gpkg.gz")
            subprocess.run(["gzip", "-k", "-1", str(gpkg_path)], check=True)

            blob_path = f"{render_uuid.hex}.gpkg.gz"
            blob = bucket.blob(blob_path)
            blob.content_encoding = "gzip"
            blob.metadata = {"gerrydb-view-render-id": render_uuid.hex}
            blob.upload_from_filename(gzipped_path, content_type=GPKG_MEDIA_TYPE)
            crud.view.cache_render(
                db=db,
                view=view_obj,
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
                "Failed to serve rendered view via Google Cloud Storage. "
                "Falling back to direct streaming."
            )
    log.debug("Returning GPKG response")
    return FileResponse(
        gpkg_path,
        media_type=GPKG_MEDIA_TYPE,
        headers={
            "ETag": etag.hex,
            "X-GerryDB-View-Render-ID": render_uuid.hex,
        },
    )
