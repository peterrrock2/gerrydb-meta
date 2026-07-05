"""Administration tools for GerryDB."""

import csv
import os
import secrets
import string
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha512
from pathlib import Path
from typing import Optional, Tuple

import click
from sqlalchemy.orm import Session as SessionType
from uvicorn.config import logger as log

from gerrydb_meta.crud.column import hash_rebuild_select
from gerrydb_meta.crud.obj_meta import obj_meta
from gerrydb_meta.db import Session
from gerrydb_meta.enums import GroupPermissions, NamespaceGroup, ScopeType
from gerrydb_meta.models import (
    ApiKey,
    Namespace,
    ObjectMeta,
    User,
    UserGroup,
    UserGroupMember,
    UserGroupScope,
    UserScope,
)
from gerrydb_meta.schemas import ObjectMetaCreate

GERRYDB_SQL_ECHO = bool(os.environ.get("GERRYDB_SQL_ECHO", False))

API_KEY_CHARS = string.ascii_lowercase + string.digits

scope_type_dict = {
    "locality:read": ScopeType.LOCALITY_READ,
    "locality:write": ScopeType.LOCALITY_WRITE,
    "meta:read": ScopeType.META_READ,
    "meta:write": ScopeType.META_WRITE,
    "namespace:create": ScopeType.NAMESPACE_CREATE,
    "namespace:read": ScopeType.NAMESPACE_READ,
    "namespace:write": ScopeType.NAMESPACE_WRITE,
    "namespace:write:derived": ScopeType.NAMESPACE_WRITE_DERIVED,
    "all": ScopeType.ALL,
}


def _generate_api_key() -> tuple[str, bytes]:
    """Generates a random API key (64 characters, a-z0-9).

    Returns:
        A 2-tuple containing:
            (1) The raw key.
            (2) A binary digest of the SHA512 hash of the key.
    """
    key = "".join(secrets.choice(API_KEY_CHARS) for _ in range(64))

    # Just a sanity check to make sure that the test key (which is NOT secure)
    # is not accidentally used in production. This is totally overkill, but it
    # makes me feel better
    test_key = "7w7uv9mi575n2dhlmg3wqba2imv1aqdys387tpbtpermujy1tuyqbxetygx8u3fr"
    redraws = 0
    while key == test_key and redraws < 3:  # pragma: no cover
        key = "".join(secrets.choice(API_KEY_CHARS) for _ in range(64))  # pragma: no cover
        redraws += 1  # pragma: no cover

    if redraws >= 3:  # pragma: no cover
        raise RuntimeError("Failed to generate a unique API key.")  # pragma: no cover

    key_hash = sha512(key.encode("utf-8")).digest()
    return key, key_hash


def grant_scope(
    db: SessionType,
    user: User,
    scopes: list[ScopeType] | ScopeType,
    *,
    meta: ObjectMeta,
    namespace_group: Optional[NamespaceGroup] = None,
    namespace_id: Optional[int] = None,
) -> None:
    """Grants a scope to a user."""

    # Can only have the namespace or the namespace group, not both.
    assert (namespace_group is None) ^ (namespace_id is None)
    assert meta is not None

    if isinstance(scopes, ScopeType):
        scopes = [scopes]

    for scope in scopes:
        scope = UserScope(
            user_id=user.user_id,
            scope=scope,
            namespace_group=namespace_group,
            namespace_id=namespace_id,
            meta_id=meta.meta_id,
        )
        db.add(scope)

    db.flush()
    db.refresh(user)


def grant_user_group_scope(
    db: SessionType,
    group: UserGroup,
    scopes: list[ScopeType] | ScopeType,
    *,
    meta: ObjectMeta,
    namespace_group: Optional[NamespaceGroup] = None,
    namespace_id: Optional[int] = None,
) -> None:
    """Grants a scope to a user group."""

    # Can only have the namespace or the namespace group, not both.
    assert namespace_group is None or namespace_id is None
    assert meta is not None

    if isinstance(scopes, ScopeType):
        scopes = [scopes]

    for scope in scopes:
        scope = UserGroupScope(
            group_id=group.group_id,
            scope=scope,
            namespace_group=namespace_group,
            namespace_id=namespace_id,
            meta_id=meta.meta_id,
        )
        db.add(scope)
        db.flush()
        db.refresh(group)


