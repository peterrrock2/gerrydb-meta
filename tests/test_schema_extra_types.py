import pytest
from pydantic import BaseModel, ValidationError

from gerrydb_meta.schemas import (
    Description,
    GeoNameStr,
    GerryPath,
    NamespacedGerryGeoPath,
    NamespacedGerryPath,
    NameStr,
    ShortStr,
    UserEmail,
)


# =============
#   UserEmail
# =============
class DummyUserEmail(BaseModel):
    email: UserEmail


@pytest.mark.parametrize(
    "value",
    [
        "a@b.com",
        "user.name+tag@example.co.uk",
        "x" * 243 + "@example.com",
    ],
)
def test_user_email_valid(value):
    obj = DummyUserEmail(email=value)
    assert obj.email == value


@pytest.mark.parametrize(
    "value",
    [
        "x" * 10,
        "x" * 255,
        "x" * 255 + "@example.com",
        "",
    ],
)
def test_user_email_invalid(value):
    with pytest.raises(ValidationError):
        DummyUserEmail(email=value)


# ===========
#   NameStr
# ===========
class DummyNameStr(BaseModel):
    name: NameStr


@pytest.mark.parametrize(
    "value",
    [
        "a1",
        "0_foo-bar.baz",
        "z9",
        "abc123_def",
        "m-._n",  # all allowed characters
        "a" * 100,  # max‐length = 100 is allowed
    ],
)
def test_namestr_valid(value):
    obj = DummyNameStr(name=value)
    assert obj.name == value


@pytest.mark.parametrize(
    "value",
    [
        "a",  # only one character—regex requires at least 2 total
        "BadUpper",  # uppercase not allowed
        "-abc",  # cannot start with hyphen
        "_foo",  # cannot start with underscore
        "1",  # single digit only is length 1
        "ab$",  # dollar sign not allowed
        "foo bar",  # space not allowed
        "a" * 101,  # too long
    ],
)
def test_namestr_invalid(value):
    with pytest.raises(ValidationError):
        DummyNameStr(name=value)


# ===============
#   Description
# ===============
class DummyDescription(BaseModel):
    description: Description


@pytest.mark.parametrize(
    "value",
    [
        None,
        "a" * 5000,  # boundary
        "Some arbitrary text under 5000 chars.",
    ],
)
def test_description_valid(value):
    obj = DummyDescription(description=value)
    assert obj.description == value


@pytest.mark.parametrize(
    "value",
    [
        "x" * 5001,  # too long
        "",
    ],
)
def test_description_invalid(value):
    with pytest.raises(ValidationError):
        DummyDescription(description=value)


# ============
#   ShortStr
# ============
class DummyShortStr(BaseModel):
    short_str: ShortStr


@pytest.mark.parametrize(
    "value",
    [
        None,
        "x" * 100,
        "Short description",
    ],
)
def test_shortstr_valid(value):
    obj = DummyShortStr(short_str=value)
    assert obj.short_str == value


@pytest.mark.parametrize(
    "value",
    [
        "x" * 101,
        "",
    ],
)
def test_shortstr_invalid(value):
    with pytest.raises(ValidationError):
        DummyShortStr(short_str=value)


# =============
#   GerryPath
# =============
class DummyGerryPath(BaseModel):
    gerry_path: GerryPath


@pytest.mark.parametrize(
    "value",
    [
        "a1",  # single segment, length 2
        "/a1",  # leading slash + single segment
        "foo-bar_baz",  # one segment, underscores and hyphens allowed
        "/foo-bar.baz",  # leading slash + allowed chars
        "abc/def",  # two segments
        "/abc/def-123",  # leading slash + two segments
        "a1/b2",  # minimal two segments (each 2‐chars)
        "x" * 252 + "/y2",  # 252 + 1 + 2 = 255 exactly
    ],
)
def test_gerrypath_valid(value):
    obj = DummyGerryPath(gerry_path=value)
    assert obj.gerry_path == value


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        "A1",  # uppercase not allowed
        "a",  # single char—must be at least 2
        "/a",  # single char after slash
        "ab/cd/ef",  # three segments—too many
        "ab//cd",  # empty middle segment
        " ab/cd",  # leading space not allowed
        "ab/cd ",  # trailing space not allowed
        "ab/c$",  # “$” not allowed
        "x" * 253 + "/y23",  # 253+1+3 = 257 > 255
        "-foo/bar",  # segment cannot start with hyphen
        "foo/Bar",  # uppercase “B” not allowed in any segment
    ],
)
def test_gerrypath_invalid(value):
    with pytest.raises(ValidationError):
        DummyGerryPath(gerry_path=value)


