"""Tests for GerryDB REST API view template endpoints."""

from http import HTTPStatus

import pytest
from fastapi import HTTPException

import gerrydb_meta.models as models
from gerrydb_meta import crud, schemas
from gerrydb_meta.api.deps import get_scopes
from gerrydb_meta.api.view_template import ViewTemplateApi
from gerrydb_meta.enums import ColumnKind, ColumnType, ScopeType
from gerrydb_meta.main import API_PREFIX
from tests.api import create_column
from tests.api.scopes import grant_namespaced_scope

VIEW_TEMPLATES_ROOT = f"{API_PREFIX}/view-templates"


def test_api_view_template_create_read__one_column(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "test")

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "one_col",
            "description": "A view template with one column.",
            "members": [f"/columns/{namespace}/test"],
        },
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.ViewTemplate(**create_response.json())
    assert {member.canonical_path for member in create_body.members} == {"test"}

    read_response = ctx.client.get(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}/one_col",
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.ViewTemplate(**read_response.json())
    assert read_body == create_body


def test_api_view_template_create_all__one_column(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "test")

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "one_col",
            "description": "A view template with one column.",
            "members": [f"/columns/{namespace}/test"],
        },
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.ViewTemplate(**create_response.json())

    all_response = ctx.client.get(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
    )
    assert all_response.status_code == HTTPStatus.OK, all_response.json()
    assert len(all_response.json()) == 1
    all_body = schemas.ViewTemplate(**all_response.json()[0])
    assert all_body == create_body


def test_api_view_template_create_read__scope_read_only(ctx_public_namespace_read_only):
    ctx = ctx_public_namespace_read_only
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "no_cols",
            "description": "A view template with no columns.",
            "members": [],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()

    read_response = ctx.client.get(f"{VIEW_TEMPLATES_ROOT}/{namespace}/no_cols")
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_view_template_create__nonexistent_column(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    col_path = f"/columns/{namespace}/bad"

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a nonexistent column.",
            "members": [col_path],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()
    assert col_path in create_response.json()["detail"]


def test_api_view_template_create__nonexistent_column_ns(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    col_path = f"/columns/bad-namespace/bad"

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a column in a nonexistent namespace.",
            "members": [col_path],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()
    assert "bad-namespace" in create_response.json()["detail"]


def test_api_view_template_create__nonexistent_column_set(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    col_set_path = f"/column-sets/{namespace}/bad"

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a nonexistent column set.",
            "members": [col_set_path],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()
    assert col_set_path in create_response.json()["detail"]


def test_api_view_template_create__nonexistent_resource(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a nonsensical resource path.",
            "members": ["/bla/bla/bla"],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()
    assert "Unknown resource" in create_response.json()["detail"]


def test_api_view_template_create__malformed_resource_path(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a malformed resource path.",
            "members": ["columns/aa"],
        },
    )
    assert create_response.status_code == HTTPStatus.BAD_REQUEST, create_response.json()
    assert "Bad resource path" in create_response.json()["detail"]


def test_api_view_template_create__invalid_resource_path(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols",
            "description": "A view template with a malformed resource path.",
            "members": ["columns/&&"],
        },
    )
    assert create_response.status_code == HTTPStatus.BAD_REQUEST, create_response.json()
    assert (
        "Found unexpected expression in field 'members' at position '0' of the request."
    ) in create_response.json()["detail"]


def test_api_view_template_create__invalid_path(
    ctx_public_namespace_read_write,
):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "bad_cols;and&&shiz",
            "description": "A view template with a malformed resource path.",
            "members": ["columns"],
        },
    )
    assert create_response.status_code == HTTPStatus.BAD_REQUEST, create_response.json()
    assert "Found unexpected expression in field 'path'" in create_response.json()["detail"]


def test_api_view_template_create__duplicate_column(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "test")
    col_path = f"/columns/{namespace}/test"

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "duped",
            "description": "A view template with the same column twice.",
            "members": [col_path, col_path],
        },
    )
    assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, create_response.json()
    assert "Duplicate resource paths" in create_response.json()["detail"]


def test_api_view_template_create__twice(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "test")
    body = {
        "path": "twice",
        "description": "A view template we'll try to create twice.",
        "members": [f"/columns/{namespace}/test"],
    }

    create_response = ctx.client.post(f"{VIEW_TEMPLATES_ROOT}/{namespace}", json=body)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_twice_response = ctx.client.post(f"{VIEW_TEMPLATES_ROOT}/{namespace}", json=body)
    assert create_twice_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (
        create_twice_response.json()
    )
    assert "may already exist" in create_twice_response.json()["detail"]


