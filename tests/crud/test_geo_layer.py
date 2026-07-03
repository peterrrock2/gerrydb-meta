import pytest

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.exceptions import CreateValueError


def make_atlantis_ns(db, meta):
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(
            path="atlantis",
            description="A legendary city",
            public=True,
        ),
        obj_meta=meta,
    )
    return ns


def test_crud_geo_layer_create(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert geo_layer.description == "The legendary city of Atlantis"
    assert geo_layer.path == "atlantis"
    assert geo_layer.namespace_id == ns.namespace_id
    assert geo_layer.meta_id == meta.meta_id
    assert str(geo_layer.source_url) == "https://en.wikipedia.org/wiki/Atlantis"


def test_crud_geo_layer_get(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert crud.geo_layer.get(db=db, path="atlantis", namespace=ns) == geo_layer


import logging


def test_crud_geo_layer_map_locality(db_with_meta, caplog):
    db, meta = db_with_meta

    caplog.set_level(logging.DEBUG, logger="uvicorn.error")

    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path=None,
                name="Locality of the Lost City of Atlantis",
                aliases=None,
            ),
        ],
        obj_meta=meta,
    )

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=None,
                internal_point=None,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=None,
                internal_point=None,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geography_list = [geo[0] for geo in geo]

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=geography_list,
        obj_meta=meta,
    )

    created_geo_set = (
        db.query(models.GeoSetVersion)
        .filter(
            models.GeoSetVersion.layer_id == geo_layer.layer_id,
            models.GeoSetVersion.loc_id == loc[0].loc_id,
        )
        .all()
    )

    geo_set_paths = []
    for item in created_geo_set[0].members:
        geo_set_paths.append(item.geo.full_path)

    assert "/atlantis/central_atlantis" in geo_set_paths
    assert "/atlantis/western_atlantis" in geo_set_paths

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=geography_list,
        obj_meta=meta,
    )
    assert (
        f"Attempted to create a new geo set for layer {geo_layer.full_path}"
        f" in the namespace {geo_layer.namespace.path} at locality "
        f" {loc[0].canonical_ref} but the new set is identical"
        f" to the old set."
    ) in caplog.text

    bad_geo_list = geography_list.copy()
    bad_geo_list[0].namespace_id = 2
    with pytest.raises(CreateValueError, match="Cannot map geographies in multiple namespaces"):
        crud.geo_layer.map_locality(
            db=db,
            layer=geo_layer,
            locality=loc[0],
            geographies=bad_geo_list,
            obj_meta=meta,
        )


def test_crud_geo_layer_get_set_by_locality(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path=None,
                name="Locality of the Lost City of Atlantis",
                aliases=None,
            ),
        ],
        obj_meta=meta,
    )

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=None,
                internal_point=None,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=None,
                internal_point=None,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geography_list = [geo[0] for geo in geo]

    crud.geo_layer.map_locality(
        db=db,
        layer=geo_layer,
        locality=loc[0],
        geographies=geography_list,
        obj_meta=meta,
    )

    created_geo_set = (
        db.query(models.GeoSetVersion)
        .filter(
            models.GeoSetVersion.layer_id == geo_layer.layer_id,
            models.GeoSetVersion.loc_id == loc[0].loc_id,
        )
        .all()[0]
    )

    assert created_geo_set == crud.geo_layer.get_set_by_locality(
        db=db, layer=geo_layer, locality=loc[0]
    )


def test_crud_geo_layer_map_locality_versioning(db_with_meta):
    """Regression: the no-op/versioning decision is scoped to (layer, locality).

    The comparison previously ran against every member of every set version in
    the database, so an identical remap never no-opped, and mapping the same
    members to a second locality silently no-opped (leaving that locality with
    no set).
    """
    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)

    geo_layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(
            path="atlantis",
            description="The legendary city of Atlantis",
            source_url="https://en.wikipedia.org/wiki/Atlantis",
        ),
        obj_meta=meta,
        namespace=ns,
    )

    locs, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path=None,
                name="Atlantis",
                aliases=None,
            ),
            schemas.LocalityCreate(
                canonical_path="lemuria",
                parent_path=None,
                name="Lemuria",
                aliases=None,
            ),
        ],
        obj_meta=meta,
    )

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path="central_atlantis", geography=None, internal_point=None),
            schemas.GeographyCreate(path="western_atlantis", geography=None, internal_point=None),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )
    geo_list = [geo[0] for geo in geos]

    def versions(loc):
        return (
            db.query(models.GeoSetVersion)
            .filter(
                models.GeoSetVersion.layer_id == geo_layer.layer_id,
                models.GeoSetVersion.loc_id == loc.loc_id,
            )
            .order_by(models.GeoSetVersion.set_version_id)
            .all()
        )

    map_kwargs = dict(db=db, layer=geo_layer, obj_meta=meta)

    crud.geo_layer.map_locality(locality=locs[0], geographies=geo_list, **map_kwargs)
    assert len(versions(locs[0])) == 1

    # Identical remap: no new version.
    crud.geo_layer.map_locality(locality=locs[0], geographies=geo_list, **map_kwargs)
    assert len(versions(locs[0])) == 1

    # Same members mapped to a different locality get that locality's own set.
    crud.geo_layer.map_locality(locality=locs[1], geographies=geo_list, **map_kwargs)
    assert len(versions(locs[1])) == 1
    assert crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=locs[1]) is not None

    # Changed membership: exactly one new version; the old one is deprecated.
    crud.geo_layer.map_locality(locality=locs[0], geographies=geo_list[:1], **map_kwargs)
    loc0_versions = versions(locs[0])
    assert len(loc0_versions) == 2
    assert loc0_versions[0].valid_to is not None
    current = crud.geo_layer.get_set_by_locality(db=db, layer=geo_layer, locality=locs[0])
    assert current.set_version_id == loc0_versions[1].set_version_id
    assert len(current.members) == 1
