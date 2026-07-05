"""Generic CR(UD) views and utilities."""

import inspect
from collections import defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Callable, Type, NamedTuple
from uuid import UUID

import ormsgpack as msgpack
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from uvicorn.config import logger as log

from gerrydb_meta import crud, models
from gerrydb_meta.api.deps import get_db, get_obj_meta, get_scopes, no_perms
from gerrydb_meta.crud.base import normalize_path
from gerrydb_meta.exceptions import GerryValueError
from gerrydb_meta.scopes import ScopeManager

# For path resolution across objects.
ENDPOINT_TO_CRUD = {
    "columns": crud.column,
    "column-sets": crud.column_set,
    "geographies": crud.geography,
}


def check_etag(db: Session, crud_obj: crud.CRBase, header: str):
    """Processes an `If-None-Match` header.

    Raises 304 Not Modified if the collection's current ETag matches the
    ETag in `header`. Otherwise returns the etag for reuse in the response
    (it costs a query; callers should not fetch it twice).
    """
    etag = crud_obj.etag(db=db)
    if etag is not None and header == f'"{etag}"':
        raise HTTPException(status_code=HTTPStatus.NOT_MODIFIED)
    return etag


def check_namespaced_etag(
    db: Session,
    crud_obj: crud.NamespacedCRBase,
    namespace: models.Namespace,
    header: str,
):
    """Processes an `If-None-Match` header.

    Raises 304 Not Modified if the namespaced collection's current ETag
    matches the ETag in `header`. Otherwise returns the etag for reuse in
    the response (it costs a query; callers should not fetch it twice).
    """
    etag = crud_obj.etag(db=db, namespace=namespace)
    if etag is not None and header == f'"{etag}"':
        raise HTTPException(status_code=HTTPStatus.NOT_MODIFIED)
    return etag


def add_etag(response: Response, etag: UUID | None) -> None:
    """Adds an `ETag` header to a response from a UUID."""
    if etag is not None:
        response.headers["ETag"] = f'"{etag}"'


def namespace_read_error_msg(obj_name: str) -> str:
    """Generates an error message for a failed read in a namespace."""
    return (
        "Namespace not found, or you do not have sufficient permissions "
        f"to read {obj_name.lower()} in this namespace."
    )


def namespace_write_error_msg(obj_name: str) -> str:
    """Generates an error message for a failed write in a namespace."""
    return (
        "Namespace not found, or you do not have sufficient permissions "
        f"to write {obj_name.lower()} in this namespace."
    )


def body_schema(obj_type: Type, obj_arg: str = "obj_in") -> Callable:
    """Injects a schema type into the signature of a request handler.

    FastAPI derives validation logic and API documentation from the type
    annotations of request handlers, so it does not suffice to use the `BaseModel`
    class or similar as the type annotation for a request body (conventionally
    the `obj_in` argument to a handler). Thus, we mutate a handler's signature
    in place to provide a more specific type annotation before registering it
    with an API router.
    """

    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)
        params = dict(signature.parameters)
        params[obj_arg] = params[obj_arg].replace(annotation=obj_type)
        func.__signature__ = signature.replace(parameters=params.values())
        return func

    return decorator


def parse_path(path: str) -> tuple[str, str]:
    """Breaks a path of form `/<namespace>/<path>` into (namespace, path).

    Returns `None` for the namespace if the path is not in the expected form
    (i.e., the path is missing a namespace).
    """
    normalized_path = path.strip().lower()
    parts = normalized_path.split("/")
    return (None, normalized_path) if len(parts) < 3 else (parts[1], "/".join(parts[2:]))


