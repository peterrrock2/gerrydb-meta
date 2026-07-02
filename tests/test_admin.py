import csv
import logging
import re
from datetime import datetime
from uuid import UUID

import pytest
from click.testing import CliRunner

import gerrydb_meta.admin as admin_module
from gerrydb_meta.admin import *
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


def clear_users(session):
    # delete in reverse‐FK order
    session.query(UserGroupScope).delete()
    session.query(UserGroupMember).delete()
    session.query(UserGroup).delete()
    session.query(UserScope).delete()
    session.query(ApiKey).delete()
    session.query(Namespace).delete()
    session.query(ObjectMeta).delete()
    session.query(User).delete()
    session.commit()


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, db_schema, db):
    """
    1) Patch admin_module.Session to use our test schema.
    2) Wipe out ALL users / groups / keys / scopes / meta.
    3) Bootstrap a fresh admin via `init:user` CLI.
    Runs automatically before every test that uses pytest.
    """
    # tell the code to pick the TEST branch
    monkeypatch.setenv("GERRYDB_RUN_TESTS", "1")
    # patch the Session inside the admin module
    monkeypatch.setattr(admin_module, "Session", db_schema)

    clear_users(db)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init:user", "--user-email", "admin@example.com", "--name", "Admin"],
    )
    assert result.exit_code == 0, result.output
    assert "New user User(email=admin@example.com, name=Admin)" in result.output
    assert "New API key for new User(email=admin@example.com, name=Admin)" in result.output

    yield


def run(cmd: list[str], **env):
    runner = CliRunner(env=env)
    return runner.invoke(cli, cmd)


def test_init_user_and_duplicate(db):
    res2 = run(["init:user", "--user-email", "other@example.com", "--name", "Other"])
    assert res2.exit_code != 0
    assert isinstance(res2.exception, ValueError)
    assert "Cannot create the first user in the database (users already exist)." in str(
        res2.exception
    )

    user = db.query(User).filter_by(email="admin@example.com").one_or_none()
    assert user is not None

    key = db.query(ApiKey).filter_by(user_id=user.user_id).first()
    assert key is not None


def test_user_create_various_groups(db):

    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
        ]
    )
    # user:create should sys error out because missing email
    assert pub.exit_code == 2

    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
            "-c",
            "bad_admin@example.com",
        ]
    )
    assert pub.exit_code == 1
    assert "No user found with email bad_admin@example.com" in str(pub.exception)

    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
            "-c",
            "admin@example.com",
        ]
    )
    assert pub.exit_code == 0
    assert "New API key for new" in pub.output

    user = db.query(User).filter_by(email="user@example.com").one()
    user_groups = db.query(UserGroup).filter_by(name="public").one()
    user_group_members = (
        db.query(UserGroupMember)
        .filter_by(user_id=user.user_id, group_id=user_groups.group_id)
        .all()
    )
    assert len(user_group_members) == 1

    contrib = run(
        [
            "user:create",
            "--user-email",
            "contrib@example.com",
            "--name",
            "Contrib",
            "--group-perm",
            "contributor",
            "-c",
            "user@example.com",
        ]
    )
    assert contrib.exit_code == 1
    assert "User is not an admin." in str(contrib.exception)

    contrib = run(
        [
            "user:create",
            "--user-email",
            "contrib@example.com",
            "--name",
            "Contrib",
            "--group-perm",
            "contributor",
            "-c",
            "admin@example.com",
        ]
    )

    assert contrib.exit_code == 0
    assert "New API key for new" in contrib.output

    contrib_user = db.query(User).filter_by(email="contrib@example.com").one()
    contrib_groups = db.query(UserGroup).filter_by(name="contributor").one()
    contrib_group_members = (
        db.query(UserGroupMember)
        .filter_by(user_id=contrib_user.user_id, group_id=contrib_groups.group_id)
        .all()
    )
    assert len(contrib_group_members) == 1

    admin_2 = run(
        [
            "user:create",
            "--user-email",
            "admin2@example.com",
            "--name",
            "Admin2",
            "--group-perm",
            "admin",
            "-c",
            "admin@example.com",
        ]
    )
    assert admin_2.exit_code == 0
    assert "New API key for new" in admin_2.output

    admin_user = db.query(User).filter_by(email="admin2@example.com").one()
    admin_groups = db.query(UserGroup).filter_by(name="admin").one()
    admin_group_members = (
        db.query(UserGroupMember)
        .filter_by(user_id=admin_user.user_id, group_id=admin_groups.group_id)
        .all()
    )
    assert len(admin_group_members) == 1

    all_admins = list((db.query(UserGroupMember).filter_by(group_id=admin_groups.group_id).all()))
    assert len(all_admins) == 2

    admin_names = [u.user.name for u in all_admins]
    assert "Admin" in admin_names
    assert "Admin2" in admin_names


