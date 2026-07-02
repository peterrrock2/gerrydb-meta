"""Scopes (permissions) and role management."""

from dataclasses import dataclass

from uvicorn.config import logger as log

from gerrydb_meta.enums import NamespaceGroup, ScopeType
from gerrydb_meta.models import Namespace, User


@dataclass
class ScopeManager:
    """Common scopes/permissions queries for a user."""

    user: User

    def __post_init__(self):
        # Cache and aggregate scopes, which are eagerly loaded.
        user_group_scopes = {
            (scope.scope, scope.namespace_group)
            for scope in self.user.scopes
            if scope.namespace_id is None and scope.namespace_group is not None
        }
        user_namespace_scopes = {
            (scope.scope, scope.namespace_id)
            for scope in self.user.scopes
            if scope.namespace_id is not None and scope.namespace_group is None
        }
        user_global_scopes = {
            scope.scope
            for scope in self.user.scopes
            if scope.namespace_id is None
            and (scope.namespace_group is None or scope.namespace_group == NamespaceGroup.ALL)
        }
        group_group_scopes = {
            (scope.scope, scope.namespace_group)
            for group in self.user.groups
            for scope in group.group.scopes
            if scope.namespace_id is None and scope.namespace_group is not None
        }
        group_namespace_scopes = {
            (scope.scope, scope.namespace_id)
            for group in self.user.groups
            for scope in group.group.scopes
            if scope.namespace_id is not None and scope.namespace_group is None
        }
        group_global_scopes = {
            scope.scope
            for group in self.user.groups
            for scope in group.group.scopes
            if scope.namespace_id is None
            and (scope.namespace_group is None or scope.namespace_group == NamespaceGroup.ALL)
        }
        self._namespace_scopes = user_namespace_scopes | group_namespace_scopes
        self._namespace_group_scopes = user_group_scopes | group_group_scopes
        self._global_scopes = user_global_scopes | group_global_scopes

    def can_read_localities(self) -> bool:
        return self.has_global_scope(ScopeType.LOCALITY_READ)

    def can_write_localities(self) -> bool:
        return self.has_global_scope(ScopeType.LOCALITY_WRITE)

    def can_read_meta(self) -> bool:
        return self.has_global_scope(ScopeType.META_READ)

    def can_write_meta(self) -> bool:
        return self.has_global_scope(ScopeType.META_WRITE)

    def can_create_namespace(self) -> bool:
        return self.has_global_scope(ScopeType.NAMESPACE_CREATE)

    def can_read_in_namespace(self, namespace: Namespace) -> bool:
        return self.has_namespace_scope(ScopeType.NAMESPACE_READ, namespace)

    def can_write_in_namespace(self, namespace: Namespace) -> bool:
        return self.has_namespace_scope(ScopeType.NAMESPACE_WRITE, namespace)

    def can_write_derived_in_namespace(self, namespace: Namespace) -> bool:
        return self.has_namespace_scope(
            ScopeType.NAMESPACE_WRITE_DERIVED, namespace
        ) or self.has_namespace_scope(ScopeType.NAMESPACE_WRITE, namespace)

    def can_read_in_public_namespaces(self) -> bool:
        return self.has_namespace_group_scope(ScopeType.NAMESPACE_READ, NamespaceGroup.PUBLIC)

    def has_global_scope(self, scope: ScopeType) -> bool:
        """Does the user have the global scope `scope`?"""
        log.debug("Checking %s for %s", scope, self.user.name)
        return ScopeType.ALL in self._global_scopes or scope in self._global_scopes

    def has_namespace_scope(self, scope: ScopeType, namespace: Namespace) -> bool:
        """Does the user have `scope` in `namespace`?"""
        log.debug("Checking %s for %s", scope, namespace)
        candidates = {
            (scope, namespace.namespace_id),
            (ScopeType.ALL, namespace.namespace_id),
        }
        group = NamespaceGroup.PUBLIC if namespace.public else NamespaceGroup.PRIVATE
        return self.has_namespace_group_scope(scope, group) or bool(
            self._namespace_scopes & candidates
        )

    def has_namespace_group_scope(self, scope: ScopeType, group: NamespaceGroup) -> bool:
        """Does the user have `scope` in `group`?"""
        candidates = {
            (scope, group),
            (ScopeType.ALL, group),
            (scope, NamespaceGroup.ALL),
            (ScopeType.ALL, NamespaceGroup.ALL),
        }
        return bool(candidates & self._namespace_group_scopes)
