import logging

import gerrydb_meta.models as models
from gerrydb_meta import crud, schemas
from gerrydb_meta.api.base import geo_set_from_paths
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.main import API_PREFIX


def test_good_map_layer_view(db, me_2010_gdf, ctx_superuser, caplog):
    ctx = ctx_superuser
    user = models.User(email="geo_settest@example.com", name="geo_set User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"geo_set_testing_key", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="geo_set test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.DEBUG, logger="uvicorn")
    logging.getLogger("uvicorn").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_geo_ns",
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
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_geo_layer",
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
                canonical_path="maine_geo_set",
                parent_path=None,
                name="maine_geo_set",
                aliases=["mar", "23r"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    db.flush()

    loc = loc[0]

    map_locality_response = ctx.client.put(
        f"{API_PREFIX}/layers/test_geo_ns/counties_geo_layer?locality=maine_geo_set",
        json={"paths": [g.path for g in geo_objs]},
    )
    map_locality_response.raise_for_status()

    layer_out = (
        db.query(models.GeoLayer)
        .filter(
            models.GeoLayer.path == "counties_geo_layer",
            models.GeoLayer.namespace_id == ns.namespace_id,
        )
        .first()
    )
    assert layer_out.path == "counties_geo_layer"

    geo_set_out = (
        db.query(models.GeoSetVersion)
        .filter(
            models.GeoSetVersion.layer_id == layer_out.layer_id,
            models.GeoSetVersion.loc_id == loc.loc_id,
        )
        .one()
    )

    geo_set_members = (
        db.query(models.GeoSetMember)
        .filter(
            models.GeoSetMember.set_version_id == geo_set_out.set_version_id,
        )
        .all()
    )

    assert len(geo_set_members) == len(geo_objs)
    assert set([g.geo_id for g in geo_objs]) == set([g.geo_id for g in geo_set_members])

    geo_set_version = geo_set_from_paths(
        locality=loc.name,
        layer=f"layers/{ns.path}/{layer_out.path}/",
        namespace=ns.path,
        db=db,
        scopes=get_scopes(ctx.admin_user),
    )
    assert geo_set_version.set_version_id == geo_set_out.set_version_id


def test_errors_map_layer_view(db, me_2010_gdf, ctx_superuser, caplog):

    ctx = ctx_superuser
    user = models.User(email="geo_set_bad@example.com", name="geo_set_bad User")
    db.add(user)
    db.flush()

    api_key = models.ApiKey(key_hash=b"geo_set_bad_testing_key", user_id=user.user_id, user=user)
    db.add(api_key)
    db.flush()

    meta = models.ObjectMeta(notes="geo_set_bad test", created_by=user.user_id)
    db.add(meta)
    db.commit()
    db.flush()

    caplog.set_level(logging.DEBUG, logger="uvicorn")
    logging.getLogger("uvicorn").addHandler(caplog.handler)

    assert me_2010_gdf.crs.to_epsg() == 4269

    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="test_geo_set_bad",
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
        for row in me_2010_gdf.itertuples()
    ]

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=geos_to_create,
        obj_meta=meta,
        namespace=ns,
        geo_import=geo_import,
    )
    geo_objs = [g[0] for g in geo]

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="counties_geo_layer",
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
                canonical_path="maine_geo_set_bad",
                parent_path=None,
                name="maine_geo_set_bad",
                aliases=["mar", "23r"],
                default_proj="epsg:26919",
            )
        ],
        obj_meta=meta,
    )

    db.flush()

    loc = loc[0]

    bad_ns_response = ctx.client.put(
        f"{API_PREFIX}/layers/this_ns_is_bad/counties_geo_layer?locality=maine_geo_set_bad",
        json={"paths": [g.path for g in geo_objs]},
    )
    assert bad_ns_response.status_code == 404
    assert (
        "Namespace not found, or you do not have sufficient permissions to write geographic "
        "layers in this namespace."
    ) in bad_ns_response.json()["detail"]

    bad_loc_response = ctx.client.put(
        f"{API_PREFIX}/layers/test_geo_set_bad/counties_geo_layer?locality=bad_locality",
        json={"paths": [g.path for g in geo_objs]},
    )

    assert bad_loc_response.status_code == 404
    assert "Locality not found" in bad_loc_response.json()["detail"]

    bad_layer_response = ctx.client.put(
        f"{API_PREFIX}/layers/test_geo_set_bad/bad_layer?locality=maine_geo_set_bad",
        json={"paths": [g.path for g in geo_objs]},
    )
    assert bad_layer_response.status_code == 404
    assert "Geographic layer not found" in bad_layer_response.json()["detail"]