def test_check_admin(db):
    # check that the admin user is in the admin group
    admin_check = run(["user:check:admin", "--email", "admin@example.com"])
    assert admin_check.exit_code == 0
    assert "is an admin: True" in admin_check.output

    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
            "-c",
            "admin@example.com",
        ]
    )
    assert pub.exit_code == 0
    assert "New API key for new" in pub.output

    pub_check = run(["user:check:admin", "--email", "user@example.com"])
    assert pub_check.exit_code == 0
    assert "is an admin: False" in pub_check.output


def test_user_group_create(db):
    group = run(["usergroup:create", "--name", "test", "--description", "desc"])
    assert group.exit_code == 2  # Forgot creator email

    group = run(
        [
            "usergroup:create",
            "--name",
            "test",
            "--description",
            "desc",
            "-c",
            "bad_admin@example.com",
        ]
    )
    assert group.exit_code == 1
    assert "No user found with email bad_admin@example.com" in str(group.exception)

    group = run(
        [
            "usergroup:create",
            "--name",
            "test",
            "--description",
            "desc",
            "-c",
            "admin@example.com",
        ]
    )
    assert group.exit_code == 0
    assert "New user group: UserGroup(name=test)" in group.output

    group = run(
        [
            "usergroup:create",
            "--name",
            "test",
            "--description",
            "desc",
            "-c",
            "admin@example.com",
        ]
    )
    assert group.exit_code == 1
    assert "User group 'test' already exists." in str(group.exception)