def from_resource_paths(
    paths: list[str], db: Session, scopes: ScopeManager, follow_refs: bool = False
) -> list[models.DeclarativeBase]:
    """Returns a collection of objects from resource paths (/<resource>/<namespace>/<path>).

    This is primarily useful for creating and updating collections that contain objects
    of heterogenous type: for instance, a `ViewTemplate` contains `Column`s, `ColumnSet`s,
    and so on, but it is convenient to refer to these resources in one list on creation
    to encode ordering.

    Objects are returned in the order of `paths`. Paths are with respect to the API
    route, and supported objects and their endpoint prefixes are defined globally
    in `ENDPOINT_TO_CRUD`.

    Partial success is not possible: it is required that `scopes` allows access to all
    referenced namespaces, and that all paths are well-formed and reference existent
    objects.

    Args:
        paths: Paths of objects with (possibly) heterogenous types.
        namespace: Default namespace to use for path parsing.
        db: Database session.
        scopes: Authorization context.
        follow_refs: If `True`, reference objects (e.g. `ColumnRef`).
            are converted to the objects they point to (e.g. `DataColumn`).

    Raises:
        HTTPException: On parsing failure, authorization failure, or lookup failure.
    """
    # Break paths into (object, namespace, path) form.

    parsed_paths = []
    for path in paths:
        path = normalize_path(path, case_sensitive_uid="geographies" in path)
        parts = path.strip().split("/")
        if len(parts) < 3:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=(
                    f'Bad resource path "{path}": must have form /<resource>/<namespace>/<path>'
                ),
            )
        if parts[0] not in ENDPOINT_TO_CRUD:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'Unknown resource "{parts[0]}".',
            )

        parsed_paths.append(tuple(parts))

    # Check for duplicates, which usually violate uniqueness constraints
    # somewhere down the line.
    if len(set(parsed_paths)) < len(parsed_paths):
        dup_paths = [path for path in parsed_paths if parsed_paths.count(path) > 1]
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=f"Duplicate resource paths found {dup_paths}",
        )

    # Verify that the user has read access in all namespaces
    # the objects are in.
    try:
        namespaces = {namespace for _, namespace, _ in parsed_paths}
    except Exception as e:
        bad_paths = [path for path in parsed_paths if len(path) != 3]
        raise ValueError(
            f"Failed to parse paths: {['/'.join(path) for path in bad_paths]}. "
            "Paths must verify the form '/<resource>/<namespace>/<path>'."
        ) from e

    namespace_objs = {}
    for namespace in namespaces:
        namespace_obj = crud.namespace.get(db=db, path=namespace)
        namespace_objs[namespace] = namespace_obj
        if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=(
                    f'Namespace "{namespace}" not found, or you do not have '
                    "sufficient permissions to read data in this namespace."
                ),
            )

    # Group parsed paths by resource.
    paths_by_endpoint = defaultdict(list)
    for endpoint, namespace, path in parsed_paths:
        paths_by_endpoint[endpoint].append((namespace, path))

    # Look up objects, preferring bulk operations.
    obj_by_path = {}
    for endpoint, endpoint_paths in paths_by_endpoint.items():
        endpoint_crud = ENDPOINT_TO_CRUD[endpoint]
        if hasattr(endpoint_crud, "get_bulk"):
            # Get the objects in bulk by path; fail if any are unknown.
            objs = endpoint_crud.get_bulk(db, namespaced_paths=endpoint_paths)
            if len(objs) < len(parsed_paths):
                missing = set((ns, path) for _, ns, path in parsed_paths) - set(
                    (obj.namespace.path, obj.path) for obj in objs
                )
                formatted_missing = [
                    f"/{endpoint}/{miss_ns}/{miss_path}" for miss_ns, miss_path in missing
                ]
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail=f"Not found: {', '.join(formatted_missing)}",
                )
            for obj in objs:
                obj_by_path[(endpoint, obj.namespace.path, obj.path)] = obj

        else:
            # Fall back to single-object lookup.
            get_fn = (
                endpoint_crud.get_ref
                if hasattr(endpoint_crud, "get_ref") and not follow_refs
                else endpoint_crud.get
            )

            for namespace, path in endpoint_paths:
                obj = get_fn(db=db, namespace=namespace_objs[namespace], path=path)
                if obj is None:
                    raise HTTPException(
                        status_code=HTTPStatus.NOT_FOUND,
                        detail=f"Not found: /{endpoint}/{namespace}/{path}",
                    )
                obj_by_path[(endpoint, namespace, path)] = obj

    # Put objects back in `path` order.
    return [obj_by_path[key] for key in parsed_paths]


