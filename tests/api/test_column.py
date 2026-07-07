"""Tests for GerryDB REST API column metadata endpoints."""

from http import HTTPStatus

from gerrydb_meta import schemas
from gerrydb_meta.enums import ColumnKind, ColumnType
from gerrydb_meta.main import API_PREFIX

COLUMNS_ROOT = f"{API_PREFIX}/columns"


def test_api_column_create_read(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_body = schemas.Column(**create_response.json())
    assert create_body.canonical_path == pop_column_meta["canonical_path"]
    assert create_body.description == pop_column_meta["description"]
    assert str(create_body.source_url) == pop_column_meta["source_url"]
    assert create_body.kind == ColumnKind.COUNT
    assert create_body.type == ColumnType.INT
    assert set(create_body.aliases) == set(pop_column_meta["aliases"])

    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{create_body.canonical_path}"
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.Column(**read_response.json())
    assert read_body == create_body


def test_api_column_create_read__get_by_alias(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()
    create_body = schemas.Column(**create_response.json())

    alias = pop_column_meta["aliases"][0]
    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{alias}"
    )
    assert read_response.status_code == HTTPStatus.OK, read_response.json()
    read_body = schemas.Column(**read_response.json())
    assert read_body == create_body


def test_api_column_create__twice(ctx_public_namespace_read_write, pop_column_meta):
    ctx = ctx_public_namespace_read_write
    namespace = ctx.namespace.path
    create_response = ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    create_twice_response = ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_twice_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (
        create_twice_response.json()
    )


def test_api_column_create_patch(ctx_public_namespace_read_write, pop_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    create_response = ctx_public_namespace_read_write.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    path = pop_column_meta["canonical_path"]
    patch_response = ctx_public_namespace_read_write.client.patch(
        f"{COLUMNS_ROOT}/{namespace}/{path}",
        json={"aliases": ["another_alias"]},
    )
    assert patch_response.status_code == HTTPStatus.OK, patch_response.json()
    patch_body = schemas.Column(**patch_response.json())
    assert set(patch_body.aliases) == {*pop_column_meta["aliases"], "another_alias"}


def test_api_column_create_all(ctx_public_namespace_read_write, pop_column_meta, vap_column_meta):
    namespace = ctx_public_namespace_read_write.namespace.path
    canonical_paths = set()
    for col_meta in (pop_column_meta, vap_column_meta):
        create_response = ctx_public_namespace_read_write.client.post(
            f"{COLUMNS_ROOT}/{namespace}", json=col_meta
        )
        canonical_paths.add(col_meta["canonical_path"])
        assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = ctx_public_namespace_read_write.client.get(f"{COLUMNS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.OK, all_response.json()
    assert set(col["canonical_path"] for col in all_response.json()) == canonical_paths


def test_api_column_create_read__scope_read_only(ctx_public_namespace_read_only, pop_column_meta):
    namespace = ctx_public_namespace_read_only.namespace.path
    create_response = ctx_public_namespace_read_only.client.post(
        f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta
    )
    assert create_response.status_code == HTTPStatus.NOT_FOUND, create_response.json()

    read_response = ctx_public_namespace_read_only.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}"
    )
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_column_create_read__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    read_response = ctx_public_namespace_read_write.client.get(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}"
    )
    assert read_response.status_code == HTTPStatus.NOT_FOUND, read_response.json()


def test_api_column_create_all__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    all_response = ctx_public_namespace_read_write.client.get(f"{COLUMNS_ROOT}/{namespace}")
    assert all_response.status_code == HTTPStatus.NOT_FOUND, all_response.json()


def test_api_column_create_patch__private_namespace(
    ctx_public_namespace_read_write, ctx_private_namespace_read_write, pop_column_meta
):
    private_ctx = ctx_private_namespace_read_write
    namespace = private_ctx.namespace.path
    create_response = private_ctx.client.post(f"{COLUMNS_ROOT}/{namespace}", json=pop_column_meta)
    assert create_response.status_code == HTTPStatus.CREATED, create_response.json()

    patch_response = ctx_public_namespace_read_write.client.patch(
        f"{COLUMNS_ROOT}/{namespace}/{pop_column_meta['canonical_path']}",
        json={"aliases": ["another_alias"]},
    )
    assert patch_response.status_code == HTTPStatus.NOT_FOUND, patch_response.json()


def test_api_column_patch__through_reference_forbidden(ctx_public_namespace_read_write):
    """Aliases cannot be injected into a column's owner namespace by
    PATCHing through a cross-namespace reference."""
    from http import HTTPStatus

    from gerrydb_meta import crud, schemas
    from gerrydb_meta.enums import ScopeType
    from tests.api import create_column
    from tests.api.scopes import grant_namespaced_scope

    ctx = ctx_public_namespace_read_write
    col = create_column(ctx, "patchcol")

    other_ns, _ = crud.namespace.create(
        db=ctx.db,
        obj_in=schemas.NamespaceCreate(path="patchrefns", description="t", public=True),
        obj_meta=ctx.meta,
    )
    crud.column.create_reference(
        ctx.db, path="patchcol", namespace=other_ns, col=col, obj_meta=ctx.meta
    )
    grant_namespaced_scope(ctx.db, ctx.meta, other_ns, ScopeType.NAMESPACE_WRITE)
    ctx.db.flush()

    response = ctx.client.patch(
        "/api/v1/columns/patchrefns/patchcol",
        json={"aliases": ["sneaky_alias"]},
    )
    assert response.status_code == HTTPStatus.FORBIDDEN, response.json()
    assert "reference" in response.json()["detail"]