def check_admin(db: SessionType, user: User) -> bool:
    """Checks if the user is an admin."""
    admin_group = (
        db.query(UserGroupMember)
        .join(UserGroup, UserGroupMember.group_id == UserGroup.group_id)
        .filter(UserGroup.name == "admin", UserGroupMember.user_id == user.user_id)
        .first()
    )

    admin_scope = (
        db.query(UserScope)
        .filter(
            user.user_id == UserScope.user_id,
            UserScope.scope == "all",
            UserScope.namespace_group == "all",
        )
        .first()
    )

    if admin_group is None and admin_scope is None:
        return False

    return True


def validate_admin(db: SessionType, user: User):
    if not check_admin(db, user):
        raise ValueError("User is not an admin.")


@dataclass(frozen=True)
class GerryAdmin:
    """Common GerryDB administration operations."""

    session: SessionType

    def initial_user_create(self, email: str, name: str) -> User:
        """
        Used to create the first user in the database. This user will be a superuser and will
        be added to the admin group. If there are any users in the database already,
        this function will raise a `ValueError`.

        Args:
            email: The user's email address.
            name: The user's name.

        Returns:
            The new user.
        """

        if self.session.query(User).count() > 0:
            raise ValueError("Cannot create the first user in the database (users already exist).")

        if self.session.query(UserGroup).count() > 0:  # pragma: no cover
            raise ValueError(  # pragma: no cover
                "Cannot create the first user in the database (user groups already exist)."
            )

        user = User(email=email, name=name)
        log.info("Created new user: %s", user)
        self.session.add(user)
        self.session.flush()
        self.session.refresh(user)

        meta_obj = ObjectMeta(
            created_by=user.user_id, notes="Used for authorization configuration only."
        )
        self.session.add(meta_obj)
        self.session.flush()
        self.session.refresh(meta_obj)

        grant_scope(
            self.session,
            user,
            scopes=ScopeType.ALL,
            namespace_group=NamespaceGroup.ALL,
            meta=meta_obj,
        )

        group = self.user_group_create(
            name=GroupPermissions.ADMIN,
            description="Users with admin privileges in the database.",
            meta=meta_obj,
        )

        self.add_user_to_group(user=user, group=group, meta=meta_obj)

        grant_user_group_scope(
            db=self.session,
            group=group,
            scopes=ScopeType.ALL,
            meta=meta_obj,
            namespace_group=NamespaceGroup.ALL,
        )

        return user

    def user_create(
        self,
        email: str,
        name: str,
        group_perm: GroupPermissions,
        creator: User,
        meta_obj: Optional[ObjectMeta] = None,
    ) -> User:
        """
        Used to create a new user in the database. The user is assigned according to the
        `group_perm` argument which classifies the GroupPermissions they have access to.
        Generally, there are three groups:

        - public: Users in this group can read data from public namespaces, but cannot
            edit anything.
        - contributor: Users in this group can read data from pulbic namespaces, and can
            create their own public or private namespaces. Contributors can also write data
            to the namespace that they create, but cannot edit any other namespaces.
            Contributors are not granted read access to the metadata table since that table
            can contain information about other users' private namespaces.
        - admin: Users in this group can read and write data to all namespaces. Admins also
            gain access to the full metadata table.

        Args:
            email: The user's email address.
            name: The user's name.
            group_perm: The type of user group to create.
            creator: The user that added this user to the database.

        Returns:
            The new user.
        """

        assert isinstance(group_perm, GroupPermissions)

        user = User(email=email, name=name)
        log.info("Created new user: %s", user)
        self.session.add(user)
        self.session.flush()
        self.session.refresh(user)

        if meta_obj is None:
            meta_obj = obj_meta.create(
                db=self.session,
                obj_in=ObjectMetaCreate(notes="Creating a new user group."),
                user=creator,
            )

        if group_perm == GroupPermissions.ADMIN:
            group = self.user_group_find_by_name(GroupPermissions.ADMIN)

            # This should never happen, but just in case.
            if group is None:  # pragma: no cover
                group = self.user_group_create(  # pragma: no cover
                    name=GroupPermissions.ADMIN,
                    description="Users with admin privileges in the database.",
                    meta=meta_obj,
                )
                grant_user_group_scope(  # pragma: no cover
                    db=self.session,
                    group=group,
                    scopes=ScopeType.ALL,
                    meta=meta_obj,
                    namespace_group=NamespaceGroup.ALL,
                )

        elif group_perm == GroupPermissions.CONTRIBUTOR:
            try:
                group = self.user_group_find_by_name(GroupPermissions.CONTRIBUTOR)
            except ValueError:
                group = self.user_group_create(
                    name=GroupPermissions.CONTRIBUTOR,
                    description="Users with contributor privileges in the database.",
                    meta=meta_obj,
                )

                grant_user_group_scope(
                    db=self.session,
                    group=group,
                    scopes=[
                        ScopeType.NAMESPACE_READ,
                        ScopeType.NAMESPACE_WRITE_DERIVED,
                    ],
                    meta=meta_obj,
                    namespace_group=NamespaceGroup.PUBLIC,
                )

                grant_user_group_scope(
                    db=self.session,
                    group=group,
                    scopes=[
                        ScopeType.NAMESPACE_CREATE,
                        ScopeType.LOCALITY_READ,
                        ScopeType.LOCALITY_WRITE,
                        ScopeType.META_WRITE,
                    ],
                    meta=meta_obj,
                )
        else:
            try:
                group = self.user_group_find_by_name("public")
            except ValueError:
                group = self.user_group_create(
                    name=GroupPermissions.PUBLIC,
                    description="Users that can read data from public namespaces.",
                    meta=meta_obj,
                )

                grant_user_group_scope(
                    db=self.session,
                    group=group,
                    scopes=[
                        ScopeType.NAMESPACE_READ,
                        ScopeType.NAMESPACE_WRITE_DERIVED,
                    ],
                    meta=meta_obj,
                    namespace_group=NamespaceGroup.PUBLIC,
                )

                grant_user_group_scope(
                    db=self.session,
                    group=group,
                    scopes=ScopeType.LOCALITY_READ,
                    meta=meta_obj,
                )

                log.info("Created public user group: %s", group)

        self.add_user_to_group(user=user, group=group, meta=meta_obj)

        return user

    def user_group_create(
        self, name: str, description: str, meta: ObjectMeta
    ) -> Tuple[UserGroup, ObjectMeta]:

        user_group = UserGroup(name=name, description=description, meta_id=meta.meta_id)

        self.session.add(user_group)
        self.session.flush()
        self.session.refresh(user_group)

        return user_group

    def user_group_find_by_name(self, name: str) -> Optional[UserGroup]:
        user_group = self.session.query(UserGroup).filter(UserGroup.name == name).first()
        if user_group is None:
            raise ValueError(f"No user group found with name {name}.")
        log.info("Found %s.", user_group)
        return user_group

    def add_user_to_group(self, user: User, group: UserGroup, meta: ObjectMeta) -> None:
        """Adds a user to a user group."""
        user_member = self.session.query(UserGroupMember).filter(
            UserGroupMember.user_id == user.user_id,
            UserGroupMember.group_id == group.group_id,
        )

        if user_member.first() is not None:
            log.info("User %s is already in group %s.", user, group)
            return

        user_member = UserGroupMember(
            user_id=user.user_id,
            group_id=group.group_id,
            meta_id=meta.meta_id,
        )

        group.users.append(user_member)
        log.info("Added %s to %s.", user, group)
        self.session.add(group)
        self.session.flush()
        self.session.refresh(group)

    def user_find_by_email(self, email: str) -> User:
        """Returns an existing user by email or raises a `ValueError`."""
        user = self.session.query(User).filter(User.email == email).first()
        if user is None:
            raise ValueError(f"No user found with email {email}.")
        log.info("Found %s.", user)
        return user

    def user_find_by_id(self, id: int) -> User:
        """Returns an existing user by email or raises a `ValueError`."""
        user = self.session.query(User).filter(User.user_id == id).first()
        if user is None:
            raise ValueError(f"No user found with id {id}.")
        log.info("Found %s.", user)
        return user

    def user_deactivate(self, user: User) -> None:
        """Deactivates all API keys for a user."""
        for api_key in user.api_keys:
            log.info("Deactivating API key for %s", user)
            api_key.active = False
        log.info("Deactivated %d API keys for %s", len(user.api_keys), user)

    def key_create(self, user: User) -> ApiKey:
        """Creates a new API key for an existing user.

        Returns:
            The raw API key.
        """
        raw_key, key_hash = _generate_api_key()
        log.info("Generated new API key for %s.", user)
        self.session.add(ApiKey(user=user, key_hash=key_hash))
        return raw_key

    def create_test_key(self, user: User, force: bool = False) -> str:
        """
        Creates a known API key for testing purposes.

        Args:
            user: The user to add the known test key to.

        Returns:
            The raw API key.
        """
        if not force:
            user_confirmation = input(
                f"You are about to create a TESTING API key for user {user}. "
                f"This API key is NOT secure and should be considered public knowledge. "
                "Are you sure you want to continue? Y/N: "
            )

            if user_confirmation.lower() != "y":
                raise ValueError("User aborted API key creation.")

        print()
        raw_key = "7w7uv9mi575n2dhlmg3wqba2imv1aqdys387tpbtpermujy1tuyqbxetygx8u3fr"
        key_hash = sha512(raw_key.encode("utf-8")).digest()
        log.info("Generated new ***TESTING*** API key for %s.", user)
        self.session.add(ApiKey(user=user, key_hash=key_hash))
        return raw_key

    def key_by_raw(self, raw_key: str) -> ApiKey:
        """Returns an existing API by raw value or raises a `ValueError`."""
        key_hash = sha512(raw_key.encode("utf-8")).digest()
        db_key = self.session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
        if db_key is None:
            raise ValueError("No API key found with hash of specified raw key.")
        return db_key

    def key_deactivate(self, api_key: ApiKey) -> None:
        """Deactivates an API key for a user."""
        log.info("Deactivating API key...")
        api_key.active = False


