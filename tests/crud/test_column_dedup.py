"""Tests for value-hash maintenance, duplicate detection, and column references."""

import pytest

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.exceptions import CreateValueError
from gerrydb_meta.value_hash import pair_digest, xor_fold


def _fixture(db, meta, ns_path="hashns", public=True):
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path=ns_path, description="t", public=public),
        obj_meta=meta,
    )
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)
    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path=f"g{i}", geography=None, internal_point=None)
            for i in range(4)
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=ns,
    )
    geos = [g[0] for g in geos]
    layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(path="hlayer", description="t"),
        obj_meta=meta,
        namespace=ns,
    )
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[schemas.LocalityCreate(canonical_path=f"{ns_path}-loc", name=f"{ns_path} loc")],
        obj_meta=meta,
    )
    crud.geo_layer.map_locality(db=db, layer=layer, locality=loc[0], geographies=geos, obj_meta=meta)
    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="pop", description="t", kind=ColumnKind.COUNT, type=ColumnType.INT
        ),
        obj_meta=meta,
        namespace=ns,
    )
    return ns, geos, layer, loc[0], col


def _stored_hash(db, col):
    row = (
        db.query(models.ColumnValueCount)
        .filter_by(col_id=col.col_id)
        .filter(models.ColumnValueCount.value_hash_hi.isnot(None))
        .one()
    )
    return row.value_hash_hi, row.value_hash_lo, row.count


def test_set_values_maintains_hash_and_partial_overlap(db_with_meta):
    db, meta = db_with_meta
    ns, geos, layer, loc, col = _fixture(db, meta)

    crud.column.set_values(
        db, col=col, values=[(geos[0], 10), (geos[1], 20)], obj_meta=meta
    )
    hi, lo, count = _stored_hash(db, col)
    expect = xor_fold(
        [pair_digest(geos[0].path, ColumnType.INT, 10), pair_digest(geos[1].path, ColumnType.INT, 20)]
    )
    assert (hi, lo) == expect and count == 2

    # Partial overlap: one changed, one unchanged, one fresh. This tripped an
    # assertion before graceful set logic.
    crud.column.set_values(
        db, col=col, values=[(geos[1], 25), (geos[0], 10), (geos[2], 30)], obj_meta=meta
    )
    hi, lo, count = _stored_hash(db, col)
    expect = xor_fold(
        [
            pair_digest(geos[0].path, ColumnType.INT, 10),
            pair_digest(geos[1].path, ColumnType.INT, 25),
            pair_digest(geos[2].path, ColumnType.INT, 30),
        ]
    )
    assert (hi, lo) == expect and count == 3


def test_find_duplicate_and_reference(db_with_meta):
    db, meta = db_with_meta
    ns, geos, layer, loc, col = _fixture(db, meta, ns_path="pubns", public=True)
    values = [(g, i * 7) for i, g in enumerate(geos)]
    crud.column.set_values(db, col=col, values=values, obj_meta=meta)
    digests = [pair_digest(g.path, ColumnType.INT, v) for g, v in values]
    hi, lo = xor_fold(digests)

    match = crud.column.find_duplicate(
        db,
        name="pop",
        locality_path="pubns-loc",
        layer_path="hlayer",
        hash_hi=hi,
        hash_lo=lo,
        readable_namespace_ids=[ns.namespace_id],
    )
    assert match is not None and match.col_id == col.col_id
    assert (
        crud.column.find_duplicate(
            db,
            name="pop",
            locality_path="pubns-loc",
            layer_path="hlayer",
            hash_hi=hi ^ 1,
            hash_lo=lo,
            readable_namespace_ids=[ns.namespace_id],
        )
        is None
    )

    # Reference from another namespace to the public column.
    user_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="userns", description="t", public=False),
        obj_meta=meta,
    )
    ref, _ = crud.column.create_reference(
        db, path="my_pop", namespace=user_ns, col=col, obj_meta=meta
    )
    assert ref.col_id == col.col_id and ref.namespace_id == user_ns.namespace_id
    # Duplicate ref path rejected.
    with pytest.raises(CreateValueError):
        crud.column.create_reference(
            db, path="my_pop", namespace=user_ns, col=col, obj_meta=meta
        )


def test_reference_to_private_namespace_rejected(db_with_meta):
    db, meta = db_with_meta
    ns, geos, layer, loc, col = _fixture(db, meta, ns_path="privns", public=False)
    other, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="otherns", description="t", public=True),
        obj_meta=meta,
    )
    with pytest.raises(CreateValueError):
        crud.column.create_reference(
            db, path="stolen", namespace=other, col=col, obj_meta=meta
        )
