import hashlib

import pytest
import shapely
from geoalchemy2 import WKBElement
from shapely import Point, Polygon, wkb
from shapely.geometry import box

from gerrydb_meta import crud, schemas
from gerrydb_meta.crud.geography import GEO_GRID_SIZE
from gerrydb_meta.exceptions import *

square_corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]

square = Polygon(square_corners)

internal_point = Point(0.0, 0.0)


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


def test_crud_geography_create_bulk(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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

    assert geo[0][0].path == "central_atlantis"
    assert geo[1][0].path == "western_atlantis"

    assert set(
        crud.geography._CRGeography__get_existing_paths(
            db,
            obj_paths=["central_atlantis", "western_atlantis", "does_not_exist"],
            namespace=ns,
        )
    ) == set(["central_atlantis", "western_atlantis"])


def test_crud_geography_create_bulk_redundant_fail(db_with_meta):
    with pytest.raises(BulkCreateError) as e:
        db, meta = db_with_meta
        ns = make_atlantis_ns(db, meta)

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
                    path="central_atlantis",
                    geography=square.wkb,
                    internal_point=None,
                ),
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=ns,
        )

    assert e.value.paths == ["central_atlantis", "central_atlantis"]
    assert str(e.value) == "Cannot create geographies with duplicate paths."


def test_crud_geography_create_bulk_already_exist_fail(db_with_meta):
    with pytest.raises(BulkCreateError) as e:
        db, meta = db_with_meta
        ns = make_atlantis_ns(db, meta)

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(
                    path="central_atlantis",
                    geography=None,
                    internal_point=None,
                ),
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=ns,
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
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=ns,
        )

    assert e.value.paths == ["central_atlantis"]
    assert str(e.value) == "Cannot create geographies that already exist."


def test_crud_geography_create_bulk_wkb_fail(db_with_meta):
    with pytest.raises(Exception) as e:
        db, meta = db_with_meta
        ns = make_atlantis_ns(db, meta)

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(
                    path="central_atlantis", geography=b"4", internal_point=None
                ),
            ],
            geo_import=geo_import,
            namespace=ns,
            obj_meta=meta,
        )

    assert str(e.value) == (
        "Failed to insert geometries. This is likely due to invalid Geometries; please ensure "
        "geometries can be encoded in WKB format."
    )


def test_crud_geography_create_bulk_not_wkb_converted_fail(db_with_meta):
    with pytest.raises(Exception) as e:
        db, meta = db_with_meta
        ns = make_atlantis_ns(db, meta)

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(
                    path="central_atlantis", geography=square, internal_point=None
                ),
            ],
            geo_import=geo_import,
            namespace=ns,
            obj_meta=meta,
        )
    assert "Value error, The geography must be of type bytes, got type Polygon" in str(e.value)


def test_crud_geography_patch_bulk_vacuous_update(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.patch_bulk(
        db=db,
        objs_in=[
            schemas.GeographyPatch(
                path="central_atlantis",
                geography=None,
                internal_point=None,
            ),
        ],
        geo_import=geo_import,
        namespace=ns,
    )

    assert geo[0][1].geography == WKBElement(Polygon().wkb, srid=4269)


def test_crud_geography_patch_bulk_redundant_update_fail(db_with_meta):
    with pytest.raises(BulkPatchError) as e:
        db, meta = db_with_meta

        ns = make_atlantis_ns(db, meta)

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(
                    path="central_atlantis",
                    geography=None,
                    internal_point=None,
                ),
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=ns,
        )

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.patch_bulk(
            db=db,
            objs_in=[
                schemas.GeographyPatch(
                    path="central_atlantis",
                    geography=None,
                    internal_point=None,
                ),
                schemas.GeographyPatch(
                    path="central_atlantis",
                    geography=None,
                    internal_point=None,
                ),
            ],
            geo_import=geo_import,
            namespace=ns,
        )
    assert e.value.paths == ["central_atlantis", "central_atlantis"]
    assert str(e.value) == "Cannot patch geographies with duplicate paths."


def test_crud_geography_patch_bulk_not_exist_fail(db_with_meta):
    with pytest.raises(BulkPatchError) as e:
        db, meta = db_with_meta

        ns = make_atlantis_ns(db, meta)

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.create_bulk(
            db=db,
            objs_in=[
                schemas.GeographyCreate(
                    path="central_atlantis",
                    geography=None,
                    internal_point=None,
                ),
            ],
            obj_meta=meta,
            geo_import=geo_import,
            namespace=ns,
        )

        geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

        geo, _ = crud.geography.patch_bulk(
            db=db,
            objs_in=[
                schemas.GeographyPatch(
                    path="western_atlantis",
                    geography=None,
                    internal_point=None,
                ),
            ],
            geo_import=geo_import,
            namespace=ns,
        )
    assert e.value.paths == ["western_atlantis"]
    assert str(e.value) == "Cannot update geographies that do not exist."