def test_user_grant(db):
    admin = db.query(User).filter_by(email="admin@example.com").one()
    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
            "-c",
            "admin@example.com",
        ]
    )
    assert pub.exit_code == 0
    assert "New API key for new" in pub.output

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "meta:read",
            "-c",
            "admin@example.com",
        ]
    )
    assert grant.exit_code == 1
    assert "Must specify exactly one of namespace or namespace group." in str(grant.exception)

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "meta:read",
            "-c",
            "admin@example.com",
        ]
    )
    assert grant.exit_code == 1
    assert "Must specify exactly one of namespace or namespace group." in str(grant.exception)

    grant = run(
        [
            "user:grant",
            "-u",
            "bad_user@example.com",
            "-s",
            "namespace:write",
            "-c",
            "admin@example.com",
            "-ng",
            "all",
        ]
    )
    assert grant.exit_code == 1
    assert "No user found with email bad_user@example.com" in str(grant.exception)

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "namespace:write",
            "-c",
            "bad_admin@example.com",
            "-ng",
            "all",
        ]
    )
    assert grant.exit_code == 1
    assert "No user found with email bad_admin@example.com" in str(grant.exception)

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "namespace:write",
            "-c",
            "admin@example.com",
            "-ns",
            "grant_ns",
            "-ng",
            "all",
        ]
    )
    assert grant.exit_code == 1
    assert "Must specify exactly one of namespace or namespace group." in str(grant.exception)

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "namespace:write",
            "-c",
            "admin@example.com",
            "-ns",
            "grant_ns",
        ]
    )
    assert grant.exit_code == 1
    assert "No namespace found with path grant_ns" in str(grant.exception)

    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000001"),
            notes="test",
            created_at=datetime.now(),
            created_by=admin.user_id,
        )
    )
    meta = db.query(ObjectMeta).filter_by(uuid="00000000-0000-0000-0000-000000000001").one()
    db.add(Namespace(path="grant_ns", description="a test ns", public=False, meta_id=meta.meta_id))
    db.commit()
    ns = db.query(Namespace).filter_by(path="grant_ns").one()

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "namespace:read",
            "-s",
            "namespace:write:derived",
            "-c",
            "admin@example.com",
            "-ns",
            "grant_ns",
        ]
    )
    assert grant.exit_code == 0

    user = db.query(User).filter_by(email="user@example.com").one()
    scopes = db.query(UserScope).filter_by(user_id=user.user_id, namespace_id=ns.namespace_id).all()

    assert len(scopes) == 2
    assert str(
        UserScope(
            user_id=user.user_id,
            scope=ScopeType.NAMESPACE_READ,
            namespace_id=ns.namespace_id,
            meta_id=meta.meta_id,
        )
    ) in [str(s) for s in scopes]

    assert str(
        UserScope(
            user_id=user.user_id,
            scope=ScopeType.NAMESPACE_WRITE_DERIVED,
            namespace_id=ns.namespace_id,
            meta_id=meta.meta_id,
        )
    ) in [str(s) for s in scopes]

    grant = run(
        [
            "user:grant",
            "-u",
            "user@example.com",
            "-s",
            "namespace:write",
            "-c",
            "admin@example.com",
            "-ng",
            "private",
        ]
    )
    assert grant.exit_code == 0

    scopes = db.query(UserScope).filter_by(user_id=user.user_id, namespace_group="private").all()
    assert len(scopes) == 1
    assert str(
        UserScope(
            user_id=user.user_id,
            scope=ScopeType.NAMESPACE_WRITE,
            namespace_group=NamespaceGroup.PRIVATE,
            meta_id=meta.meta_id,
        )
    ) in [str(s) for s in scopes]


