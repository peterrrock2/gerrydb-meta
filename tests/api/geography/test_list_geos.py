import hashlib

import shapely

from gerrydb_meta.crud.geography import GEO_GRID_SIZE


def canonical_md5(geom):
    """Hash of the stored (grid-snapped) WKB bytes."""
    snapped = geom if geom.is_empty else shapely.set_precision(geom, GEO_GRID_SIZE, mode="pointwise")
    return hashlib.md5(snapped.wkb).hexdigest()
import logging
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from shapely import Point, Polygon

import gerrydb_meta.crud as crud
import gerrydb_meta.schemas as schemas
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.api.geography.list_geos import GetMode, all_paths


def test_full_list(ctx_no_scopes, caplog, me_2010_gdf):
    db = ctx_no_scopes.db
    user = ctx_no_scopes.admin_user
    meta = ctx_no_scopes.admin_meta
    scopes = get_scopes(user)

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    logging.getLogger("uvicorn.error").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269
    new_me_2010_gdf = me_2010_gdf.copy()

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_list_full",
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
            path="counties_list_full",
            description="2010 U.S. Census counties.",
            source_url="https://www.census.gov/",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="main_list_full",
                name="main_list_full",
                aliases=["mal", "23l"],
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
        all_paths(
            namespace="bad_namespace",
            loc_ref="mal",
            layer="counties_list_full",
            db=db,
            scopes=scopes,
            mode=GetMode.list_paths,
        )

    assert excinfo.value.status_code == 404
    assert (
        "Namespace 'bad_namespace' not found, or you do not have sufficient permissions "
        "to read data in this namespace."
    )

    path_list = all_paths(
        namespace=ns.path,
        loc_ref="mal",
        layer="counties_list_full",
        db=db,
        scopes=scopes,
        mode=GetMode.list_paths,
    )

    assert set(path_list) == set(me_2010_gdf.index)

    time1 = datetime.now(timezone.utc)

    path_hash_list = all_paths(
        namespace=ns.path,
        loc_ref="mal",
        layer="counties_list_full",
        db=db,
        scopes=scopes,
        mode=GetMode.path_hash_pair,
    )
    path_hash_dict = dict(path_hash_list)

    assert set(path_hash_dict.keys()) == set(me_2010_gdf.index)
    assert set(path_hash_dict.values()) == {
        canonical_md5(row.geometry) for row in new_me_2010_gdf.itertuples()
    }

    new_me_2010_gdf["geometry"] = [Polygon() for _ in range(len(new_me_2010_gdf))]
    new_me_2010_gdf["internal_point"] = [Point() for _ in range(len(new_me_2010_gdf))]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geo = crud.geography.patch_bulk(
        db=db,
        objs_in=[
            schemas.GeographyPatch(
                path=str(row.Index),
                geography=row.geometry.wkb,
                internal_point=row.internal_point.wkb,
            )
            for row in new_me_2010_gdf.itertuples()
        ],
        geo_import=geo_import,
        namespace=ns,
        allow_empty_polys=True,
    )

    path_hash_list = all_paths(
        namespace=ns.path,
        loc_ref="mal",
        layer="counties_list_full",
        db=db,
        scopes=scopes,
        mode=GetMode.path_hash_pair,
    )
    path_hash_dict = dict(path_hash_list)

    assert set(path_hash_dict.keys()) == set(me_2010_gdf.index)
    assert set(path_hash_dict.values()) == {
        canonical_md5(row.geometry) for row in new_me_2010_gdf.itertuples()
    }

    # Check that being valid at a specific time returns the correct hashes
    path_hash_list = all_paths(
        namespace=ns.path,
        loc_ref="mal",
        layer="counties_list_full",
        db=db,
        scopes=scopes,
        mode=GetMode.path_hash_pair,
        valid_at=time1,
    )
    path_hash_dict = dict(path_hash_list)

    assert set(path_hash_dict.keys()) == set(me_2010_gdf.index)
    assert set(path_hash_dict.values()) == {
        canonical_md5(row.geometry) for row in me_2010_gdf.itertuples()
    }
