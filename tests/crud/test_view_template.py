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

    direct_members = [m for m in view.columns if m.direct]
    synthesized = [m for m in view.columns if not m.direct]
    assert len(direct_members) == 1
    assert direct_members[0].member.path == "city"
    assert direct_members[0].col_id == city_col.col_id
    # Set members are pinned as hidden rows so data resolution survives ref
    # repointing; the set itself remains the authored member.
    assert {m.member.path for m in synthesized} == {"mayor", "population"}
    assert all(m.col_id == m.member.col_id for m in view.columns)
    assert len(view.column_sets) == 1
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


def _make_two_columns_and_set(db, meta, ns):
    cols = {}
    for path in ("alpha", "beta"):
        col, _ = crud.column.create(
            db=db,
            obj_in=schemas.ColumnCreate(
                canonical_path=path,
                description=path,
                kind=ColumnKind.COUNT,
                type=ColumnType.INT,
            ),
            obj_meta=meta,
            namespace=ns,
        )
        cols[path] = col
    col_set, _ = crud.column_set.create(
        db=db,
        obj_in=schemas.ColumnSetCreate(
            path="ab_set",
            description="alpha and beta",
            columns=["alpha", "beta"],
        ),
        obj_meta=meta,
        namespace=ns,
    )
    return cols, col_set


def test_view_template_set_members_pinned_and_hidden(db_with_meta):
    """Set-derived pins carry data resolution but stay out of the serialized
    member list, and a version created after a ref repoint resolves the new
    column through the same, unmodified column set."""
    db, meta = db_with_meta
    ns = make_atlantis_ns(db, meta)
    cols, col_set = _make_two_columns_and_set(db, meta, ns)

    version, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="set_only_template",
            description="only a set",
            members=["ab_set"],
        ),
        resolved_members=[col_set],
        obj_meta=meta,
        namespace=ns,
    )

    assert all(not m.direct for m in version.columns)
    assert {m.col_id for m in version.columns} == {c.col_id for c in cols.values()}
    # The set's authored order is inherited by its hidden pin rows.
    assert all(m.order == 0 for m in version.columns)

    serialized = schemas.ViewTemplate.from_attributes(version)
    assert [type(m).__name__ for m in serialized.members] == ["ColumnSet"]

    # Repoint alpha's canonical ref (as materialization would) and create a
    # new version from the SAME set: the old version keeps its pin, the new
    # version picks up the repointed column.
    gamma, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="gamma",
            description="replacement for alpha",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=ns,
    )
    alpha_ref = cols["alpha"].canonical_ref
    alpha_ref.col_id = gamma.col_id
    db.flush()
    db.expire(alpha_ref)

    version2, _ = crud.view_template.create(
        db=db,
        obj_in=schemas.ViewTemplateCreate(
            path="set_only_template_v2",
            description="same set, after repoint",
            members=["ab_set"],
        ),
        resolved_members=[col_set],
        obj_meta=meta,
        namespace=ns,
    )

    assert {m.col_id for m in version.columns} == {
        cols["alpha"].col_id,
        cols["beta"].col_id,
    }
    assert {m.col_id for m in version2.columns} == {gamma.col_id, cols["beta"].col_id}
