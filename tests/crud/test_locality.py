"""Tests for GerryDB CRUD operations on locality metadata."""

import pytest

from gerrydb_meta import crud, schemas
from gerrydb_meta.exceptions import CreateValueError


def test_crud_locality_create_no_parent_no_aliases(db_with_meta):
    name = "Lost City of Atlantis"
    db, meta = db_with_meta
    loc, _ = crud.locality.create(
        db=db,
        obj_in=schemas.LocalityCreate(
            canonical_path="atlantis",
            parent_path=None,
            name=name,
            aliases=None,
        ),
        obj_meta=meta,
    )
    assert loc.loc_id is not None
    assert loc.name == name


from gerrydb_meta import models


def test_crud_locality_create_bad_parent(db_with_meta):
    name = "Lost City of Atlantis"
    db, meta = db_with_meta
    db.add(
        models.LocalityRef(
            loc_id=None,
            path="bad_parent",
            meta_id=meta.meta_id,
        )
    )
    with pytest.raises(CreateValueError, match="Dangling locality reference found."):
        _ = crud.locality.create(
            db=db,
            obj_in=schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path="bad_parent",
                name=name,
                aliases=None,
            ),
            obj_meta=meta,
        )


def test_crud_locality_get_by_ref(db_with_meta):
    name = "Lost City of Atlantis"
    db, meta = db_with_meta
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path=None,
                name=name,
                aliases=["greece-atlantis"],
            ),
        ],
        obj_meta=meta,
    )
    assert crud.locality.get_by_ref(db=db, path="atlantis").loc_id == loc[0].loc_id
    assert crud.locality.get_by_ref(db=db, path="greece-atlantis").loc_id == loc[0].loc_id


def test_crud_locality_patch(db_with_meta):
    name = "Lost City of Atlantis"
    db, meta = db_with_meta
    loc, _ = crud.locality.create_bulk(
        db=db,
        objs_in=[
            schemas.LocalityCreate(
                canonical_path="atlantis",
                parent_path=None,
                name=name,
                aliases=None,
            ),
        ],
        obj_meta=meta,
    )
    loc_with_aliases, _ = crud.locality.patch(
        db=db,
        obj=loc[0],
        obj_meta=meta,
        patch=schemas.LocalityPatch(aliases=["greece-atlantis"]),
    )
    assert set(ref.path for ref in loc_with_aliases.refs) == {
        "atlantis",
        "greece-atlantis",
    }

    _ = crud.locality.patch(
        db=db,
        obj=loc[0],
        obj_meta=meta,
        patch=schemas.LocalityPatch(aliases=["greece-atlantis"]),
    )
    assert set(ref.path for ref in loc_with_aliases.refs) == {
        "atlantis",
        "greece-atlantis",
    }

    with pytest.raises(
        CreateValueError,
        match=(
            "Failed to create aliases for new location. "
            r"\(One or more aliases may already exist.\)"
        ),
    ):
        crud.locality._add_aliases(
            db=db,
            alias_paths=["greece-atlantis"],
            loc=loc[0],
            obj_meta=meta,
        )