def test_user_add_group(db, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    admin = db.query(User).filter_by(email="admin@example.com").one()

    pub = run(
        [
            "user:create",
            "--user-email",
            "user@example.com",
            "--name",
            "User",
            "-c",
            "admin@example.com",
        ]
    )
    assert pub.exit_code == 0
    assert "New API key for new" in pub.output

    added = run(
        [
            "user:add:group",
            "-u",
            "user@example.com",
            "-g",
            "admin",
            "-c",
            "admin@example.com",
        ]
    )
    assert added.exit_code == 0
    assert "Added User(email=user@example.com, name=User) to UserGroup(name=admin)" in caplog.text

    added = run(
        [
            "user:add:group",
            "-u",
            "user@example.com",
            "-g",
            "admin",
            "-c",
            "admin@example.com",
        ]
    )
    assert added.exit_code == 0
    assert (
        "User User(email=user@example.com, name=User) is already in group UserGroup(name=admin)"
        in caplog.text
    )

    user = db.query(User).filter_by(email="user@example.com").one()

    groups = db.query(UserGroup).filter_by(name="admin").one()
    group_members = db.query(UserGroupMember).filter_by(group_id=groups.group_id).all()
    assert len(group_members) == 2
    assert user in [m.user for m in group_members]
    assert admin in [m.user for m in group_members]


def test_usergroup_grant(db):
    grp_create = run(
        [
            "usergroup:create",
            "--name",
            "team",
            "--description",
            "Team X",
            "-c",
            "admin@example.com",
        ]
    )
    assert grp_create.exit_code == 0

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "all",
            "-c",
            "nope@x.com",
            "-ng",
            "all",
        ]
    )
    assert r.exit_code != 0
    assert "No user found with email nope@x.com" in str(r.exception)

    r = run(
        [
            "usergroup:grant",
            "-g",
            "nopeGroup",
            "-s",
            "all",
            "-c",
            "admin@example.com",
            "-ng",
            "all",
        ]
    )
    assert r.exit_code != 0
    assert "No user group found with name nopeGroup" in str(r.exception)

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "all",
            "-c",
            "admin@example.com",
        ]
    )
    assert r.exit_code != 0
    assert "Must specify exactly one of namespace or namespace group." in str(r.exception)

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "all",
            "-c",
            "admin@example.com",
            "-ns",
            "doesntmatter",
            "-ng",
            "all",
        ]
    )
    assert r.exit_code != 0
    assert "Must specify exactly one of namespace or namespace group." in str(r.exception)

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "all",
            "-c",
            "admin@example.com",
            "-ns",
            "missing_ns",
        ]
    )
    assert r.exit_code != 0
    assert "No namespace found with path missing_ns" in str(r.exception)

    admin = (
        db.query(ObjectMeta).filter_by(created_by=db.query(ObjectMeta).first().created_by).first()
    )
    db.add(
        ObjectMeta(
            uuid=UUID("00000000-0000-0000-0000-000000000002"),
            notes="ns test",
            created_at=datetime.now(),
            created_by=admin.created_by,
        )
    )
    db.flush()
    meta = db.query(ObjectMeta).filter_by(uuid=UUID("00000000-0000-0000-0000-000000000002")).one()
    db.add(
        Namespace(
            path="the_ns",
            description="test ns",
            public=False,
            meta_id=meta.meta_id,
        )
    )
    db.commit()
    ns = db.query(Namespace).filter_by(path="the_ns").one()

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "namespace:read",
            "-s",
            "namespace:write:derived",
            "-c",
            "admin@example.com",
            "-ns",
            "the_ns",
        ]
    )
    assert r.exit_code == 0

    scopes = (
        db.query(UserGroupScope)
        .filter_by(
            group_id=db.query(UserGroup).filter_by(name="team").one().group_id,
            namespace_id=ns.namespace_id,
        )
        .all()
    )
    assert len(scopes) == 2
    names = {s.scope for s in scopes}
    assert {ScopeType.NAMESPACE_READ, ScopeType.NAMESPACE_WRITE_DERIVED} == names

    r = run(
        [
            "usergroup:grant",
            "-g",
            "team",
            "-s",
            "meta:write",
            "-c",
            "admin@example.com",
            "-ng",
            "public",
        ]
    )
    assert r.exit_code == 0

    scopes_ng = (
        db.query(UserGroupScope)
        .filter_by(
            group_id=db.query(UserGroup).filter_by(name="team").one().group_id,
            namespace_group=NamespaceGroup.PUBLIC,
        )
        .all()
    )
    assert len(scopes_ng) == 1
    assert scopes_ng[0].scope == ScopeType.META_WRITE


def test_bulk_user_create_success(tmp_path, db):
    roster = tmp_path / "roster.csv"
    with open(roster, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["name", "email", "group_perm"])
        writer.writeheader()
        writer.writerow({"name": "Alice", "email": "alice@example.com", "group_perm": "public"})
        writer.writerow({"name": "Bob", "email": "bob@example.com", "group_perm": "contributor"})

    keys_out = tmp_path / "keys.csv"

    result = run(
        [
            "user:create:bulk",
            "--roster",
            str(roster),
            "--keys",
            str(keys_out),
            "-c",
            "admin@example.com",
        ]
    )
    assert result.exit_code == 0, result.output

    lines = keys_out.read_text().splitlines()
    assert lines[0] == "name,email,key"
    assert len(lines) == 3

    emails = [line.split(",")[1] for line in lines[1:]]
    assert set(emails) == {"alice@example.com", "bob@example.com"}

    for email in emails:
        user = db.query(User).filter_by(email=email).one()
        assert db.query(ApiKey).filter_by(user_id=user.user_id).first()


def test_bulk_user_create_no_creator(tmp_path):
    roster = tmp_path / "roster.csv"
    with open(roster, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["name", "email", "group_perm"])
        writer.writeheader()
        writer.writerow({"name": "Carol", "email": "carol@example.com", "group_perm": "public"})

    keys_out = tmp_path / "keys.csv"

    result = run(
        [
            "user:create:bulk",
            "--roster",
            str(roster),
            "--keys",
            str(keys_out),
            "-c",
            "nonexistent@example.com",
        ]
    )
    assert result.exit_code != 0
    assert "No user found with email nonexistent@example.com" in str(result.exception)