def namespace_with_read(
    db: Session,
    scopes: ScopeManager,
    path: str,
    base_namespace: str | None = None,
) -> models.Namespace:
    """Loads a namespace with read access or raises an HTTP error.

    Also enforces the private join constraint: a view cannot reference
    private namespaces that are not its own. If `base_namespace` is provided,
    private namespaces with paths that do not match `base_namespace` are rejected.
    """
    namespace_obj = crud.namespace.get(db=db, path=path)
    if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'Namespace "{path}" not found, or you do not have sufficient '
                "permissions to read in this namespace."
            ),
        )
    if (
        base_namespace is not None
        and not namespace_obj.public
        and namespace_obj.path != base_namespace
    ):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot join across private namespaces: namespace {namespace_obj.path} is private."
            ),
        )
    return namespace_obj


def geos_from_paths(
    paths: list[str], namespace: str, db: Session, scopes: ScopeManager
) -> list[models.Geography]:
    """Returns a collection of geographies, possibly across namespaces.

    Geographies are returned in the order of `paths`.

    Partial success is not possible: it is required that `scopes` allows access to all
    referenced namespaces, and that all paths are well-formed and reference existent
    geographies.

    Args:
        paths: Paths of geographies, either relative to `namespace` or absolute.
        namespace: Default namespace to use for path parsing.
        db: Database session.
        scopes: Authorization context.

    Raises:
        HTTPException: On parsing failure, authorization failure, or lookup failure.
    """
    return from_resource_paths(
        paths=[
            (f"/geographies{path}" if path.startswith("/") else f"/geographies/{namespace}/{path}")
            for path in paths
        ],
        db=db,
        scopes=scopes,
    )


class GeoRef(NamedTuple):
    """Lightweight stand-in for a Geography row on bulk write paths.

    Carries exactly the attributes bulk writers consume (`geo_id`, `path`,
    `namespace_id`, `full_path`); hashable, so it can key assignment dicts.
    """

    geo_id: int
    path: str
    namespace_id: int
    full_path: str


def geo_refs_from_paths(
    paths: list[str], namespace: str, db: Session, scopes: ScopeManager
) -> list[GeoRef]:
    """Resolves geography paths to lightweight refs, possibly across namespaces.

    Same contract, ordering, and error behavior as `geos_from_paths`, but
    resolves through a three-column projection instead of ORM entities:
    Geography eager-joins meta and namespace, so the ORM route materializes a
    four-table join per path that bulk writers (column values, set mapping,
    plan/graph creation) never read.

    Raises:
        HTTPException: On parsing failure, authorization failure, or lookup failure.
    """
    parsed: list[tuple[str, str]] = []
    for path in paths:
        # Absoluteness must be read off the raw path: normalize_path strips
        # leading slashes, so the normalized form never starts with "/".
        is_absolute = path.startswith("/")
        norm = normalize_path(path, case_sensitive_uid=True)
        parts = norm.split("/")
        if (is_absolute and len(parts) != 2) or (not is_absolute and len(parts) != 1):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=(
                    f'Bad resource path "/geographies/{norm}": '
                    "must have form /<resource>/<namespace>/<path>"
                ),
            )
        parsed.append((parts[0], parts[1]) if is_absolute else (namespace, norm))

    if len(set(parsed)) < len(parsed):
        dup_paths = [
            ("geographies", ns, path) for ns, path in parsed if parsed.count((ns, path)) > 1
        ]
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=f"Duplicate resource paths found {dup_paths}",
        )

    namespace_ids: dict[str, int] = {}
    for ns in {ns for ns, _ in parsed}:
        namespace_obj = crud.namespace.get(db=db, path=ns)
        if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=(
                    f'Namespace "{ns}" not found, or you do not have '
                    "sufficient permissions to read data in this namespace."
                ),
            )
        namespace_ids[ns] = namespace_obj.namespace_id

    refs_by_key: dict[tuple[str, str], GeoRef] = {}
    for ns, ns_id in namespace_ids.items():
        ns_paths = [path for p_ns, path in parsed if p_ns == ns]
        rows = db.execute(
            select(
                models.Geography.geo_id,
                models.Geography.path,
                models.Geography.namespace_id,
            ).where(
                models.Geography.namespace_id == ns_id,
                models.Geography.path.in_(ns_paths),
            )
        )
        for row in rows:
            refs_by_key[(ns, row.path)] = GeoRef(
                geo_id=row.geo_id,
                path=row.path,
                namespace_id=row.namespace_id,
                full_path=f"/{ns}/{row.path}",
            )

    if len(refs_by_key) < len(set(parsed)):
        missing = set(parsed) - set(refs_by_key)
        formatted_missing = [f"/geographies/{ns}/{path}" for ns, path in sorted(missing)]
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"Not found: {', '.join(formatted_missing)}",
        )

    return [refs_by_key[key] for key in parsed]