@click.group()
def cli():
    """Administration tools for GerryDB."""


@contextmanager
def admin_context():
    session = Session()
    admin = GerryAdmin(session)
    try:
        yield admin
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


# This will only be used in testing.
@cli.command("init:user")
@click.option("--user-email", required=True)
@click.option("--name", required=True)
def create_first_user(user_email: str, name: str):
    """Creates the first user in the database. This user will be a superuser and will
    be added to the admin group. If there are any users in the database already,
    this function will raise a `ValueError`."""
    with admin_context() as admin:
        user = admin.initial_user_create(name=name, email=user_email)
        print(f"New user {user} created.")
        raw_key = admin.key_create(user)
        print(f"New API key for new {user}: {raw_key}")


@cli.command("user:create")
@click.option("-u", "--user-email", required=True)
@click.option("--name", required=True)
@click.option(
    "--group-perm",
    type=click.Choice([g.value for g in GroupPermissions], case_sensitive=False),
    default=GroupPermissions.PUBLIC.value,
    required=True,
    help="Which group to add the user into (public, contributor, admin).",
)
@click.option("-c", "--creator-email", required=True)
def user_create(user_email, name, group_perm, creator_email):
    """Creates a new user for the database, adds them to the specified group, and then
    generates a new API key for them.
    """
    gp_enum = GroupPermissions(group_perm.lower())
    with admin_context() as admin:
        creator = admin.user_find_by_email(creator_email)
        validate_admin(admin.session, creator)

        user = admin.user_create(email=user_email, name=name, group_perm=gp_enum, creator=creator)
        raw_key = admin.key_create(user)
        print(f"New API key for new {user}: {raw_key}")


