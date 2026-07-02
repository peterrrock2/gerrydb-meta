import inspect
import uuid
from http import HTTPStatus

import pytest
from fastapi import HTTPException, Response
from pydantic import BaseModel

import gerrydb_meta.api.base as base
from gerrydb_meta import crud
from gerrydb_meta.api.base import *
from gerrydb_meta.api.deps import get_scopes

# Dummy classes for testing
db_dummy = object()


class DummyCRUD:
    def __init__(self, tag):
        self._tag = tag

    def etag(self, db=None, namespace=None):
        return self._tag


class DummyNamespacedCRUD(DummyCRUD):
    # inherits etag(db, namespace)
    pass


class DummyScopes:
    def can_read_in_namespace(self, ns):
        return True

    def can_read_localities(self):
        return True


@pytest.fixture
def dummy_namespace():
    return object()


def test_check_etag_no_exception():
    tag = uuid.uuid4()
    crud_obj = DummyCRUD(tag)
    check_etag(db_dummy, crud_obj, f'"{tag}"')
    with pytest.raises(HTTPException) as excinfo:
        check_etag(db_dummy, crud_obj, '"{etag}"')
    assert excinfo.value.status_code == HTTPStatus.NOT_MODIFIED


def test_check_namespaced_etag():
    tag = uuid.uuid4()
    crud_obj = DummyNamespacedCRUD(tag)
    namespace = object()
    check_namespaced_etag(db_dummy, crud_obj, namespace, f'"{tag}"')
    with pytest.raises(HTTPException) as excinfo:
        check_namespaced_etag(db_dummy, crud_obj, namespace, '"{etag}"')
    assert excinfo.value.status_code == HTTPStatus.NOT_MODIFIED


def test_add_etag():
    resp = Response()
    tag = uuid.uuid4()
    add_etag(resp, tag)
    assert resp.headers.get("ETag") == f'"{tag}"'
    resp2 = Response()
    add_etag(resp2, None)
    assert "ETag" not in resp2.headers


def test_namespace_error_msgs():
    read_msg = namespace_read_error_msg("Column")
    assert "read column" in read_msg.lower()
    write_msg = namespace_write_error_msg("Column")
    assert "write column" in write_msg.lower()


def test_body_schema_decorator_replaces_annotation():
    class MyModel(BaseModel):
        x: int

    def handler(a: int, obj_in: object):
        pass

    decorated = body_schema(MyModel)(handler)
    sig = inspect.signature(decorated)
    params = sig.parameters
    assert params["a"].annotation == int
    assert params["obj_in"].annotation is MyModel


@pytest.mark.parametrize(
    "input_path,expected",
    [
        ("/ns/path/to/resource", ("ns", "path/to/resource")),
        ("ns/path/only", ("path", "only")),
        ("/onlyone", (None, "/onlyone")),
        ("  /A/B/C  ", ("a", "b/c")),
    ],
)
def test_parse_path(input_path, expected):
    assert parse_path(input_path) == expected


def test_from_resource_paths_bad_path():
    with pytest.raises(HTTPException) as excinfo:
        from_resource_paths(["badpath"], db_dummy, DummyScopes())
    assert excinfo.value.status_code == HTTPStatus.BAD_REQUEST


def test_from_resource_paths_unknown_resource():
    with pytest.raises(HTTPException) as excinfo:
        from_resource_paths(["/foo/ns/p"], db_dummy, DummyScopes())
    assert excinfo.value.status_code == HTTPStatus.NOT_FOUND


def test_msgpack_response_render_and_media_type():
    resp = MsgpackResponse()
    data = {"key": "value", "num": 42}
    packed = resp.render(data)
    # should be bytes and unpackable
    import ormsgpack as msgpack

    unpacked = msgpack.unpackb(packed)
    assert unpacked == data
    assert resp.media_type == "application/msgpack"


class DummyNamespaceObj:
    def __init__(self, path, public=True):
        self.path = path
        self.public = public


class DummyObj:
    def __init__(self, namespace, path):
        self.namespace = DummyNamespaceObj(namespace)
        self.path = path


class DummyCRUDBulk:
    def __init__(self, objs):
        self.objs = objs

    def get_bulk(self, db, namespaced_paths):
        return self.objs


class DummyCRUDFallback:
    def __init__(self, ref_map, obj_map):
        self.ref_map = ref_map
        self.obj_map = obj_map

    def get_ref(self, db, namespace, path):
        return self.ref_map.get((namespace.path, path))

    def get(self, db, namespace, path):
        return self.obj_map.get((namespace.path, path))


