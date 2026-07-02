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


def test_crud_column_set_create_base(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    crud.column.create(
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

    crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="city",
            description="the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="a_set_of_columns",
            description="just a good ol' set of columns",
            columns=["mayor", "city"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    set_id = (
        db.query(models.ColumnSet)
        .filter(models.ColumnSet.path == "a_set_of_columns")
        .first()
        .set_id
    )

    assert col_set.set_id == set_id
    assert col_set.columns[0].set_id == set_id
    assert col_set.columns[1].set_id == set_id

    assert (
        col_set.columns[0].ref_id
        == db.query(models.ColumnRef)
        .filter(models.ColumnRef.path == col_set.columns[0].ref.path)
        .first()
        .ref_id
    )
    assert (
        col_set.columns[1].ref_id
        == db.query(models.ColumnRef)
        .filter(models.ColumnRef.path == col_set.columns[1].ref.path)
        .first()
        .ref_id
    )


def test_crud_column_set_get(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    crud.column.create(
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

    crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="city",
            description="the city",
            kind=ColumnKind.IDENTIFIER,
            type=ColumnType.STR,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="a_set_of_columns",
            description="just a good ol' set of columns",
            columns=["mayor", "city"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    assert crud.column_set.get(db=db, path="a_set_of_columns", namespace=ns) == col_set