@cli.command("usergroup:create")
@click.option("--name", required=True)
@click.option("--description", required=True)
@click.option("-c", "--creator-email", required=True)
def usergroup_create(name: str, description: str, creator_email: str):
    with admin_context() as admin:
        creator = admin.user_find_by_email(creator_email)
        validate_admin(admin.session, creator)

        try:
            admin.user_group_find_by_name(name)
        except ValueError:
            pass
        else:
            raise ValueError(f"User group '{name}' already exists.")

        meta_obj = obj_meta.create(
            db=admin.session,
            obj_in=ObjectMetaCreate(notes=f"Creating the user group '{name}'."),
            user=creator,
        )

        user_group = admin.user_group_create(name=name, description=description, meta=meta_obj)
        print(f"New user group: {user_group}")


@cli.command("user:grant")
@click.option("-u", "--user-email", required=True)
@click.option(
    "-s",
    "--scope",
    type=click.Choice([s for s in scope_type_dict.keys()], case_sensitive=False),
    required=True,
    multiple=True,
)
@click.option(
    "-c",
    "--creator-email",
    required=True,
    help="The email of the user granting the permissions.",
)
@click.option(
    "-ns",
    "--namespace",
    type=str,
    required=False,
    help="The namespace to grant the permissions in.",
    default=None,
)
@click.option(
    "-ng",
    "--namespace-group",
    required=False,
    type=click.Choice(["public", "private", "all", None]),
    help="The namespace group to grant the permissions in.",
    default=None,
)
def user_grant(
    user_email: str,
    scope: str,
    creator_email: str,
    namespace: Optional[str],
    namespace_group: Optional[str],
):
    scopes = [scope_type_dict[s] for s in scope]
    assert (namespace is None) ^ (namespace_group is None), (
        "Must specify exactly one of namespace or namespace group."
    )

    with admin_context() as admin:
        user = admin.user_find_by_email(user_email)
        creator = admin.user_find_by_email(creator_email)

        validate_admin(admin.session, creator)

        namespace_id = None
        if namespace is not None:
            namespace_id = (
                admin.session.query(Namespace.namespace_id)
                .filter(Namespace.path == namespace)
                .first()
            )
            if namespace_id is None:
                raise ValueError(f"No namespace found with path {namespace}.")

            # Unpack the tuple
            namespace_id = namespace_id[0]

        meta_obj = obj_meta.create(
            db=admin.session,
            obj_in=ObjectMetaCreate(notes=f"Granting '{scopes}' to '{user}'."),
            user=creator,
        )

        grant_scope(
            db=admin.session,
            user=user,
            scopes=scopes,
            meta=meta_obj,
            namespace_group=namespace_group,
            namespace_id=namespace_id,
        )