def test_api_view_template_create_read__private_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
):
    private_ctx = ctx_private_namespace_read_write
    public_ctx = ctx_public_namespace_read_write
    namespace = private_ctx.namespace.path

    create_response = private_ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={"path": "empty", "description": "empty", "members": []},
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    read_response = public_ctx.client.get(f"{VIEW_TEMPLATES_ROOT}/{namespace}/cols")
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_column_create_all__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write
):
    private_ctx = ctx_private_namespace_read_write
    public_ctx = ctx_public_namespace_read_write
    namespace = private_ctx.namespace.path

    create_response = private_ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={"path": "empty", "description": "empty", "members": []},
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = public_ctx.client.get(f"{VIEW_TEMPLATES_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.NOT_FOUND, all_response.json()


# Recall the public join constraint:
#   * A view template can reference resources in any public namespace.
#   * If the view template is in a private namespace, it can reference
#     resources in that private namespace (but not any other private namespace).


def test_api_view_template_create__join_constraint__private_col_in_public_namespace(
    ctx_public_namespace_read_write,
    ctx_private_namespace_read_write,
):
    private_ctx = ctx_private_namespace_read_write
    public_ctx = ctx_public_namespace_read_write
    private_namespace = private_ctx.namespace.path
    public_namespace = public_ctx.namespace.path

    create_column(private_ctx, "private_col")
    create_column(public_ctx, "public_col")

    create_response = public_ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{public_namespace}",
        json={
            "path": "private_join",
            "description": "A public view template with a private column.",
            "members": [
                f"/columns/{private_namespace}/private_col",
                f"/columns/{public_namespace}/public_col",
            ],
        },
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()
    assert private_namespace in create_response.json()["detail"]


def test_api_view_template_create__join_constraint__private_col_in_private_namespace(
    ctx_private_namespace_read_write,
):
    ctx = ctx_private_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "private_col")

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "private",
            "description": "A private view template with a private column.",
            "members": [f"/columns/{namespace}/private_col"],
        },
    )
    create_body = schemas.ViewTemplate(**create_response.json())

    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    assert len(create_body.members) == 1


def test_api_view_template_create__join_constraint__private_xref_in_private_namespace(
    ctx_private_namespace_read_write,
):
    ctx = ctx_private_namespace_read_write
    namespace = ctx.namespace.path

    create_column(ctx, "private_col")
    other_private_namespace_obj, _ = crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(
            path=f"{namespace}__other",
            description="Yet another private namespace",
            public=False,
        ),
        obj_meta=ctx.admin_meta,
    )
    grant_namespaced_scope(
        db=ctx.db,
        user_or_meta=ctx.meta,
        namespace=other_private_namespace_obj,
        scope=ScopeType.NAMESPACE_READ,
    )
    crud.column.create(
        db=ctx.db,
        obj_in=schemas.ColumnCreate(
            canonical_path="other_private_col",
            description="Test column in another private namespace",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=ctx.meta,
        namespace=other_private_namespace_obj,
    )

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "private",
            "description": (
                "A private view template with columns from multiple private namespaces."
            ),
            "members": [
                f"/columns/{namespace}/private_col",
                f"/columns/{namespace}__other/other_private_col",
            ],
        },
    )

    assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, create_response.json()
    assert "Cannot create cross-namespace reference" in create_response.json()["detail"]


def test_odd_errors(ctx_public_namespace_read_write):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    db = ctx.db
    user = models.User(email="rendertest@example.com", name="Render User")
    db.add(user)
    db.flush()
    scopes = get_scopes(user)

    with pytest.raises(HTTPException, match="Cannot read in public namespaces"):
        ViewTemplateApi(
            crud=crud.view_template,
            get_schema=schemas.ViewTemplate,
            create_schema=schemas.ViewTemplateCreate,
            patch_schema=schemas.ViewTemplatePatch,
            obj_name_singular="ViewTemplate",
            obj_name_plural="ViewTemplates",
        )._check_public(scopes)

    n_cols = 101
    for i in range(n_cols):
        create_column(ctx, f"test{i}")

    create_response = ctx.client.post(
        f"{VIEW_TEMPLATES_ROOT}/{namespace}",
        json={
            "path": "too_many",
            "description": "A view template with too many columns.",
            "members": [f"/columns/{namespace}/test{i}" for i in range(n_cols)],
        },
    )

    assert create_response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "Maximum view template column count exceeded" in create_response.json()["detail"]
