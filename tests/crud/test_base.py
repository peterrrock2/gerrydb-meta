import pytest

from gerrydb_meta.crud.base import *
from gerrydb_meta.exceptions import GerryPathError


def test_normalize_path_flat():
    assert normalize_path("atlantis") == "atlantis"


def test_normalize_path_case():
    assert normalize_path("Atlantis") == "atlantis"


def test_normalize_path_case_sensitive():
    assert normalize_path("Atlantis", case_sensitive_uid=True) == "Atlantis"


def test_normalize_extra_slashes():
    assert normalize_path("/greece//atlantis") == "greece/atlantis"


def test_normalize_case_sensitive_long_path():
    assert (
        normalize_path("/Greece/aTlanTis/Underworld", case_sensitive_uid=True)
        == "greece/atlantis/Underworld"
    )


def test_normalize_path_bad_substrings():
    with pytest.raises(GerryPathError, match="Please remove or replace the following substring"):
        normalize_path("greece;atlantis")

    with pytest.raises(GerryPathError, match="Please remove or replace the following substring"):
        normalize_path("greece..atlantis")

    with pytest.raises(GerryPathError, match="Please remove or replace the following substring"):
        normalize_path("greece atlantis")


def test_bad_path_lenghts():
    with pytest.raises(GerryPathError, match=r"This path has 3 segment\(s\), but should have 2"):
        normalize_path("greece/atlantis/underworld", path_length=2)

    with pytest.raises(GerryPathError, match=r"This path has 3 segment\(s\), but should have 2"):
        normalize_path("greece/atlantis/underworld", case_sensitive_uid=True, path_length=2)