@cli.command("user:add:group")
@click.option("-u", "--user-email", required=True, multiple=True)
@click.option("-g", "--group", required=True)
@click.option("-c", "--creator-email", required=True)
def user_add_group(user_email: str, group: str, creator_email: str):
    with admin_context() as admin:
        users = [admin.user_find_by_email(email) for email in user_email]
        group = admin.user_group_find_by_name(group)
        creator = admin.user_find_by_email(creator_email)

        validate_admin(admin.session, creator)

        meta_obj = obj_meta.create(
            db=admin.session,
            obj_in=ObjectMetaCreate(notes=f"Adding '{users}' to group '{group}'."),
            user=creator,
        )

        for user in users:
            admin.add_user_to_group(user=user, group=group, meta=meta_obj)


@cli.command("usergroup:grant")
@click.option("-g", "--group", required=True)
@click.option(
    "-s",
    "--scope",
    type=click.Choice([s for s in scope_type_dict.keys()], case_sensitive=False),
    required=True,
    multiple=True,
)
@click.option(
    "-c",
    "--creator-email",
    required=True,
    help="The email of the user granting the permissions.",
    default=None,
)
@click.option(
    "-ns",
    "--namespace",
    type=str,
    required=False,
    help="The namespace to grant the permissions in.",
    default=None,
)
@click.option(
    "-ng",
    "--namespace-group",
    required=False,
    type=click.Choice(["public", "private", "all", None]),
    help="The namespace group to grant the permissions in.",
    default=None,
)
def usergroup_grant(
    group: str, scope: str, creator_email: str, namespace: str, namespace_group: str
):
    scopes = [scope_type_dict[s] for s in scope]
    assert (namespace is None) ^ (namespace_group is None), (
        "Must specify exactly one of namespace or namespace group."
    )

    with admin_context() as admin:
        creator = admin.user_find_by_email(creator_email)
        group = admin.user_group_find_by_name(group)

        validate_admin(admin.session, creator)

        namespace_id = None
        if namespace is not None:
            namespace_id = (
                admin.session.query(Namespace.namespace_id)
                .filter(Namespace.path == namespace)
                .first()
            )
            if namespace_id is None:
                raise ValueError(f"No namespace found with path {namespace}.")

            # Unpack the tuple
            namespace_id = namespace_id[0]

        meta_obj = obj_meta.create(
            db=admin.session,
            obj_in=ObjectMetaCreate(notes=f"Granting '{scopes}' to group '{group}'."),
            user=creator,
        )

        grant_user_group_scope(
            db=admin.session,
            group=group,
            scopes=scopes,
            meta=meta_obj,
            namespace_group=namespace_group,
            namespace_id=namespace_id,
        )
        print(f"Granted {scope} to {group}")


