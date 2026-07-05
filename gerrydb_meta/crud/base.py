"""Generic CR(UD) operations."""

# Based on the `full-stack-fastapi-postgresql` template:
#   https://github.com/tiangolo/full-stack-fastapi-postgresql/
#   blob/490c554e23343eec0736b06e59b2108fdd057fdc/
#   %7B%7Bcookiecutter.project_slug%7D%7D/backend/app/app/crud/base.py
import uuid
from abc import ABC, abstractmethod
from typing import Any, Generic, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gerrydb_meta.exceptions import GerryPathError
from gerrydb_meta.models import Base, ETag, Namespace, ObjectMeta

ModelType = TypeVar("ModelType", bound=Base)
GetSchemaType = TypeVar("GetSchemaType", bound=BaseModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
PatchSchemaType = TypeVar("PatchSchemaType", bound=BaseModel)

# These characters are most likely to appear in the resource_id part of
# a path (typically the last segment). Exclusion of these characters
# prevents ogr2ogr fails and helps protect against malicious code injection.
# Most of these are caught by Pydantic validation, but these have slipped
# through the cracks in the past, so we keep this check here just in case.
INVALID_PATH_SUBSTRINGS = set({"..", " ", ";", "\\", "./"})


def normalize_path(
    path: str, case_sensitive_uid: bool = False, path_length: Optional[int] = None
) -> str:
    """Normalizes a path (removes leading, trailing, and duplicate slashes, and
    lowercases the path if `case_sensitive_uid` is `False`).

    Some paths, such as paths containing GEOIDs, are case-sensitive in the last
    segment. In these cases, `case_sensitive_uid` should be set to `True`.
    """
    for item in INVALID_PATH_SUBSTRINGS:
        if item in path:
            raise GerryPathError(
                f"Invalid path: '{path}'. Please remove or replace the following substring "
                f"wherever it occurs: '{item}'"
            )

    if case_sensitive_uid:
        # Don't make a list with empty things. So substrings like "///" don't
        # cause issues
        path_list = [seg for seg in path.strip().split("/") if seg]

        if path_length is not None and len(path_list) != path_length:
            raise GerryPathError(
                f"Invalid path: '{path}'. This path has {len(path_list)} segment(s), but "
                f"should have {path_length}"
            )

        return "/".join(
            seg.lower() if i < len(path_list) - 1 else seg for i, seg in enumerate(path_list) if seg
        )

    path_list = [seg for seg in path.strip().lower().split("/") if seg]

    if path_length is not None and len(path_list) != path_length:
        raise GerryPathError(
            f"Invalid path: '{path}'. This path has {len(path_list)} segment(s), but "
            f"should have {path_length}."
        )

    return "/".join(path_list)


class CRBase(Generic[ModelType, CreateSchemaType], ABC):
    model: Type[ModelType]

    def __init__(self, model: Type[ModelType]):
        """
        CR object with default methods to create and read.

        Args:
            model: A SQLAlchemy model class.
        """
        self.model = model

    @abstractmethod
    def get(self, db: Session, id: Any) -> Optional[ModelType]:  # pragma: no cover
        pass

    def all(self, db: Session) -> List[ModelType]:
        return db.query(self.model).all()

    @abstractmethod
    def create(
        self, db: Session, *, obj_in: CreateSchemaType
    ) -> Tuple[ModelType, uuid.UUID]:  # pragma: no cover
        pass

    def etag(self, db: Session) -> uuid.UUID | None:
        """Retrieves the latest UUID-format ETag for the collection."""
        etag = (
            db.query(ETag.etag)
            .filter(ETag.table == self.model.__tablename__, ETag.namespace_id.is_(None))
            .first()
        )
        return None if etag is None else etag[0]

    def _update_etag(self, db: Session) -> uuid.UUID:
        """Refreshes the (object, namespace) ETag."""
        new_etag = uuid.uuid4()
        stmt = (
            insert(ETag)
            .values(table=self.model.__tablename__, namespace_id=None, etag=new_etag)
            .on_conflict_do_update(
                index_elements=["table", "namespace_id"], set_={"etag": new_etag}
            )
        )
        db.execute(stmt)
        return new_etag


class NamespacedCRBase(Generic[ModelType, CreateSchemaType], ABC):
    model: Type[ModelType]

    def __init__(self, model: Type[ModelType]):
        """
        Namespaced CR object with default methods to create and read.

        Args:
            model: A SQLAlchemy model class.
        """
        self.model = model

    @abstractmethod
    def get(
        self, db: Session, namespace: Namespace, path: Any
    ) -> Optional[ModelType]:  # pragma: no cover
        pass

    def all_in_namespace(
        self,
        db: Session,
        *,
        namespace: Namespace,
        limit: int | None = None,
        offset: int = 0,
    ) -> List[ModelType]:
        query = db.query(self.model).filter(self.model.namespace_id == namespace.namespace_id)
        if limit is not None or offset:
            # Deterministic order only when paginating (order by primary key:
            # not every model has a path column); unpaginated listings keep
            # their historical arbitrary order.
            query = query.order_by(*self.model.__mapper__.primary_key).offset(offset)
            if limit is not None:
                query = query.limit(limit)
        return query.all()

    @abstractmethod
    def create(
        self,
        db: Session,
        *,
        obj_in: CreateSchemaType,
        namespace: Namespace,
        obj_meta: ObjectMeta,
    ) -> Tuple[ModelType, uuid.UUID]:  # pragma: no cover
        pass

    def etag(self, db: Session, namespace: Namespace) -> uuid.UUID | None:
        """Retrieves the latest UUID-format ETag for the collection."""
        etag = (
            db.query(ETag.etag)
            .filter(
                ETag.table == self.model.__tablename__,
                ETag.namespace_id == namespace.namespace_id,
            )
            .first()
        )
        return None if etag is None else etag[0]

    def _update_etag(self, db: Session, namespace: Namespace) -> uuid.UUID:
        """Refreshes the (object, namespace) ETag."""
        new_etag = uuid.uuid4()
        stmt = (
            insert(ETag)
            .values(
                table=self.model.__tablename__,
                namespace_id=namespace.namespace_id,
                etag=new_etag,
            )
            .on_conflict_do_update(
                index_elements=["table", "namespace_id"], set_={"etag": new_etag}
            )
        )
        db.execute(stmt)
        return new_etag


class ReadOnlyBase(Generic[ModelType], ABC):
    def __init__(self, model: Type[ModelType]):
        """
        Read-only object base.
        **Parameters**
        * `model`: A SQLAlchemy model class
        """
        self.model = model

    @abstractmethod
    def get(self, db: Session, id: Any) -> Optional[ModelType]:  # pragma: no cover
        pass

    def all(self, db: Session) -> List[ModelType]:  # pragma: no cover
        return db.query(self.model).all()