class DenyScopes:
    def can_read_in_namespace(self, ns):
        return False

    def can_read_localities(self):
        return True


def setup_dummy_namespace(monkeypatch):
    monkeypatch.setattr(base, "normalize_path", lambda p, case_sensitive_uid: p)
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: DummyNamespaceObj(path))


def test_from_resource_paths_success_bulk(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    paths = ["columns/ns1/a", "columns/ns2/b"]
    objs = [DummyObj("ns1", "a"), DummyObj("ns2", "b")]
    monkeypatch.setitem(base.ENDPOINT_TO_CRUD, "columns", DummyCRUDBulk(objs))
    result = from_resource_paths(paths, db_dummy, DummyScopes())
    assert result == objs


def test_from_resource_paths_success_bad_paths(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    paths = ["columns/ns1/a/too_long"]
    [DummyObj("ns1", "a")]
    with pytest.raises(
        ValueError, match="Paths must verify the form '/<resource>/<namespace>/<path>'"
    ):
        from_resource_paths(paths, db_dummy, DummyScopes())


def test_from_resource_paths_missing_bulk(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    paths = ["columns/ns1/a", "columns/ns2/b"]
    objs = [DummyObj("ns1", "a")]
    monkeypatch.setitem(base.ENDPOINT_TO_CRUD, "columns", DummyCRUDBulk(objs))
    with pytest.raises(HTTPException) as excinfo:
        from_resource_paths(paths, db_dummy, DummyScopes())
    assert excinfo.value.status_code == HTTPStatus.NOT_FOUND
    assert "/columns/ns2/b" in str(excinfo.value.detail)


def test_from_resource_paths_success_fallback(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    paths = ["geographies/ns/x", "geographies/ns/y"]
    ref_map = {("ns", "x"): DummyObj("ns", "x")}
    obj_map = {("ns", "y"): DummyObj("ns", "y")}
    monkeypatch.setitem(base.ENDPOINT_TO_CRUD, "geographies", DummyCRUDFallback(ref_map, obj_map))
    with pytest.raises(HTTPException):
        from_resource_paths(paths, db_dummy, DummyScopes(), follow_refs=False)

    ref_map[("ns", "y")] = obj_map[("ns", "y")]
    result = from_resource_paths(paths, db_dummy, DummyScopes(), follow_refs=False)
    assert [o.path for o in result] == ["x", "y"]
    obj_map[("ns", "x")] = ref_map[("ns", "x")]
    result2 = from_resource_paths(paths, db_dummy, DummyScopes(), follow_refs=True)
    assert [o.path for o in result2] == ["x", "y"]


def test_from_resource_paths_duplicate(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    monkeypatch.setitem(base.ENDPOINT_TO_CRUD, "columns", DummyCRUDBulk([]))
    paths = ["columns/ns/p", "columns/ns/p"]
    with pytest.raises(HTTPException) as excinfo:
        from_resource_paths(paths, db_dummy, DummyScopes())
    assert excinfo.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_from_resource_paths_namespace_permission(monkeypatch):
    setup_dummy_namespace(monkeypatch)
    monkeypatch.setitem(base.ENDPOINT_TO_CRUD, "columns", DummyCRUDBulk([]))
    with pytest.raises(HTTPException) as excinfo:
        from_resource_paths(["columns/ns/p"], db_dummy, DenyScopes())
    assert excinfo.value.status_code == HTTPStatus.NOT_FOUND


def test_namespace_with_read(ctx_private_namespace_read_only):
    ctx = ctx_private_namespace_read_only

    scopes = get_scopes(ctx.admin_user)
    # test_namespace_with_read
    with pytest.raises(HTTPException, match='Namespace "bad_test_namespace_with_read" not found,'):
        _ = base.namespace_with_read(
            db=ctx.db,
            scopes=scopes,
            path="bad_test_namespace_with_read",
            base_namespace=None,
        )

    with pytest.raises(
        HTTPException,
        match=(
            "Cannot join across private namespaces: namespace "
            "test_namespace_with_read__private is private."
        ),
    ):
        _ = base.namespace_with_read(
            db=ctx.db,
            scopes=scopes,
            path="test_namespace_with_read__private",
            base_namespace="bad_namespace_thing",
        )

    ns = base.namespace_with_read(
        db=ctx.db,
        scopes=scopes,
        path="test_namespace_with_read__private",
        base_namespace=None,
    )
    assert ns.path == "test_namespace_with_read__private"


class DummyScopesGeo:
    def __init__(self, can_read: bool):
        self._can_read = can_read

    def can_read_localities(self) -> bool:
        return self._can_read


@pytest.fixture
def dummy_scopes_allow():
    return DummyScopesGeo(can_read=True)


@pytest.fixture
def dummy_scopes_deny():
    return DummyScopesGeo(can_read=False)


def test_forbidden_if_no_scope(db, dummy_scopes_deny):
    with pytest.raises(HTTPException) as exc:
        geo_set_from_paths(
            locality="anything",
            layer="layers/ns/layername",
            namespace="ns",
            db=db,
            scopes=dummy_scopes_deny,
        )
    assert exc.value.status_code == HTTPStatus.FORBIDDEN
    assert "read localities" in exc.value.detail


def test_locality_not_found(db, dummy_scopes_allow, monkeypatch):
    monkeypatch.setattr(crud.locality, "get_by_ref", lambda db, path: None)

    with pytest.raises(HTTPException) as exc:
        geo_set_from_paths(
            locality="does-not-exist",
            layer="layers/ns/layername",
            namespace="ns",
            db=db,
            scopes=dummy_scopes_allow,
        )
    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == "Locality not found."


def test_layer_not_found(db, dummy_scopes_allow, monkeypatch, dummy_namespace):
    monkeypatch.setattr(crud.locality, "get_by_ref", lambda db, path: object())
    monkeypatch.setattr(base, "parse_path", lambda layer: ("x", "lay"))
    monkeypatch.setattr(
        base,
        "namespace_with_read",
        lambda db, scopes, path, base_namespace: dummy_namespace,
    )
    monkeypatch.setattr(crud.geo_layer, "get", lambda db, path, namespace: None)

    with pytest.raises(HTTPException) as exc:
        base.geo_set_from_paths(
            locality="exists",
            layer="layers/x/lay",
            namespace="ns",
            db=db,
            scopes=dummy_scopes_allow,
        )

    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == "Geographic layer not found."


def test_no_set_for_locality_and_layer(db, dummy_scopes_allow, monkeypatch, dummy_namespace):
    monkeypatch.setattr(crud.locality, "get_by_ref", lambda db, path: object())
    monkeypatch.setattr(base, "parse_path", lambda layer: ("x", "lay"))
    monkeypatch.setattr(
        base,
        "namespace_with_read",
        lambda db, scopes, path, base_namespace: dummy_namespace,
    )
    monkeypatch.setattr(crud.geo_layer, "get", lambda db, path, namespace: object())
    monkeypatch.setattr(
        crud.geo_layer,
        "get_set_by_locality",
        lambda db, layer, locality: None,
    )

    bad_layer_str = "layers/x/lay"
    bad_locality_str = "exists"
    with pytest.raises(HTTPException) as exc:
        base.geo_set_from_paths(
            locality=bad_locality_str,
            layer=bad_layer_str,
            namespace="ns",
            db=db,
            scopes=dummy_scopes_allow,
        )

    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == (
        f'No set of geographies in geographic layer "{bad_layer_str}" '
        f'at locality "{bad_locality_str}".'
    )


from http import HTTPStatus

import msgpack
import pytest
from fastapi import APIRouter, FastAPI, Request
from starlette.testclient import TestClient

# Create an APIRouter that uses your MsgpackRoute
router = APIRouter(
    route_class=MsgpackRoute,
    default_response_class=MsgpackResponse,
)


@router.post("/echo")
async def echo(request: Request):
    # MsgpackRequest.body() will unpack for us
    data = await request.body()
    return {"received": data}


@router.post("/boom")
async def boom(request: Request):
    # force decoding then raise a GerryValueError
    _ = await request.body()
    raise GerryValueError("database oops")


# Wire it up in a FastAPI app
app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_unsupported_media_type_error():
    """Wrong or missing content-type → 415"""
    resp = client.post("/echo", content=b"\x00\x01\x02")
    assert resp.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert resp.json() == {"detail": "Only MessagePack requests are supported by this endpoint."}


def test_invalid_msgpack_body_error():
    """Correct Content-Type but invalid MessagePack → 400"""
    headers = {"content-type": "application/msgpack"}
    # a single 0xC1 byte is guaranteed to throw a FormatError/UnpackValueError
    resp = client.post("/echo", content=b"\xc1", headers=headers)
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert resp.json() == {"detail": "Request body is not a valid MessagePack object."}


def test_gerry_value_error_pass_through():
    """An uncaught GerryValueError should become a 500, not a decode error."""
    headers = {"content-type": "application/msgpack"}
    packed_empty = msgpack.packb({})

    resp = client.post("/boom", content=packed_empty, headers=headers)
    assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


from types import SimpleNamespace


class DummyScopesNSApi:
    def __init__(self, can_read=True, can_write=True):
        self._can_read = can_read
        self._can_write = can_write

    def can_read_in_namespace(self, ns):
        return self._can_read

    def can_write_in_namespace(self, ns):
        return self._can_write


@pytest.fixture
def public_ns():
    return SimpleNamespace(path="public_ns", public=True)


@pytest.fixture
def private_ns():
    return SimpleNamespace(path="private_ns", public=False)


def make_api():
    # The instance‐level .crud isn’t used by the methods,
    # so we can just pass anything here.
    return NamespacedObjectApi(
        crud=None,
        get_schema=None,
        create_schema=None,
        obj_name_singular="thing",
        obj_name_plural="things",
    )


#
# _namespace_with_read
#
def test_read_not_found(monkeypatch):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: None)
    scopes = DummyScopesNSApi(can_read=True)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_read(db=None, scopes=scopes, path="whatever")
    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == namespace_read_error_msg("things")


def test_read_no_permission(monkeypatch, public_ns):
    api = make_api()
    # return a namespace, but scopes.denies read
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: public_ns)
    scopes = DummyScopesNSApi(can_read=False)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_read(db=None, scopes=scopes, path="public_ns")
    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == namespace_read_error_msg("things")


def test_read_private_cross_namespace(monkeypatch, private_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: private_ns)
    scopes = DummyScopesNSApi(can_read=True)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_read(
            db=None,
            scopes=scopes,
            path="private_ns",
            base_namespace="other_ns",
        )
    assert exc.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert exc.value.detail == (
        f"Cannot join across private namespaces: namespace {private_ns.path} is private."
    )


def test_read_success_public(monkeypatch, public_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: public_ns)
    scopes = DummyScopesNSApi(can_read=True)
    out = api._namespace_with_read(
        db=None,
        scopes=scopes,
        path="public_ns",
        base_namespace="anything",
    )
    assert out is public_ns


def test_read_success_private_match(monkeypatch, private_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: private_ns)
    scopes = DummyScopesNSApi(can_read=True)
    out = api._namespace_with_read(
        db=None,
        scopes=scopes,
        path="private_ns",
        base_namespace="private_ns",
    )
    assert out is private_ns


#
# _namespace_with_write
#
def test_write_not_found(monkeypatch):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: None)
    scopes = DummyScopesNSApi(can_write=True)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_write(db=None, scopes=scopes, path="whatever")
    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == namespace_write_error_msg("things")


def test_write_no_permission(monkeypatch, public_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: public_ns)
    scopes = DummyScopesNSApi(can_write=False)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_write(db=None, scopes=scopes, path="public_ns")
    assert exc.value.status_code == HTTPStatus.NOT_FOUND
    assert exc.value.detail == namespace_write_error_msg("things")


def test_write_private_cross_namespace(monkeypatch, private_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: private_ns)
    scopes = DummyScopesNSApi(can_write=True)
    with pytest.raises(HTTPException) as exc:
        api._namespace_with_write(
            db=None,
            scopes=scopes,
            path="private_ns",
            base_namespace="other_ns",
        )
    assert exc.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert exc.value.detail == (
        f"Cannot join across private namespaces: namespace {private_ns.path} is private."
    )


def test_write_success_public(monkeypatch, public_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: public_ns)
    scopes = DummyScopesNSApi(can_write=True)
    out = api._namespace_with_write(
        db=None,
        scopes=scopes,
        path="public_ns",
        base_namespace="anything",
    )
    assert out is public_ns


def test_write_success_private_match(monkeypatch, private_ns):
    api = make_api()
    monkeypatch.setattr(base.crud.namespace, "get", lambda db, path: private_ns)
    scopes = DummyScopesNSApi(can_write=True)
    out = api._namespace_with_write(
        db=None,
        scopes=scopes,
        path="private_ns",
        base_namespace="private_ns",
    )
    assert out is private_ns
