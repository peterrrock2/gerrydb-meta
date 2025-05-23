"""Enumerations common between database models and user-facing schemas."""

from enum import Enum


class ColumnType(str, Enum):
    """Data type of a column."""

    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STR = "str"
    JSON = "json"


class ColumnKind(str, Enum):
    """Meaning of a column."""

    COUNT = "count"
    PERCENT = "percent"
    CATEGORICAL = "categorical"
    IDENTIFIER = "identifier"
    AREA = "area"
    OTHER = "other"


class ScopeType(str, Enum):
    """An abstract scope (no namespace information)."""

    NAMESPACE_READ = "namespace:read:*"
    NAMESPACE_WRITE = "namespace:write:*"
    NAMESPACE_WRITE_DERIVED = "namespace:write_derived:*"
    NAMESPACE_CREATE = "namespace:create"
    LOCALITY_READ = "locality:read"
    LOCALITY_WRITE = "locality:write"
    META_READ = "meta:read"
    META_WRITE = "meta:write"
    ALL = "all"

    def __str__(self):
        return self.value


class GroupPermissions(str, Enum):
    """A user group.

    User groups are used to determine which users can access which namespaces.
    This is not intended to be exhaustive, but rather to provide for some
    common use cases.
    """

    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    PUBLIC = "public"


class NamespaceGroup(str, Enum):
    """A namespace group.

    Namespace groups only exist for authorization and are not intended to change
    over time---they simply allow us to distinguish between public namespaces
    (more or less visible to anyone with access to the Gerry instance)
    and private namespaces (visible only to users with explicit permissions).
    """

    PUBLIC = "public"
    PRIVATE = "private"
    ALL = "all"


class ViewRenderStatus(str, Enum):
    """Job queue status of a rendered view."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


class GraphRenderStatus(str, Enum):
    """Job queue status of a rendered graph."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