@cli.command("user:create:bulk")
@click.option("--roster", "roster_path", type=click.Path(path_type=Path), required=True)
@click.option("--keys", "keys_path", type=click.Path(path_type=Path), required=True)
@click.option("-c", "--creator-email", required=True)
def bulk_user_create(roster_path: Path, keys_path: Path, creator_email: str):
    """Creates users with active API keys in bulk.

    Expects a roster CSV with `name`, `email`, and `group_perm` columns.
    Generates a CSV with `name`, `email`, and `key` columns.
    """
    accounts = []

    creator = None
    with admin_context() as admin, open(roster_path, newline="") as roster_fp:
        creator = admin.user_find_by_email(creator_email)

        validate_admin(admin.session, creator)

        meta_obj = obj_meta.create(
            db=admin.session,
            obj_in=ObjectMetaCreate(notes=f"Creating users with API keys."),
            user=creator,
        )

        for row in csv.DictReader(roster_fp):
            name = row["name"].strip()
            email = row["email"].lower().strip()
            perms = GroupPermissions(row["group_perm"].strip())
            print(f"Creating user {name} with email {email} and group {perms}.")
            user = admin.user_create(
                name=name,
                email=email,
                group_perm=perms,
                creator=creator,
                meta_obj=meta_obj,
            )
            raw_key = admin.key_create(user)
            accounts.append({"name": user.name, "email": user.email, "key": str(raw_key)})

    print(f"Generated {len(accounts)} new accounts.")
    with open(keys_path, "w", newline="") as keys_fp:
        writer = csv.DictWriter(keys_fp, fieldnames=["name", "email", "key"])
        writer.writeheader()
        for account in accounts:
            writer.writerow(account)


@cli.command("key:create")
@click.option("--email", required=True)
def key_create(email: str):
    """Creates a new API key for an existing user."""
    with admin_context() as admin:
        user = admin.user_find_by_email(email)
        raw_key = admin.key_create(user)
        print(f"New API key for existing {user}: {raw_key}")


@cli.command("user:deactivate")
@click.option("--email", required=True)
def user_deactivate(email: str):
    """Deactivates all API keys associated with a user."""
    with admin_context() as admin:
        user = admin.user_find_by_email(email)
        admin.user_deactivate(user)


@cli.command("key:deactivate")
@click.option("--key", required=True)
def key_deactivate(key: str):
    """Deactivates a single API key."""
    with admin_context() as admin:
        db_key = admin.key_by_raw(key)
        admin.key_deactivate(db_key)


@cli.command("user:check:admin")
@click.option("--email", required=True)
def user_check_admin(email: str):
    """Checks if a user is an admin."""
    with admin_context() as admin:
        user = admin.user_find_by_email(email)
        is_admin = check_admin(admin.session, user)
        print(f"User {user} is an admin: {is_admin}")


