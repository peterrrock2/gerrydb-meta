"""Tests for GerryDB CRUD operations on column metadata."""

import pytest

from gerrydb_meta import crud, models, schemas
from gerrydb_meta.enums import ColumnKind, ColumnType


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


def test_crud_column_create_base(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert col.col_id is not None
    assert col.description == "the mayor of the city"
    assert col.kind == ColumnKind.IDENTIFIER
    assert col.type == ColumnType.STR

    assert col.canonical_ref.path == "mayor"
    assert col.canonical_ref.namespace_id == ns.namespace_id
    assert col.canonical_ref.meta_id == meta.meta_id


def test_crud_column_get_ref(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert crud.column.get_ref(db=db, path="mayor", namespace=ns).col_id == col.col_id
    assert crud.column.get_ref(db=db, path="mayor", namespace=ns) is col.canonical_ref
    assert (
        crud.column.get_global_ref(db=db, path=(None, "mayor"), namespace=ns).col_id == col.col_id
    )
    assert (
        crud.column.get_global_ref(db=db, path=(None, "mayor"), namespace=ns) is col.canonical_ref
    )


def test_crud_column_get(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert crud.column.get(db=db, path="mayor", namespace=ns).col_id == col.col_id
    assert crud.column.get(db=db, path="mayor", namespace=ns) is col


def test_crud_column_get_global_ref(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="mayor",
            description="the mayor of the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert (
        crud.column.get_global_ref(db=db, path=("atlantis", "mayor"), namespace=ns).col_id
        == col.col_id
    )
    assert (
        crud.column.get_global_ref(db=db, path=("atlantis", "mayor"), namespace=ns)
        is col.canonical_ref
    )
    assert (
        crud.column.get_global_ref(db=db, path=("atlantis", "mayor"), namespace=ns).namespace_id
        == ns.namespace_id
    )
    assert (
        crud.column.get_global_ref(db=db, path=("atlantis", "mayor"), namespace=ns).meta_id
        == meta.meta_id
    )
    assert (
        crud.column.get_global_ref(db=db, path=("atlantis", "mayor"), namespace=ns).path == "mayor"
    )


def test_crud_column_set_values(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    # create bulk returns a list of geos and a uuid
    # The geos are (Geography, GeoVersion) pairs
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

    geo_update_values = []
    for i, g in enumerate(geo):
        geo_update_values.append((g[0], 100 + i))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="geo_identifier",
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values,
        obj_meta=meta,
    )

    cols_list = (
        db.query(models.ColumnValue)
        .join(models.ColumnRef, models.ColumnValue.col_id == models.ColumnRef.col_id)
        .filter(models.ColumnRef.path == "geo_identifier")
        .all()
    )
    assert len(cols_list) == 2
    assert cols_list[0].val_int == 100
    assert cols_list[1].val_int == 101

    assert cols_list[0].geo_id == geo[0][0].geo_id
    assert cols_list[1].geo_id == geo[1][0].geo_id

    assert cols_list[0].col_id == col.col_id
    assert cols_list[1].col_id == col.col_id

    assert cols_list[0].val_float is None
    assert cols_list[1].val_float is None

    assert cols_list[0].val_str is None
    assert cols_list[1].val_str is None

    assert cols_list[0].val_bool is None
    assert cols_list[1].val_bool is None


def test_crud_column_set_values__error_dup_geo(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    # create bulk returns a list of geos and a uuid
    # The geos are (Geography, GeoVersion) pairs
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

    geo_update_values = []
    for i, g in enumerate(geo):
        geo_update_values.append((g[0], 100 + i))
    geo_update_values.append((geo[0][0], 200))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="geo_identifier",
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    with pytest.raises(
        ValueError,
        match="Duplicate geography path 'central_atlantis' found.",
    ):
        crud.column.set_values(
            db=db,
            col=col,
            values=geo_update_values,
            obj_meta=meta,
        )


def test_crud_column_update_col_of_each_type(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    # create bulk returns a list of geos and a uuid
    # The geos are (Geography, GeoVersion) pairs
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

    # ==============
    #    TYPE INT
    # ==============

    col_path = "geo_identifier_int"
    col_type = ColumnType.INT

    geo_update_values1 = []
    for i, g in enumerate(geo):
        geo_update_values1.append((g[0], int(100 + i)))
    geo_update_values2 = []
    for i, g in enumerate(geo):
        geo_update_values2.append((g[0], int(200 + i)))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path=col_path,
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=col_type,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values1,
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values2,
        obj_meta=meta,
    )

    cols_list = (
        db.query(models.ColumnValue)
        .join(models.ColumnRef, models.ColumnValue.col_id == models.ColumnRef.col_id)
        .filter(models.ColumnRef.path == col_path)
        .filter(models.ColumnValue.valid_to.is_(None))
        .all()
    )
    assert len(cols_list) == 2
    assert cols_list[0].val_int == 200
    assert cols_list[1].val_int == 201

    assert cols_list[0].geo_id == geo[0][0].geo_id
    assert cols_list[1].geo_id == geo[1][0].geo_id

    assert cols_list[0].col_id == col.col_id
    assert cols_list[1].col_id == col.col_id

    assert cols_list[0].val_float is None
    assert cols_list[1].val_float is None

    assert cols_list[0].val_str is None
    assert cols_list[1].val_str is None

    assert cols_list[0].val_bool is None
    assert cols_list[1].val_bool is None

    # ================
    #    TYPE FLOAT
    # ================

    col_path = "geo_identifier_float"
    col_type = ColumnType.FLOAT

    # The values should silently promote
    geo_update_values1 = []
    for i, g in enumerate(geo):
        geo_update_values1.append((g[0], int(100 + i)))
    geo_update_values2 = []
    for i, g in enumerate(geo):
        geo_update_values2.append((g[0], int(200 + i)))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path=col_path,
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=col_type,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values1,
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values2,
        obj_meta=meta,
    )

    cols_list = (
        db.query(models.ColumnValue)
        .join(models.ColumnRef, models.ColumnValue.col_id == models.ColumnRef.col_id)
        .filter(models.ColumnRef.path == col_path)
        .filter(models.ColumnValue.valid_to.is_(None))
        .all()
    )
    assert len(cols_list) == 2
    assert cols_list[0].val_int is None
    assert cols_list[1].val_int is None

    assert cols_list[0].geo_id == geo[0][0].geo_id
    assert cols_list[1].geo_id == geo[1][0].geo_id

    assert cols_list[0].col_id == col.col_id
    assert cols_list[1].col_id == col.col_id

    assert cols_list[0].val_float == 200.0
    assert cols_list[1].val_float == 201.0

    assert cols_list[0].val_str is None
    assert cols_list[1].val_str is None

    assert cols_list[0].val_bool is None
    assert cols_list[1].val_bool is None

    # ==============
    #    TYPE STR
    # ==============

    col_path = "geo_identifier_str"
    col_type = ColumnType.STR

    geo_update_values1 = []
    for i, g in enumerate(geo):
        geo_update_values1.append((g[0], str(100 + i)))
    geo_update_values2 = []
    for i, g in enumerate(geo):
        geo_update_values2.append((g[0], str(200 + i)))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path=col_path,
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=col_type,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values1,
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values2,
        obj_meta=meta,
    )

    cols_list = (
        db.query(models.ColumnValue)
        .join(models.ColumnRef, models.ColumnValue.col_id == models.ColumnRef.col_id)
        .filter(models.ColumnRef.path == col_path)
        .filter(models.ColumnValue.valid_to.is_(None))
        .all()
    )
    assert len(cols_list) == 2
    assert cols_list[0].val_int is None
    assert cols_list[1].val_int is None

    assert cols_list[0].geo_id == geo[0][0].geo_id
    assert cols_list[1].geo_id == geo[1][0].geo_id

    assert cols_list[0].col_id == col.col_id
    assert cols_list[1].col_id == col.col_id

    assert cols_list[0].val_float is None
    assert cols_list[1].val_float is None

    assert cols_list[0].val_str == "200"
    assert cols_list[1].val_str == "201"

    assert cols_list[0].val_bool is None
    assert cols_list[1].val_bool is None

    # ===============
    #    TYPE BOOL
    # ===============

    col_path = "geo_identifier_bool"
    col_type = ColumnType.BOOL

    geo_update_values1 = []
    for i, g in enumerate(geo):
        geo_update_values1.append((g[0], False))
    geo_update_values2 = []
    for i, g in enumerate(geo):
        geo_update_values2.append((g[0], True))

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path=col_path,
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=col_type,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values1,
        obj_meta=meta,
    )

    crud.column.set_values(
        db=db,
        col=col,
        values=geo_update_values2,
        obj_meta=meta,
    )

    cols_list = (
        db.query(models.ColumnValue)
        .join(models.ColumnRef, models.ColumnValue.col_id == models.ColumnRef.col_id)
        .filter(models.ColumnRef.path == col_path)
        .filter(models.ColumnValue.valid_to.is_(None))
        .all()
    )
    assert len(cols_list) == 2
    assert cols_list[0].val_int is None
    assert cols_list[1].val_int is None

    assert cols_list[0].geo_id == geo[0][0].geo_id
    assert cols_list[1].geo_id == geo[1][0].geo_id

    assert cols_list[0].col_id == col.col_id
    assert cols_list[1].col_id == col.col_id

    assert cols_list[0].val_float is None
    assert cols_list[1].val_float is None

    assert cols_list[0].val_str is None
    assert cols_list[1].val_str is None

    assert cols_list[0].val_bool
    assert cols_list[1].val_bool


def test_crud_column_patch(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="geo_identifier",
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.INT,
            aliases=None,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    data_col, _ = crud.column.patch(
        db=db,
        obj=col,
        obj_meta=meta,
        patch=schemas.ColumnPatch(aliases=["foo-bar"]),
    )

    refs_lst = []
    for col_ref in data_col.refs:
        refs_lst.append(col_ref.path)

    assert "foo-bar" in refs_lst
    assert "geo_identifier" in refs_lst


import logging


def test_crud_column_patch_with_existing_aliases(db_with_meta, caplog):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    caplog.set_level(logging.INFO, logger="uvicorn.error")

    col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="geo_identifier",
            description="an identifier number for the region",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.INT,
            aliases=["foo-bar"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    _ = crud.column.patch(
        db=db,
        obj=col,
        obj_meta=meta,
        patch=schemas.ColumnPatch(aliases=["foo-bar"]),
    )
    data_col, _ = crud.column.patch(
        db=db,
        obj=col,
        obj_meta=meta,
        patch=schemas.ColumnPatch(aliases=["foo-bar", "bar-baz"]),
    )

    refs_lst = []
    for col_ref in data_col.refs:
        refs_lst.append(col_ref.path)

    assert set(refs_lst) == set(["foo-bar", "bar-baz", "geo_identifier"])
