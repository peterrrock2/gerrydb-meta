"""Base configuration and routing for Gerry API endpoints."""

from fastapi import APIRouter

from gerrydb_meta import crud, schemas
from gerrydb_meta.api import (
    column,
    column_dedup,
    column_value,
    geo_import,
    geo_set,
    geography,
    graph,
    locality,
    namespace,
    obj_meta,
    plan,
    view,
    view_template,
)
from gerrydb_meta.api.base import NamespacedObjectApi

api_router = APIRouter()
api_router.include_router(locality.router, prefix="/localities", tags=["localities"])
api_router.include_router(namespace.router, prefix="/namespaces", tags=["namespaces"])
api_router.include_router(obj_meta.router, prefix="/meta", tags=["meta"])
api_router.include_router(geography.router, prefix="/geographies", tags=["geographies"])
api_router.include_router(
    geography.list_router, prefix="/__geography_list", tags=["geography_list"]
)
api_router.include_router(
    geography.fork_router, prefix="/__geography_fork", tags=["geography_fork"]
)
api_router.include_router(geo_import.router, prefix="/geo-imports", tags=["geo-imports"])
api_router.include_router(column_value.router, prefix="/columns", tags=["columns"])
api_router.include_router(column_dedup.router, prefix="/column-refs", tags=["columns"])
api_router.include_router(geo_set.router, prefix="/layers", tags=["layers"])
api_router.include_router(plan.router, prefix="/plans", tags=["plans"])
api_router.include_router(view.router, prefix="/views", tags=["views"])
api_router.include_router(view_template.router, prefix="/view-templates", tags=["view-templates"])
api_router.include_router(graph.router, prefix="/graphs", tags=["graphs"])


api_router.include_router(
    column.ColumnApi(
        crud=crud.column,
        get_schema=schemas.Column,
        create_schema=schemas.ColumnCreate,
        patch_schema=schemas.ColumnPatch,
        obj_name_singular="Column",
        obj_name_plural="Columns",
    ).router(),
    prefix="/columns",
    tags=["columns"],
)

api_router.include_router(
    NamespacedObjectApi(
        crud=crud.column_set,
        get_schema=schemas.ColumnSet,
        create_schema=schemas.ColumnSetCreate,
        obj_name_singular="ColumnSet",
        obj_name_plural="ColumnSets",
    ).router(),
    prefix="/column-sets",
    tags=["column-sets"],
)

api_router.include_router(
    NamespacedObjectApi(
        crud=crud.geo_layer,
        get_schema=schemas.GeoLayer,
        create_schema=schemas.GeoLayerCreate,
        obj_name_singular="GeoLayer",
        obj_name_plural="GeoLayers",
    ).router(),
    prefix="/layers",
    tags=["layers"],
)