# =======================
#   NamespacedGerryPath
# =======================
class DummyNamespacedGerryPath(BaseModel):
    namespaced_gerry_path: NamespacedGerryPath


@pytest.mark.parametrize(
    "value",
    [
        "a1",
        "/a1",
        "foo/bar",
        "/foo/bar",
        "foo/bar/baz",
        "/foo/bar/baz-qux",
        "a1/b2/c3_d4",
        "x" * 252 + "/y2",  # 255 total
    ],
)
def test_namespaced_gerrypath_valid(value):
    obj = DummyNamespacedGerryPath(namespaced_gerry_path=value)
    assert obj.namespaced_gerry_path == value


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        "A1",  # uppercase not allowed
        "a",  # too short
        "ab/cd/ef/gh",  # 4 segments—too many
        "foo//bar",  # empty segment
        "foo/Bar/baz",  # uppercase in segment 2
        "ab/cd$",  # illegal char
        "x" * 254 + "/y2",
    ],
)
def test_namespaced_gerrypath_invalid(value):
    with pytest.raises(ValidationError):
        DummyNamespacedGerryPath(namespaced_gerry_path=value)


# ==========================
#   NamespacedGerryGeoPath
# ==========================
class DummyNamespacedGerryGeoPath(BaseModel):
    namespaced_gerry_geo_path: NamespacedGerryGeoPath


@pytest.mark.parametrize(
    "value",
    [
        "a1",
        "/a1",
        "foo/bar",
        "/foo/bar",
        "foo/bar/Baz123",  # last segment uppercase start
        "/foo-bar/baz_qux/Geo09",  # three segments, last may start uppercase
        "foo1/bar2/123",  # last segment may start digit
        "a1/b2/c3",  # all‐lowercase segments—still okay
        "x" * 248 + "/y2/ZZZ",  # 255 total
        "vtd:0109700VP25",  # bare geoid path with uppercase (AL VTDs)
        "vtd:010130012.2",  # bare geoid path with dot
        "vtd:010450007-1",  # bare geoid path with hyphen
        "/census.2020/vtd:0109700VP25",  # namespaced uppercase geoid
    ],
)
def test_namespaced_gerrygeopath_valid(value):
    obj = DummyNamespacedGerryGeoPath(namespaced_gerry_geo_path=value)
    assert obj.namespaced_gerry_geo_path == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "A1",  # uppercase in first segment
        "a",  # too short
        "ab/cd/ef/gh",  # 4 segments
        "foo//bar",  # empty segment
        "foo/Bar/baz/qux",  # too many
        "foo/bar/_baz",  # last segment cannot start underscore
        "foo/bar/ baz",  # space not allowed
        "x" * 253 + "/y2/zzz",  # length >255
    ],
)
def test_namespaced_gerrygeopath_invalid(value):
    with pytest.raises(ValidationError):
        DummyNamespacedGerryGeoPath(namespaced_gerry_geo_path=value)


# ==============
#   GeoNameStr
# ==============
class DummyGeoNameStr(BaseModel):
    geo_name_str: GeoNameStr


@pytest.mark.parametrize(
    "value",
    [
        "a1",
        "0A",
        "abcXYZ_123",
        "m-._N",
        "x" * 100,  # boundary length
    ],
)
def test_geonamestr_valid(value):
    obj = DummyGeoNameStr(geo_name_str=value)
    assert obj.geo_name_str == value


@pytest.mark.parametrize(
    "value",
    [
        "a",  # only one char
        "A0",  # cannot start uppercase
        "_foo",  # cannot start underscore
        " foo",  # leading space
        "foo$bar",  # illegal char
        "x" * 101,  # too long
    ],
)
def test_geonamestr_invalid(value):
    with pytest.raises(ValidationError):
        DummyGeoNameStr(geo_name_str=value)