def test_bulk_user_create_missing_roster(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    keys_out = tmp_path / "keys.csv"

    result = run(
        [
            "user:create:bulk",
            "--roster",
            str(missing),
            "--keys",
            str(keys_out),
            "-c",
            "admin@example.com",
        ]
    )
    assert result.exit_code != 0
    assert "No such file or directory" in str(result.exception)


def test_key_create_and_deactivate_and_key_deactivate(db):
    user_email = "testuser@example.com"
    res = run(
        [
            "user:create",
            "-u",
            user_email,
            "--name",
            "TestUser",
            "--group-perm",
            "public",
            "-c",
            "admin@example.com",
        ]
    )
    assert res.exit_code == 0
    raw1 = res.output.strip().split()[-1]
    assert len(raw1) == 64

    res2 = run(["key:create", "--email", user_email])
    assert res2.exit_code == 0
    raw2 = res2.output.strip().split()[-1]
    assert raw2 != raw1

    user = db.query(User).filter_by(email=user_email).one()
    keys = db.query(ApiKey).filter_by(user_id=user.user_id).all()
    assert len(keys) == 2
    assert all(k.active for k in keys)

    res3 = run(["user:deactivate", "--email", user_email])
    assert res3.exit_code == 0
    keys_after = db.query(ApiKey).filter_by(user_id=user.user_id).all()
    db.commit()
    assert all([not k.active for k in keys_after])

    res4 = run(["key:create", "--email", user_email])
    raw3 = res4.output.strip().split()[-1]
    keys2 = db.query(ApiKey).filter_by(user_id=user.user_id).all()
    assert any(k.active for k in keys2)

    res5 = run(["key:deactivate", "--key", raw3])
    assert res5.exit_code == 0
    db.commit()

    k_obj = db.query(ApiKey).filter_by(key_hash=sha512(raw3.encode()).digest()).one()
    assert not k_obj.active


def test_key_create_nonexistent_user():
    res = run(["key:create", "--email", "nope@example.com"])
    assert res.exit_code != 0
    assert "No user found with email nope@example.com" in str(res.exception)


def test_user_deactivate_nonexistent_user():
    res = run(["user:deactivate", "--email", "nope@example.com"])
    assert res.exit_code != 0
    assert "No user found with email nope@example.com" in str(res.exception)


def test_key_deactivate_nonexistent_key():
    bad = "a" * 64
    res = run(["key:deactivate", "--key", bad])
    assert res.exit_code != 0
    assert "No API key found with hash of specified raw key." in str(res.exception)


def test_user_find_by_id(db):
    admin_user = db.query(User).filter_by(email="admin@example.com").one()
    admin = GerryAdmin(session=db)
    user = admin.user_find_by_id(admin_user.user_id)
    assert user.email == "admin@example.com"
    assert user.name == "Admin"

    with pytest.raises(ValueError, match=re.escape(f"No user found with id {9999999}.")):
        admin.user_find_by_id(9999999)


def test_create_test_key_prompt(db, monkeypatch):
    admin_user = db.query(User).filter_by(email="admin@example.com").one()
    admin = GerryAdmin(session=db)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(ValueError, match="User aborted API key creation."):
        admin.create_test_key(admin_user, force=False)


def test_create_test_key(db, monkeypatch):
    admin_user = db.query(User).filter_by(email="admin@example.com").one()
    admin = GerryAdmin(session=db)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    admin.create_test_key(admin_user, force=True)
    db.commit()
    raw_key_hash = sha512(
        "7w7uv9mi575n2dhlmg3wqba2imv1aqdys387tpbtpermujy1tuyqbxetygx8u3fr".encode("utf-8")
    ).digest()
    assert raw_key_hash in [k.key_hash for k in admin_user.api_keys]