def test_api_column_list_include_references(ctx_public_namespace_read_write):
    """Un-materialized clones appear in listings only with the flag, labeled
    by their local path with the resolved column's metadata."""
    from gerrydb_meta import crud

    ctx = ctx_public_namespace_read_write
    db, meta, ns_obj = ctx.db, ctx.meta or ctx.admin_meta, ctx.namespace

    src_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="refsrc", description="t", public=True),
        obj_meta=meta,
    )
    src_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="pop",
            description="source population",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=src_ns,
    )
    crud.column.create_reference(
        db, path="borrowed_pop", namespace=ns_obj, col=src_col, obj_meta=meta
    )
    db.flush()

    plain = ctx.client.get(f"{COLUMNS_ROOT}/{ns_obj.path}")
    assert plain.status_code == HTTPStatus.OK
    assert "borrowed_pop" not in {c["canonical_path"] for c in plain.json()}

    flagged = ctx.client.get(f"{COLUMNS_ROOT}/{ns_obj.path}?include_references=true")
    assert flagged.status_code == HTTPStatus.OK
    by_path = {c["canonical_path"]: c for c in flagged.json()}
    assert "borrowed_pop" in by_path
    clone = by_path["borrowed_pop"]
    assert clone["namespace"] == ns_obj.path
    assert clone["description"] == "source population"
    assert clone["kind"] == "count"


def test_api_column_reference_validate_paths(ctx_public_namespace_read_write):
    """validate_paths refuses a clone whose source values cover paths the
    target namespace lacks; the default permits it."""
    from gerrydb_meta import crud

    ctx = ctx_public_namespace_read_write
    db, meta, ns_obj = ctx.db, ctx.meta or ctx.admin_meta, ctx.namespace

    src_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="valsrc", description="t", public=True),
        obj_meta=meta,
    )
    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=src_ns)
    geos, _ = crud.geography.create_bulk(
        db=db,
        objs_in=[
            schemas.GeographyCreate(path=f"vg{i}", geography=None, internal_point=None)
            for i in range(2)
        ],
        obj_meta=meta,
        geo_import=geo_import,
        namespace=src_ns,
    )
    src_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="valpop",
            description="t",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=src_ns,
    )
    crud.column.set_values(
        db=db,
        col=src_col,
        values=[(g[0], i) for i, g in enumerate(geos)],
        obj_meta=meta,
    )
    db.flush()

    body = {
        "path": "valpop_clone",
        "target_namespace": src_ns.path,
        "target_path": "valpop",
        "validate_paths": True,
    }
    refused = ctx.client.post(f"/api/v1/column-refs/{ns_obj.path}", json=body)
    assert refused.status_code == HTTPStatus.CONFLICT
    assert "missing" in refused.json()["detail"]

    body["validate_paths"] = False
    allowed = ctx.client.post(f"/api/v1/column-refs/{ns_obj.path}", json=body)
    assert allowed.status_code == HTTPStatus.CREATED, allowed.json()


def test_api_column_materialize(ctx_public_namespace_read_write):
    """Route glue: materialize returns the owned column; same-namespace
    aliases and unknown paths refuse."""
    from gerrydb_meta import crud

    ctx = ctx_public_namespace_read_write
    db, meta, ns_obj = ctx.db, ctx.meta or ctx.admin_meta, ctx.namespace

    src_ns, _ = crud.namespace.create(
        db=db,
        obj_in=schemas.NamespaceCreate(path="matapi", description="t", public=True),
        obj_meta=meta,
    )
    src_col, _ = crud.column.create(
        db=db,
        obj_in=schemas.ColumnCreate(
            canonical_path="matpop",
            description="source population",
            kind=ColumnKind.COUNT,
            type=ColumnType.INT,
        ),
        obj_meta=meta,
        namespace=src_ns,
    )
    crud.column.create_reference(
        db, path="borrowed_matpop", namespace=ns_obj, col=src_col, obj_meta=meta
    )
    db.flush()

    response = ctx.client.post(
        f"{COLUMNS_ROOT}/{ns_obj.path}/borrowed_matpop/materialize"
    )
    assert response.status_code == HTTPStatus.OK, response.json()
    body = schemas.Column(**response.json())
    assert body.canonical_path == "borrowed_matpop"
    assert body.namespace == ns_obj.path
    assert body.kind == ColumnKind.COUNT

    # The path now names an owned column, not a cross-namespace ref.
    again = ctx.client.post(f"{COLUMNS_ROOT}/{ns_obj.path}/borrowed_matpop/materialize")
    assert again.status_code == HTTPStatus.CONFLICT

    missing = ctx.client.post(f"{COLUMNS_ROOT}/{ns_obj.path}/nope/materialize")
    assert missing.status_code == HTTPStatus.NOT_FOUND
