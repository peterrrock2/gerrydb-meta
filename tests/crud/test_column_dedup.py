"""Tests for value-hash maintenance, duplicate detection, and column references."""

import pytest
from sqlalchemy import text as sa_text

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


def test_map_locality_seeds_correct_hash_for_prevalued_geos(db_with_meta):
    """F1 regression: mapping already-valued geographies into a NEW set
    version seeds the full-column fingerprint, not NULL (which a later
    partial write would corrupt). Covers all four stored value types."""
    from gerrydb_meta.value_hash import pair_digest, xor_fold

    db, meta = db_with_meta
    ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="f1ns", description="t", public=True),
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

    specs = [
        (ColumnType.INT, [3, 7, 11, 13]),
        (ColumnType.STR, ["a", "bb", "ccc", "dddd"]),
        (ColumnType.FLOAT, [1.5, 2.25, -3.0, 0.0]),
        (ColumnType.BOOL, [True, False, True, False]),
    ]
    cols = []
    for i, (ctype, vals) in enumerate(specs):
        col, _ = crud.column.create(
            db=db,
            obj_in=schemas.ColumnCreate(
                canonical_path=f"c{i}", description="t", kind=ColumnKind.COUNT, type=ctype
            ),
            obj_meta=meta,
            namespace=ns,
        )
        crud.column.set_values(
            db, col=col, values=list(zip(geos, vals)), obj_meta=meta
        )
        cols.append((col, ctype, vals))

    # Now map these already-valued geographies into a NEW set version.
    layer, _ = crud.geo_layer.create(
        db=db,
        obj_in=schemas.GeoLayerCreate(path="f1layer", description="t"),
        obj_meta=meta,
        namespace=ns,
    )
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[schemas.LocalityCreate(canonical_path="f1-loc", name="f1 loc")],
        obj_meta=meta,
    )
    crud.geo_layer.map_locality(db=db, layer=layer, locality=loc[0], geographies=geos, obj_meta=meta)
    sv = crud.geo_layer.get_set_by_locality(db=db, layer=layer, locality=loc[0])

    for col, ctype, vals in cols:
        row = (
            db.query(models.ColumnValueCount)
            .filter_by(col_id=col.col_id, set_version_id=sv.set_version_id)
            .one()
        )
        expect = xor_fold([pair_digest(g.path, ctype, v) for g, v in zip(geos, vals)])
        assert row.count == 4
        assert (row.value_hash_hi, row.value_hash_lo) == expect, ctype


def test_missing_value_paths_and_cross_namespace_refs(db_with_meta):
    """Clone validation surfaces source-valued paths absent from the target,
    and cross-namespace refs list only refs that leave the namespace."""
    db, meta = db_with_meta
    src_ns, src_geos, _, _, src_col = _fixture(db, meta, ns_path="clonesrc")
    crud.column.set_values(
        db=db,
        col=src_col,
        values=[(g, i) for i, g in enumerate(src_geos)],
        obj_meta=meta,
    )

    tgt, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="clonetgt", description="t", public=True),
        obj_meta=meta,
    )
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=tgt)
    crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path=f"g{i}", geography=None, internal_point=None)
            for i in range(3)
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=tgt,
    )

    assert crud.column.missing_value_paths(db, col=src_col, namespace=tgt) == ["g3"]

    crud.geography.create_bulk(
        db=db,
        objs_in=[schemas.GeographyCreate(path="g3", geography=None, internal_point=None)],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=tgt,
    )
    assert crud.column.missing_value_paths(db, col=src_col, namespace=tgt) == []

    ref, _ = crud.column.create_reference(
        db, path="pop", namespace=tgt, col=src_col, obj_meta=meta
    )
    tgt_refs = crud.column.cross_namespace_refs(db, namespace=tgt)
    assert [r.ref_id for r in tgt_refs] == [ref.ref_id]
    assert crud.column.cross_namespace_refs(db, namespace=src_ns) == []


def test_materialize_clone_copies_values_and_repoints(db_with_meta):
    """Materialization: values land on target geo_ids, stats refold to the
    source fingerprint, every same-source ref in the namespace repoints, and
    same-namespace aliases refuse."""
    db, meta = db_with_meta
    src_ns, src_geos, _, _, src_col = _fixture(db, meta, ns_path="matsrc")
    crud.column.set_values(
        db=db,
        col=src_col,
        values=[(g, i * 10) for i, g in enumerate(src_geos)],
        obj_meta=meta,
    )

    tgt_ns, tgt_geos, _, _, _ = _fixture(db, meta, ns_path="mattgt")

    clone1, _ = crud.column.create_reference(
        db, path="borrowed", namespace=tgt_ns, col=src_col, obj_meta=meta
    )
    clone2, _ = crud.column.create_reference(
        db, path="borrowed_alias", namespace=tgt_ns, col=src_col, obj_meta=meta
    )

    new_col, _ = crud.column.materialize(db, ref=clone1, obj_meta=meta)
    assert new_col.namespace_id == tgt_ns.namespace_id
    assert new_col.canonical_ref_id == clone1.ref_id
    assert (new_col.kind, new_col.type) == (src_col.kind, src_col.type)

    # Values were copied onto the TARGET namespace's geo_ids, path-mapped.
    rows = db.execute(
        sa_text(
            "SELECT g.path, cv.val_int FROM gerrydb.column_value cv "
            "JOIN gerrydb.geography g ON g.geo_id = cv.geo_id "
            f"WHERE cv.col_id = {new_col.col_id} AND cv.valid_to IS NULL"
        )
    ).all()
    tgt_geo_ids = {g.geo_id for g in tgt_geos}
    assert {r.path: r.val_int for r in rows} == {f"g{i}": i * 10 for i in range(4)}
    copied_geo_ids = set(
        db.execute(
            sa_text(f"SELECT geo_id FROM gerrydb.column_value WHERE col_id = {new_col.col_id}")
        ).scalars()
    )
    assert copied_geo_ids <= tgt_geo_ids

    # Stats: the refold over target sets reproduces the source fingerprint.
    src_stats = (
        db.query(models.ColumnValueCount)
        .filter_by(col_id=src_col.col_id)
        .filter(models.ColumnValueCount.value_hash_hi.isnot(None))
        .one()
    )
    tgt_stats = (
        db.query(models.ColumnValueCount)
        .filter_by(col_id=new_col.col_id)
        .one()
    )
    assert tgt_stats.count == src_stats.count == 4
    assert tgt_stats.value_hash_hi == src_stats.value_hash_hi
    assert tgt_stats.value_hash_lo == src_stats.value_hash_lo

    # Both same-source refs in the namespace repointed; source untouched.
    db.refresh(clone1)
    db.refresh(clone2)
    assert clone1.col_id == new_col.col_id
    assert clone2.col_id == new_col.col_id
    assert src_col.canonical_ref.col_id == src_col.col_id

    # Same-namespace references (aliases) refuse.
    alias, _ = crud.column.create_reference(
        db, path="src_alias", namespace=src_ns, col=src_col, obj_meta=meta
    )
    with pytest.raises(CreateValueError, match="cross-namespace"):
        crud.column.materialize(db, ref=alias, obj_meta=meta)