@cli.command("render:sweep")
@click.option("--dry-run", is_flag=True, help="List orphaned render tables without dropping.")
def render_sweep(dry_run: bool):
    """Drops orphaned render_* tables.

    Renders materialize into gerrydb.render_<uuid> tables that the API drops
    when the GeoPackage is written; a process dying mid-render leaves the
    table behind. Only run while no renders are in flight (an in-flight
    render's table is indistinguishable from an orphan).
    """
    from sqlalchemy import text

    with admin_context() as admin:
        rows = admin.session.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'gerrydb'
                  AND c.relkind = 'r'
                  AND c.relname ~ '^render_[0-9a-f]{32}$'
                ORDER BY c.relname
                """
            )
        ).all()
        if not rows:
            print("No render tables found.")
            return
        for (relname,) in rows:
            if dry_run:
                print(f"orphan: gerrydb.{relname}")
            else:
                admin.session.execute(text(f"DROP TABLE IF EXISTS gerrydb.{relname}"))
                print(f"dropped: gerrydb.{relname}")
        if not dry_run:
            admin.session.commit()


@cli.command("stats:revalidate")
@click.option("--fix", is_flag=True, help="Rewrite drifted rows instead of only reporting.")
def stats_revalidate(fix: bool):
    """Recomputes current-value counts from column_value and compares them to
    the column_value_count stats table.

    View-create validation reads the stats table instead of scanning
    column_value; this is the on-demand full scan. Only current set versions
    are checked and fixed: deprecated versions intentionally keep the counts
    they had when deprecated. Expect the scan to take a while on a loaded
    database.
    """
    from sqlalchemy import text

    drift_sql = text(
        """
        WITH actual AS (
            SELECT cv.col_id, m.set_version_id, COUNT(*) AS n
            FROM gerrydb.column_value cv
            JOIN gerrydb.geo_set_member m ON m.geo_id = cv.geo_id
            JOIN gerrydb.geo_set_version sv
                ON sv.set_version_id = m.set_version_id
            WHERE cv.valid_to IS NULL AND sv.valid_to IS NULL
            GROUP BY cv.col_id, m.set_version_id
        ),
        stored AS (
            SELECT c.col_id, c.set_version_id, c.count
            FROM gerrydb.column_value_count c
            JOIN gerrydb.geo_set_version sv
                ON sv.set_version_id = c.set_version_id
            WHERE sv.valid_to IS NULL
        )
        SELECT
            COALESCE(a.col_id, s.col_id) AS col_id,
            COALESCE(a.set_version_id, s.set_version_id) AS set_version_id,
            s.count AS stored,
            a.n AS actual
        FROM actual a
        FULL OUTER JOIN stored s
            ON s.col_id = a.col_id AND s.set_version_id = a.set_version_id
        WHERE COALESCE(s.count, -1) <> COALESCE(a.n, -1)
        ORDER BY 1, 2
        """
    )
    with admin_context() as admin:
        rows = admin.session.execute(drift_sql).all()
        if not rows:
            print("column_value_count is consistent with column_value.")
            return
        for col_id, set_version_id, stored, actual in rows:
            print(
                f"drift: col_id={col_id} set_version_id={set_version_id} "
                f"stored={stored} actual={actual}"
            )
        print(f"{len(rows)} drifted row(s).")
        if fix:
            admin.session.execute(
                text(
                    """
                    DELETE FROM gerrydb.column_value_count c
                    USING gerrydb.geo_set_version sv
                    WHERE sv.set_version_id = c.set_version_id
                      AND sv.valid_to IS NULL
                    """
                )
            )
            admin.session.execute(
                text(
                    "INSERT INTO gerrydb.column_value_count "
                    "(col_id, set_version_id, count, value_hash_hi, value_hash_lo) "
                    + hash_rebuild_select(
                        "m.set_version_id IN ("
                        "SELECT set_version_id FROM gerrydb.geo_set_version "
                        "WHERE valid_to IS NULL)"
                    )
                )
            )
            admin.session.commit()
            print("Rebuilt counts and fingerprints for current set versions.")


if __name__ == "__main__":
    cli()  # pragma: no cover