def geo_set_from_paths(
    locality: str, layer: str, namespace: str, *, db: Session, scopes: ScopeManager
) -> models.GeoSetVersion:
    """Returns the latest `GeoSetVersion` corresponding to `locality` and `layer`.

    Raises:
        HTTPException: If no such `GeoSetVersion` exists, or if the requester
            does not have permissions to access the GeoSet or its associated
            geographic layer or locality.
    """
    log.debug("TOP OF GEO SET FROM PATHS")
    if not scopes.can_read_localities():
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=no_perms("read localities"),
        )

    locality_obj = crud.locality.get_by_ref(db=db, path=locality)
    if locality_obj is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Locality not found.")

    log.debug("PAST BASIC CHECKS")

    layer_namespace, layer_path = parse_path(layer)
    if layer_namespace is None:
        layer_namespace = namespace

    layer_namespace_obj = namespace_with_read(
        db=db,
        scopes=scopes,
        path=layer_namespace,
        base_namespace=namespace,
    )
    layer_obj = crud.geo_layer.get(
        db=db,
        path=layer_path,
        namespace=layer_namespace_obj,
    )
    if layer_obj is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Geographic layer not found.")

    # Verify that a `GeoSet` currently exists for (locality, layer).
    geo_set_version = crud.geo_layer.get_set_by_locality(
        db=db, layer=layer_obj, locality=locality_obj
    )
    if geo_set_version is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=(
                f'No set of geographies in geographic layer "{layer}" at locality "{locality}".'
            ),
        )
    return geo_set_version


# see https://fastapi.tiangolo.com/advanced/custom-request-and-route/
class MsgpackRequest(Request):
    """A request with a MessagePack-encoded body."""

    async def body(self) -> bytes:
        if not hasattr(self, "_body"):
            body = await super().body()
            if body:
                body = msgpack.unpackb(body)
            self._body = body
        return self._body


# see https://fastapi.tiangolo.com/advanced/custom-response/
class MsgpackResponse(Response):
    """A request with a MessagePack-encoded body."""

    media_type = "application/msgpack"

    def render(self, content: Any) -> bytes:
        return msgpack.packb(content)


class MsgpackRoute(APIRoute):
    """A route where requests must have a MessagePack-encoded body."""

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            if request.headers.get("content-type") not in (
                "application/msgpack",
                "application/x-msgpack",
            ):
                raise HTTPException(
                    status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    detail="Only MessagePack requests are supported by this endpoint.",
                )

            try:
                request = MsgpackRequest(request.scope, request.receive)
                return await original_route_handler(request)
            except GerryValueError as ex:
                # `MsgpackDecodeError` behaves like an alias of `ValueError`,
                # so we need to explicitly avoid the `MsgpackDecodeError` handler
                # below when dealing with `ValueError`s raised by database operations.
                raise ex
            except msgpack.MsgpackDecodeError:
                log.exception("MessagePack decode failed.")
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Request body is not a valid MessagePack object.",
                )

        return custom_route_handler


