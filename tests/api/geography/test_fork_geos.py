import hashlib
import logging

import pytest
from fastapi import HTTPException
from shapely import Point, Polygon

import gerrydb_meta.crud as crud
import gerrydb_meta.schemas as schemas
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.api.geography.fork_geos import (
    __validate_forkability,
    __validate_source_and_target_namespaces,
    check_forkability,
    fork_geos_between_namespaces,
)


def test_fork_validate__source_and_target_namespaces_errors(ctx_no_scopes):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta
    scopes = get_scopes(user)

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full_2",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    with pytest.raises(HTTPException) as excinfo:
        __validate_source_and_target_namespaces(
            source_namespace="does_not_exist",
            target_namespace=ns2.path,
            db=db,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        f'Namespace "does_not_exist" not found, or you do not have '
        "sufficient permissions to read geometries in this namespace."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_source_and_target_namespaces(
            source_namespace=ns.path,
            target_namespace="does_not_exist",
            db=db,
            scopes=scopes,
        )

    assert excinfo.value.status_code == 404
    assert (
        f'Namespace "does_not_exist" not found, or you do not have '
        "sufficient permissions to write geometries in this namespace."
    ) in str(excinfo.value.detail)


def test_fork_validate__all_errors(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    source_namespace = "source_ns"
    source_layer = "source_layer"
    target_namespace = "target_ns"
    target_layer = "target_layer"
    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set(),
            target_geo_hash_pairs=set(),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 403
    assert (
        f"Cannot fork data from layer '{source_layer}' in "
        f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
        f"both the source and target layers do not contain any geographies."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set(),
            target_geo_hash_pairs=set([("target_geo", "target_geo")]),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 403
    assert (
        f"Cannot fork data from layer '{source_layer}' in "
        f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
        f"the source layer does not contain any geographies. Please check to make sure "
        f"that the source and target namespaces are correct."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set([("source_geo", hashlib.md5(Polygon().wkb).hexdigest())]),
            target_geo_hash_pairs=set(),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 403
    assert (
        f"Cannot fork data from layer '{source_layer}' in "
        f"'{source_namespace}' to layer '{target_layer}' in '{target_namespace}' because "
        "some of the source geographies have empty polygons and `allow_empty_polys` "
        f"is False."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set([("source_geo", "source_geo")]),
            target_geo_hash_pairs=set([("target_geo", "target_geo")]),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 409
    assert (
        f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
        f"to layer '{target_layer}' in '{target_namespace}' because some "
        f"geometries in the target namespace/layer are different from the geometries "
        f"in the source namespace/layer. Forking should only be used when attempting "
        f"to add geometries from the source namespace/layer that were not previously "
        f"present in the target namespace/layer to the target namespace/layer."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set([("geo1", "geo1")]),
            target_geo_hash_pairs=set([("geo1", "geo1"), ("geo2", "geo2")]),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 409
    assert (
        f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
        f"to layer '{target_layer}' in '{target_namespace}' because some "
        f"geometries in the target namespace/layer are not present in the "
        f"source namespace/layer."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set([("geo1", "geo1")]),
            target_geo_hash_pairs=set(),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 409
    assert (
        f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' "
        f"to layer '{target_layer}' in '{target_namespace}' because some "
        f"no geometries are present in the target namespace/layer and the parameter "
        f"`allow_extra_source_geos` was not passed as `True`."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        __validate_forkability(
            source_namespace=source_namespace,
            source_layer=source_layer,
            target_namespace=target_namespace,
            target_layer=target_layer,
            source_geo_hash_pairs=set([("geo1", "geo1"), ("geo2", "geo2")]),
            target_geo_hash_pairs=set([("geo1", "geo1")]),
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )
    assert excinfo.value.status_code == 409
    assert (
        f"Cannot fork data from layer '{source_layer}' in '{source_namespace}' to layer "
        f"'{target_layer}' in '{target_namespace}' because some geometries in the source "
        f"namespace/layer are not present in the target namespace/layer and the "
        f"parameter `allow_extra_source_geos` was not passed as `True`."
    ) in str(excinfo.value.detail)

    # This one should not raise an error
    __validate_forkability(
        source_namespace=source_namespace,
        source_layer=source_layer,
        target_namespace=target_namespace,
        target_layer=target_layer,
        source_geo_hash_pairs=set([("geo1", "geo1")]),
        target_geo_hash_pairs=set([("geo1", "geo1")]),
        allow_extra_source_geos=False,
        allow_empty_polys=False,
    )


def test_full_fork(ctx_no_scopes, caplog, me_2010_gdf):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269
    new_me_2010_gdf = me_2010_gdf.copy()

    new_me_2010_gdf["geometry"] = [Polygon() for _ in range(len(new_me_2010_gdf))]
    new_me_2010_gdf["internal_point"] = [Point() for _ in range(len(new_me_2010_gdf))]

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full_2",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in new_me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_fork_full",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    geo_layer2, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_fork_full",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_fork_full",
                name="main_fork_full",
                aliases=["maf", "23f"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    with pytest.raises(HTTPException) as excinfo:
        fork_geos_between_namespaces(
            target_namespace=ns2.path,
            loc_ref="maf",
            target_layer=geo_layer2.path,
            db=db,
            user=user,
            scopes=get_scopes(user),
            source_namespace=ns.path,
            source_layer=geo_layer.path,
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 403
    assert (
        "Cannot fork data from layer 'counties_fork_full' in 'test_fork_full' to layer "
        "'counties_fork_full' in 'test_fork_full_2' because some of the source geographies "
        "have empty polygons and `allow_empty_polys` is False."
    ) in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        fork_geos_between_namespaces(
            target_namespace=ns2.path,
            loc_ref="maf",
            target_layer=geo_layer2.path,
            db=db,
            user=user,
            scopes=get_scopes(user),
            source_namespace=ns.path,
            source_layer=geo_layer.path,
            allow_extra_source_geos=False,
            allow_empty_polys=True,
        )

    assert excinfo.value.status_code == 409
    assert (
        "Cannot fork data from layer 'counties_fork_full' in 'test_fork_full' to layer "
        "'counties_fork_full' in 'test_fork_full_2' because some geometries are present "
        "in the target namespace/layer and the parameter `allow_extra_source_geos` was not "
        "passed as `True`."
    ) in str(excinfo.value.detail)

    # Now check and everything

    fork_geos_between_namespaces(
        target_namespace=ns2.path,
        loc_ref="maf",
        target_layer=geo_layer2.path,
        db=db,
        user=user,
        scopes=get_scopes(user),
        source_namespace=ns.path,
        source_layer=geo_layer.path,
        allow_extra_source_geos=True,
        allow_empty_polys=True,
        notes="THERE ARE NO NOTES",
    )

    geos_in_new_ns = crud.geography.get_bulk(
        db=db,
        namespaced_paths=[(f"{ns2.path}", f"{row.Index}") for row in new_me_2010_gdf.itertuples()],
    )

    for geo in geos_in_new_ns:
        assert geo.namespace == ns2
        assert geo.path in new_me_2010_gdf.index
        assert str(geo.versions[0].geo_bin.geography) == Polygon().wkb.hex()


def test_full_fork_lingering_errors(ctx_no_scopes, caplog, me_2010_gdf):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269
    new_me_2010_gdf = me_2010_gdf.copy()

    new_me_2010_gdf["geometry"] = [Polygon() for _ in range(len(new_me_2010_gdf))]
    new_me_2010_gdf["internal_point"] = [Point() for _ in range(len(new_me_2010_gdf))]

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full",
            description="A test namespace",
            public=False,
        ),
        obj_meta=meta,
    )

    ns2, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_fork_full_2",
            description="A test namespace",
            public=True,
        ),
        obj_meta=meta,
    )

    geos_to_create = [
        schemas.GeographyCreate(
            path=str(row.Index),
            geography=row.geometry.wkb,
            internal_point=row.internal_point.wkb,
        )
        for row in new_me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_fork_full",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    geo_layer2, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_fork_full",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns2,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_fork_full",
                name="main_fork_full",
                aliases=["maf", "23f"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=[geo[0] for geo in geo],
        obj_meta=meta,
    )

    with pytest.raises(HTTPException) as excinfo:
        check_forkability(
            target_namespace=ns2.path,
            loc_ref="does_not_exist",
            target_layer=geo_layer2.path,
            db=db,
            scopes=get_scopes(user),
            source_namespace=ns.path,
            source_layer=geo_layer.path,
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 404
    assert "Locality 'does_not_exist' not found in namespace" in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        check_forkability(
            target_namespace=ns2.path,
            loc_ref="maf",
            target_layer="does_not_exist",
            db=db,
            scopes=get_scopes(user),
            source_namespace=ns.path,
            source_layer=geo_layer.path,
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 404
    assert "Layer 'does_not_exist' not found in namespace" in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        check_forkability(
            target_namespace=ns2.path,
            loc_ref="maf",
            target_layer=geo_layer2.path,
            db=db,
            scopes=get_scopes(user),
            source_namespace=ns.path,
            source_layer=geo_layer.path,
            allow_extra_source_geos=False,
            allow_empty_polys=False,
        )

    assert excinfo.value.status_code == 403
    assert (
        f"Namespace '{ns.path}' is not public, so you cannot fork values or geographies from it."
    ) in str(excinfo.value.detail)
