"""Tests for GerryDB REST API column value endpoints."""

from http import HTTPStatus

import pytest

from gerrydb_meta.enums import ColumnType
from gerrydb_meta.main import API_PREFIX
from tests.api import create_column, create_geo, get_column_values

COLUMNS_ROOT = f"{API_PREFIX}/columns"


@pytest.mark.parametrize(
    "typed_vals",
    [
        (ColumnType.INT, -1, 1),
        (ColumnType.FLOAT, 1.0, 3.141592653589793),
        (ColumnType.BOOL, True, False),
        (ColumnType.STR, "", "abc"),
    ],
    ids=("int", "float", "bool", "str"),
)
def test_api_column_value_set__two_geos(ctx_public_namespace_read_write, typed_vals):
    col_type, val1, val2 = typed_vals
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    col_obj = create_column(ctx, "col", col_type=col_type)
    create_geo(ctx, "geo1")
    create_geo(ctx, "geo2")

    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[
            {"path": f"/{namespace}/geo1", "value": val1},
            {"path": f"/{namespace}/geo2", "value": val2},
        ],
    )
    assert put_response.status_code == HTTPStatus.NO_CONTENT, put_response.json()

    # This is a bit of a hack: without rendering a view, we can't get the inserted
    # values directly back from the API, so we query the database directly.
    inserted_values = get_column_values(ctx, col_obj)
    assert inserted_values["geo1"] == val1
    assert inserted_values["geo2"] == val2


@pytest.mark.parametrize(
    "typed_vals",
    [
        (ColumnType.INT, ("abc", 1.0, {"key": "value"})),
        (ColumnType.FLOAT, ("abc", {"key": "value"})),
        (ColumnType.BOOL, ("abc", 1.0, {"key": "value"})),
        (ColumnType.STR, (1, 1.0, True, {"key": "value"})),
    ],
    ids=("int", "float", "bool", "str"),
)
def test_api_column_value_set__bad_values(ctx_public_namespace_read_write, typed_vals):
    col_type, vals = typed_vals
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "col", col_type=col_type)
    for idx in range(len(vals)):
        create_geo(ctx, f"geo{idx}")

    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": f"/{namespace}/geo{idx}", "value": value} for idx, value in enumerate(vals)],
    )

    err = put_response.json()
    assert put_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, err
    assert "Type errors" in err["detail"]
    assert len(err["errors"]) == len(vals)


def test_api_column_value_set__int_to_float(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    col_obj = create_column(ctx, "col", col_type=ColumnType.FLOAT)
    create_geo(ctx, "geo")

    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": f"/{namespace}/geo", "value": 2}],
    )
    assert put_response.status_code == HTTPStatus.NO_CONTENT, put_response.json()

    inserted_values = get_column_values(ctx, col_obj)
    assert inserted_values["geo"] == 2.0


def test_api_column_value_set__nonexistent_col(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_geo(ctx, "geo")

    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": f"/{namespace}/geo", "value": 1}],
    )

    err = put_response.json()
    assert put_response.status_code == HTTPStatus.NOT_FOUND, err
    assert "Column not found" in err["detail"]


def test_api_column_value_set__nonexistent_geo(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    col_obj = create_column(ctx, "col", col_type=ColumnType.FLOAT)
    bad_geo_path = f"/{namespace}/geo"
    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": bad_geo_path, "value": 2}],
    )

    err = put_response.json()
    assert put_response.status_code == HTTPStatus.NOT_FOUND, err
    assert bad_geo_path in err["detail"]

    assert get_column_values(ctx, col_obj) == {}


def test_api_column_value_set__public_col_private_geo(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
):
    public_ctx = ctx_public_namespace_read_write
    private_ctx = ctx_private_namespace_read_write
    public_namespace = public_ctx.namespace.path
    private_namespace = private_ctx.namespace.path

    public_col = create_column(public_ctx, "col")
    create_geo(private_ctx, "geo")

    put_response = public_ctx.client.put(
        f"{COLUMNS_ROOT}/{public_namespace}/col",
        json=[{"path": f"/{private_namespace}/geo", "value": 2}],
    )

    err = put_response.json()
    assert put_response.status_code == HTTPStatus.NOT_FOUND, err
    assert private_namespace in err["detail"]

    assert get_column_values(public_ctx, public_col) == {}


def test_api_column_value_set__private_col_public_geo(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
):
    public_ctx = ctx_public_namespace_read_write
    private_ctx = ctx_private_namespace_read_write
    public_namespace = public_ctx.namespace.path
    private_namespace = private_ctx.namespace.path

    private_col = create_column(private_ctx, "col")
    create_geo(public_ctx, "geo")

    put_response = public_ctx.client.put(
        f"{COLUMNS_ROOT}/{private_namespace}/col",
        json=[{"path": f"/{public_namespace}/geo", "value": 2}],
    )

    err = put_response.json()
    assert put_response.status_code == HTTPStatus.NOT_FOUND, err
    assert "Namespace not found" in err["detail"]

    assert get_column_values(private_ctx, private_col) == {}


def test_api_column_value_set__update(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    col_obj = create_column(ctx, "col")
    create_geo(ctx, "geo")

    put_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": f"/{namespace}/geo", "value": 1}],
    )
    assert put_response.status_code == HTTPStatus.NO_CONTENT, put_response.json()

    put_again_response = ctx.client.put(
        f"{COLUMNS_ROOT}/{namespace}/col",
        json=[{"path": f"/{namespace}/geo", "value": 2}],
    )
    assert put_again_response.status_code == HTTPStatus.NO_CONTENT, put_again_response.json()

    assert get_column_values(ctx, col_obj) == {"geo": 2}


def test_api_column_value_set__through_reference_forbidden(
    ctx_public_namespace_read_write,
):
    """Writing values through a cross-namespace reference is refused:
    references are immutable aliases, and the write scope that was checked
    belongs to the referencing namespace, not the column's owner."""
    from gerrydb_meta import crud, schemas
    from gerrydb_meta.enums import ScopeType
    from tests.api.scopes import grant_namespaced_scope

    ctx = ctx_public_namespace_read_write
    col = create_column(ctx, "refcol")
    create_geo(ctx, "geo1")

    other_ns, _ = crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(
            path="refns", description="test", public=True
        ),
        obj_meta=ctx.meta,
    )
    crud.column.create_reference(
        ctx.db, path="refcol", namespace=other_ns, col=col, obj_meta=ctx.meta
    )
    grant_namespaced_scope(ctx.db, ctx.meta, other_ns, ScopeType.NAMESPACE_WRITE)
    ctx.db.flush()

    response = ctx.client.put(
        f"{COLUMNS_ROOT}/refns/refcol",
        json=[{"path": f"/{ctx.namespace.path}/geo1", "value": 1}],
    )
    assert response.status_code == HTTPStatus.FORBIDDEN, response.json()
    assert "reference" in response.json()["detail"]