@dataclass
class NamespacedObjectApi:
    """Generic API for a namespaced object."""

    crud: crud.NamespacedCRBase
    get_schema: crud.GetSchemaType
    create_schema: crud.CreateSchemaType | None
    obj_name_singular: str
    obj_name_plural: str
    patch_schema: crud.PatchSchemaType | None = None
    # Listing schema override: collections can serialize a slimmer shape than
    # single gets (e.g. plans list without per-geography assignments).
    list_schema: crud.GetSchemaType | None = None
    # Server-side ceiling on list page size; None means unbounded. Set on
    # collections that can reach millions of rows (geographies).
    list_hard_cap: int | None = None

    def _namespace_with_read(
        self,
        *,
        db: Session,
        scopes: ScopeManager,
        path: str,
        base_namespace: str | None = None,
    ) -> models.Namespace:
        """Loads a namespace with read access or raises an HTTP error.

        Also enforces the private join constraint: a view cannot reference
        private namespaces that are not its own. If `base_namespace` is provided,
        private namespaces with paths that do not match `base_namespace` are rejected.
        """
        namespace_obj = crud.namespace.get(db=db, path=path)
        if namespace_obj is None or not scopes.can_read_in_namespace(namespace_obj):
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=namespace_read_error_msg(self.obj_name_plural),
            )

        if (
            base_namespace is not None
            and not namespace_obj.public
            and namespace_obj.path != base_namespace
        ):
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail=(
                    "Cannot join across private namespaces: "
                    f"namespace {namespace_obj.path} is private."
                ),
            )

        return namespace_obj

    def _namespace_with_write(
        self,
        *,
        db: Session,
        scopes: ScopeManager,
        path: str,
        base_namespace: str | None = None,
    ) -> models.Namespace:
        """Loads a namespace with write access or raises an HTTP error.

        Also enforces the private join constraint: a view cannot reference
        private namespaces that are not its own. If `base_namespace` is provided,
        private namespaces with paths that do not match `base_namespace` are rejected.
        """
        namespace_obj = crud.namespace.get(db=db, path=path)
        if namespace_obj is None or not scopes.can_write_in_namespace(namespace_obj):
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=namespace_write_error_msg(self.obj_name_plural),
            )

        if (
            base_namespace is not None
            and not namespace_obj.public
            and namespace_obj.path != base_namespace
        ):
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail=(
                    "Cannot join across private namespaces: "
                    f"namespace {namespace_obj.path} is private."
                ),
            )

        return namespace_obj

    def _obj(self, *, db: Session, namespace: models.Namespace, path: str) -> Any:
        """Loads a generic namespaced object or raises an HTTP error."""
        obj = self.crud.get(db=db, namespace=namespace, path=path)
        if obj is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"{self.obj_name_singular} '{path}' not found in namespace.",
            )
        return obj

    def _check_etag(self, *, db: Session, namespace: models.Namespace, header: str | None):
        """Processes an `If-None-Match` header.

        Raises 304 Not Modified if the namespaced collection's current ETag
        matches the ETag in `header`. Otherwise returns the etag.
        """
        return check_namespaced_etag(db=db, crud_obj=self.crud, namespace=namespace, header=header)

    def _get(self, router: APIRouter) -> Callable:
        @router.get(
            "/{namespace}/{path:path}",
            response_model=self.get_schema,
            name=f"Read {self.obj_name_singular}",
        )
        def get_route(
            *,
            response: Response,
            namespace: str,
            path: str,
            db: Session = Depends(get_db),
            scopes: ScopeManager = Depends(get_scopes),
            if_none_match: str | None = Header(default=None),
        ):
            log.debug("IN GET FOR NAMESPACED OBJECT API")
            namespace_obj = self._namespace_with_read(db=db, scopes=scopes, path=namespace)
            etag = self._check_etag(db=db, namespace=namespace_obj, header=if_none_match)
            obj = self._obj(db=db, namespace=namespace_obj, path=path)
            add_etag(response, etag)
            return self.get_schema.from_attributes(obj)

        return get_route

    def _all(self, router: APIRouter) -> Callable:
        list_schema = self.list_schema or self.get_schema

        @router.get(
            "/{namespace}",
            response_model=list[list_schema],
            name=f"Read {self.obj_name_plural}",
        )
        def all_route(
            *,
            response: Response,
            namespace: str,
            limit: int | None = Query(default=None, ge=1),
            offset: int = Query(default=0, ge=0),
            db: Session = Depends(get_db),
            scopes: ScopeManager = Depends(get_scopes),
            if_none_match: str | None = Header(default=None),
        ):
            log.debug("IN GET ALL FOR NAMESPACED OBJECT API")
            namespace_obj = self._namespace_with_read(db=db, scopes=scopes, path=namespace)
            etag = self._check_etag(db=db, namespace=namespace_obj, header=if_none_match)
            if self.list_hard_cap is not None:
                limit = min(limit or self.list_hard_cap, self.list_hard_cap)
            objs = self.crud.all_in_namespace(
                db=db, namespace=namespace_obj, limit=limit, offset=offset
            )
            add_etag(response, etag)
            return [list_schema.from_attributes(obj) for obj in objs]

        return all_route

    def _create(self, router: APIRouter) -> Callable:
        @router.post(
            "/{namespace}",
            response_model=self.get_schema,
            name=f"Create {self.obj_name_singular}",
            status_code=HTTPStatus.CREATED,
        )
        @body_schema(self.create_schema)
        def create_route(
            *,
            response: Response,
            namespace: str,
            obj_in: BaseModel,
            db: Session = Depends(get_db),
            obj_meta: models.ObjectMeta = Depends(get_obj_meta),
            scopes: ScopeManager = Depends(get_scopes),
        ):
            log.debug("IN POST FOR NAMESPACED OBJECT API")
            namespace_obj = self._namespace_with_write(db=db, scopes=scopes, path=namespace)
            obj, etag = self.crud.create(
                db=db, obj_in=obj_in, namespace=namespace_obj, obj_meta=obj_meta
            )
            add_etag(response, etag)
            return self.get_schema.from_attributes(obj)

        return create_route

    def _patch(self, router: APIRouter) -> Callable:
        @router.patch(
            "/{namespace}/{path:path}",
            response_model=self.get_schema,
            name=f"Patch {self.obj_name_singular}",
        )
        @body_schema(self.patch_schema)
        def patch_route(
            *,
            response: Response,
            namespace: str,
            path: str,
            obj_in: BaseModel,
            db: Session = Depends(get_db),
            obj_meta: models.ObjectMeta = Depends(get_obj_meta),
            scopes: ScopeManager = Depends(get_scopes),
        ):
            log.debug("IN PATCH FOR NAMESPACED OBJECT API")
            namespace_obj = self._namespace_with_write(db=db, scopes=scopes, path=namespace)
            obj = self._obj(db=db, namespace=namespace_obj, path=path)
            if getattr(obj, "namespace_id", namespace_obj.namespace_id) != namespace_obj.namespace_id:
                # The path resolved through a cross-namespace reference; the
                # write scope that was checked belongs to the referencing
                # namespace, not the object's owner.
                raise HTTPException(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail=(
                        f"'{path}' is a reference to an object in another "
                        "namespace and cannot be modified through the reference."
                    ),
                )
            patched_obj, etag = self.crud.patch(db=db, obj=obj, obj_meta=obj_meta, patch=obj_in)
            add_etag(response, etag)
            return self.get_schema.from_attributes(patched_obj)

        return patch_route

    def router(self) -> APIRouter:
        """Generates a router with basic CR operations for the object."""
        router = APIRouter()
        for route_func in (self._get, self._all, self._create):
            route_func(router)

        if self.patch_schema is not None and hasattr(self.crud, "patch"):
            self._patch(router)

        return router