def test_crud_geography_patch_bulk_all_squares(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

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

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.patch_bulk(
        db=db,
        objs_in=[
            schemas.GeographyPatch(
                path="central_atlantis",
                geography=square.wkb,
                internal_point=internal_point.wkb,
            ),
            schemas.GeographyPatch(
                path="western_atlantis",
                geography=square.wkb,
                internal_point=internal_point.wkb,
            ),
        ],
        geo_import=geo_import,
        namespace=ns,
    )

    assert wkb.loads(geo[0][1].geography.desc) == square


def test_crud_geography_patch_bulk_errors_nonemtpy_to_empty(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geo, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="central_atlantis",
                geography=box(0, 0, 1, 1).wkb,
                internal_point=Point(0, 0).wkb,
            ),
            schemas.GeographyCreate(
                path="western_atlantis",
                geography=box(0, 0, 1, 1).wkb,
                internal_point=Point(0, 0).wkb,
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    with pytest.raises(
        BulkPatchError,
        match=(
            "When updating geographies, found that some new geographies are empty polygons when "
            "a previous version of the same geography in the target namespace was not empty. To "
            "allow for this, set the `allow_empty_polys` parameter to `True`."
        ),
    ):
        _ = crud.geography.patch_bulk(
            db=db,
            objs_in=[
                schemas.GeographyPatch(
                    path="central_atlantis",
                    geography=Polygon().wkb,
                    internal_point=Point().wkb,
                ),
            ],
            geo_import=geo_import,
            namespace=ns,
        )


def test_crud_geography_geometry_hash_canary(db_with_meta):
    """Cross-stack canonical-WKB hash canary.

    geo_bin dedup relies on md5(shapely WKB of the grid-snapped geometry)
    matching the server's generated column md5(ST_AsBinary(geography)) byte
    for byte, with both sides snapping to the same 1e-6 degree grid before
    hashing. The constants below are shared with the client suite's canary; if
    either assertion fails, a shapely/GEOS/PostGIS upgrade changed WKB
    serialization or precision reduction, and uploads would stop deduplicating
    against previously stored geometries.

    The awkward fixture has 7-decimal coordinates, so its canonical hash
    differs from its raw hash: it also pins that the server snaps before
    hashing and storage.
    """
    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    awkward = Polygon(
        [(-71.1234567, 42.7654321), (-70.9876543, 42.7654329), (-70.9876543, 43.0123456)]
    )
    fixtures = {
        "empty_canary": (Polygon(), "75b6f320f5eb33d79cbcd9cf62be5a83"),
        "awkward_canary": (awkward, "f05ebab893ed6babfebd1bbbe1693be9"),
    }

    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path=path, geography=poly.wkb, internal_point=None)
            for path, (poly, _) in fixtures.items()
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    for geo, version in geos:
        poly, expected = fixtures[geo.path]
        canonical = poly if poly.is_empty else shapely.set_precision(poly, GEO_GRID_SIZE, mode="pointwise")
        # Client-side hash of the canonical bytes (what upload dedup computes)...
        assert hashlib.md5(canonical.wkb).hexdigest() == expected
        # ...must equal the server-side generated column for the stored bytes.
        assert version.geo_bin.geometry_hash.hex() == expected

    # The raw 7-decimal bytes must NOT be what got stored.
    assert (
        hashlib.md5(fixtures["awkward_canary"][0].wkb).hexdigest()
        != fixtures["awkward_canary"][1]
    )


def test_crud_geography_empty_polygons_keep_distinct_internal_points(db_with_meta):
    """Hash-identical geometries share a bin, but each geography keeps its own
    internal point (points used to live on the shared bin, so all empty
    polygons aliased to the first upload's point)."""
    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(
                path="empty_a", geography=None, internal_point=Point(1.0, 1.0).wkb
            ),
            schemas.GeographyCreate(
                path="empty_b", geography=None, internal_point=Point(2.0, 2.0).wkb
            ),
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )

    versions = {geo.path: version for geo, version in geos}
    assert versions["empty_a"].geo_bin_id == versions["empty_b"].geo_bin_id
    point_a = wkb.loads(bytes(versions["empty_a"].internal_point.data))
    point_b = wkb.loads(bytes(versions["empty_b"].internal_point.data))
    assert point_a == Point(1.0, 1.0)
    assert point_b == Point(2.0, 2.0)
