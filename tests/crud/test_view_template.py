import pytest

from gerrydb_meta import crud, schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
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


def test_view_template_create(db_with_meta):
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

    crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    city_col = crud.column.get_ref(db=db, path="city", namespace=ns)

    view, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template",
            description="template for viewing mayor power",
            members=["mayor_power"],
        ),
        resolved_members=[city_col, col_set],
        obj_meta=meta,
        namespace=ns,
    )

    assert len(view.columns) == 1
    assert len(view.column_sets) == 1
    assert view.columns[0].member.path == "city"
    assert view.column_sets[0].member.path == "mayor_power"


def test_view_template_get(db_with_meta):
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

    crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="population",
            description="the population of the city",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="mayor_power",
            description="how many people the mayor controls",
            columns=["mayor", "population"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    city_col = crud.column.get_ref(db=db, path="city", namespace=ns)

    view, _uuid = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="mayor_power_template",
            description="template for viewing mayor power",
            members=["mayor_power"],
        ),
        resolved_members=[city_col, col_set],
        obj_meta=meta,
        namespace=ns,
    )

    retrieved_view = crud.view_template.get(db=db, path="mayor_power_template", namespace=ns)

    assert retrieved_view.template_version_id == view.template_version_id
    assert retrieved_view.template_id == view.template_id
    assert retrieved_view.valid_from == view.valid_from
    assert retrieved_view.valid_to == view.valid_to
    assert retrieved_view.meta_id == view.meta_id
    assert retrieved_view.columns == view.columns
    assert retrieved_view.column_sets == view.column_sets


def test_view_template_error_bad_resolved_members(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    with pytest.raises(
        CreateValueError,
        match="View templates may only contain columns and column sets.",
    ):
        _ = crud.view_template.create(
            db=db,
            obj_in=schemas.ViewTemplateCreate(
                path="mayor_power_template",
                description="template for viewing mayor power",
                members=["mayor_power"],
            ),
            resolved_members=["bad"],
            obj_meta=meta,
            namespace=ns,
        )


import logging


def test_view_template_error_duplicate_columns(db_with_meta, caplog):
    db, meta = db_with_meta

    caplog.set_level(logging.INFO, logger="uvicorn")

    ns = make_atlantis_ns(db, meta)

    with pytest.raises(
        CreateValueError,
        match="View templates may only contain columns and column sets.",
    ):
        _ = crud.view_template.create(
            db=db,
            obj_in=schemas.ViewTemplateCreate(
                path="mayor_power_template",
                description="template for viewing mayor power",
                members=["mayor_power"],
            ),
            resolved_members=["bad"],
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
            aliases=["ct"],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    city_col = crud.column.get_ref(db=db, path="city", namespace=ns)

    with pytest.raises(
        CreateValueError,
        match="the following column was referenced elsewhere",
    ):
        _ = crud.view_template.create(
            db=db,
            obj_in=schemas.ViewTemplateCreate(
                path="mayor_power_template",
                description="template for viewing mayor power",
                members=["mayor_power"],
            ),
            resolved_members=[city_col, city_col],
            obj_meta=meta,
            namespace=ns,
        )

    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="city_set",
            description="A really silly column set",
            columns=[
                "city",
            ],
        ),
        obj_meta=meta,
        namespace=ns,
    )

    with pytest.raises(
        CreateValueError,
        match=(
            "in column set 'city_set' that was previously added or appears in another column set."
        ),
    ):
        _ = crud.view_template.create(
            db=db,
            obj_in=schemas.ViewTemplateCreate(
                path="weeee",
                description="a silly template",
                members=["/columns/city", "/column_sets/city_set"],
            ),
            resolved_members=[city_col, col_set],
            obj_meta=meta,
            namespace=ns,
        )
