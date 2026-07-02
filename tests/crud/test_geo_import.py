from gerrydb_meta import crud, models, schemas


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


def test_crud_geo_import_create(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    assert (
        db.query(models.User).filter(models.User.user_id == geo_import.created_by).first()
        is not None
    )
    assert (
        db.query(models.Namespace)
        .filter(models.Namespace.namespace_id == geo_import.namespace_id)
        .first()
        is not None
    )


def test_crud_geo_import_get(db_with_meta):
    db, meta = db_with_meta

    ns = make_atlantis_ns(db, meta)

    geo_import, _ = crud.geo_import.create(db=db, obj_meta=meta, namespace=ns)

    assert crud.geo_import.get(db=db, uuid=geo_import.uuid) is not None
    assert crud.geo_import.get(db=db, uuid=geo_import.uuid).uuid == geo_import.uuid
    assert crud.geo_import.get(db=db, uuid=geo_import.uuid).namespace_id == geo_import.namespace_id
    assert crud.geo_import.get(db=db, uuid=geo_import.uuid).meta_id == geo_import.meta_id
    assert crud.geo_import.get(db=db, uuid=geo_import.uuid).created_by == geo_import.created_by
    assert crud.geo_import.get(db=db, uuid=geo_import.uuid).created_at == geo_import.created_at
