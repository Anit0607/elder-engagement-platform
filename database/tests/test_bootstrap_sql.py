"""PostgreSQL 16 behavior checks for the one-time schema bootstrap template."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ADMIN_DATABASE_URL = os.environ["DATABASE_URL"]
TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "bootstrap"
    / "V0001__establish_schema_ownership.sql.template"
)


@dataclass(frozen=True)
class BootstrapFixture:
    database_name: str
    operator: str
    migration_role: str
    runtime_role: str
    app_schema: str
    migration_schema: str


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return value.replace("'", "''")


def _render(fixture: BootstrapFixture) -> str:
    rendered = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__ADVISORY_LOCK_LITERAL__": _literal(
            f"elder-engagement:{fixture.database_name}:{fixture.app_schema}"
        ),
        "__DATABASE_LITERAL__": _literal(fixture.database_name),
        "__APPLICATION_SCHEMA_LITERAL__": _literal(fixture.app_schema),
        "__MIGRATION_SCHEMA_LITERAL__": _literal(fixture.migration_schema),
        "__MIGRATION_ROLE_LITERAL__": _literal(fixture.migration_role),
        "__RUNTIME_ROLE_LITERAL__": _literal(fixture.runtime_role),
        "__OPERATOR_LITERAL__": _literal(fixture.operator),
        "__APPLICATION_SCHEMA_IDENTIFIER__": _identifier(fixture.app_schema),
        "__MIGRATION_SCHEMA_IDENTIFIER__": _identifier(fixture.migration_schema),
        "__MIGRATION_ROLE_IDENTIFIER__": _identifier(fixture.migration_role),
        "__RUNTIME_ROLE_IDENTIFIER__": _identifier(fixture.runtime_role),
        "__OPERATOR_IDENTIFIER__": _identifier(fixture.operator),
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    assert re.search(r"__[A-Z0-9_]+__", rendered) is None
    return rendered


@contextmanager
def bootstrap_fixture(
    *, unsafe_migration_role: bool = False, grant_migration_membership: bool = True
) -> Iterator[BootstrapFixture]:
    suffix = uuid.uuid4().hex[:10]
    migration_role = f"eebm_{suffix}"
    runtime_role = f"eebr_{suffix}"
    operator = f"eebo_{suffix}"
    app_schema = f"eeba_{suffix}"
    migration_schema = f"eebc_{suffix}"

    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
        database_name = admin.execute("SELECT current_database()").fetchone()[0]
        fixture = BootstrapFixture(
            database_name=str(database_name),
            operator=operator,
            migration_role=migration_role,
            runtime_role=runtime_role,
            app_schema=app_schema,
            migration_schema=migration_schema,
        )
        admin.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN {}").format(
                sql.Identifier(migration_role),
                sql.SQL("CREATEDB") if unsafe_migration_role else sql.SQL("NOCREATEDB"),
            )
        )
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(runtime_role)))
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(operator))
        )
        admin.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                sql.Identifier(database_name), sql.Identifier(operator)
            )
        )
        if grant_migration_membership:
            admin.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(migration_role), sql.Identifier(operator)
                )
            )

    try:
        yield fixture
    finally:
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(app_schema))
            )
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(migration_schema)
                )
            )
            admin.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(migration_role), sql.Identifier(fixture.operator)
                )
            )
            admin.execute(
                sql.SQL("REVOKE CREATE ON DATABASE {} FROM {}").format(
                    sql.Identifier(fixture.database_name), sql.Identifier(fixture.operator)
                )
            )
            for role in (operator, runtime_role, migration_role):
                admin.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _execute(fixture: BootstrapFixture, script: str) -> None:
    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as operator:
        try:
            operator.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(
                    sql.Identifier(fixture.operator)
                )
            )
            operator.execute(script, prepare=False)
        except Exception:
            operator.execute("ROLLBACK")
            raise


def _schema_exists(name: str) -> bool:
    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
        return bool(admin.execute("SELECT to_regnamespace(%s) IS NOT NULL", (name,)).fetchone()[0])


def test_bootstrap_creates_empty_schemas_with_exact_permissions() -> None:
    with bootstrap_fixture() as fixture:
        _execute(fixture, _render(fixture))
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
            rows = admin.execute(
                """
                SELECT namespace.nspname, owner.rolname,
                       has_schema_privilege(%s, namespace.nspname, 'USAGE'),
                       has_schema_privilege(%s, namespace.nspname, 'CREATE')
                  FROM pg_namespace AS namespace
                  JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
                 WHERE namespace.nspname IN (%s, %s)
                 ORDER BY namespace.nspname
                """,
                (
                    fixture.runtime_role,
                    fixture.runtime_role,
                    fixture.app_schema,
                    fixture.migration_schema,
                ),
            ).fetchall()
            assert rows == [
                (fixture.app_schema, fixture.migration_role, True, False),
                (fixture.migration_schema, fixture.migration_role, False, False),
            ]
            membership = admin.execute(
                """
                SELECT count(*)
                  FROM pg_auth_members AS membership
                  JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
                  JOIN pg_roles AS member_role ON member_role.oid = membership.member
                 WHERE granted_role.rolname = %s AND member_role.rolname = %s
                """,
                (fixture.migration_role, fixture.operator),
            ).fetchone()[0]
            assert membership == 1


def test_bootstrap_refuses_an_accidental_second_run() -> None:
    with bootstrap_fixture() as fixture:
        rendered = _render(fixture)
        _execute(fixture, rendered)
        with pytest.raises(psycopg.errors.RaiseException, match="already exists"):
            _execute(fixture, rendered)
        assert _schema_exists(fixture.app_schema)
        assert _schema_exists(fixture.migration_schema)


def test_bootstrap_refuses_unexpected_existing_objects() -> None:
    with bootstrap_fixture() as fixture:
        object_name = f"eebx_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE TABLE public.{} (id integer)").format(sql.Identifier(object_name)))
        try:
            with pytest.raises(psycopg.errors.RaiseException, match="unexpected objects"):
                _execute(fixture, _render(fixture))
            assert not _schema_exists(fixture.app_schema)
            assert not _schema_exists(fixture.migration_schema)
        finally:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP TABLE public.{}").format(sql.Identifier(object_name)))


def test_bootstrap_refuses_an_administrative_application_role() -> None:
    with bootstrap_fixture(unsafe_migration_role=True) as fixture:
        with pytest.raises(psycopg.errors.RaiseException, match="administrative privileges"):
            _execute(fixture, _render(fixture))
        assert not _schema_exists(fixture.app_schema)
        assert not _schema_exists(fixture.migration_schema)


def test_bootstrap_refuses_runtime_inheriting_migration_ownership() -> None:
    with bootstrap_fixture() as fixture:
        try:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(fixture.migration_role),
                        sql.Identifier(fixture.runtime_role),
                    )
                )
            with pytest.raises(psycopg.errors.RaiseException, match="must not inherit"):
                _execute(fixture, _render(fixture))
            assert not _schema_exists(fixture.app_schema)
            assert not _schema_exists(fixture.migration_schema)
        finally:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(fixture.migration_role),
                        sql.Identifier(fixture.runtime_role),
                    )
                )


def test_bootstrap_refuses_operator_without_owner_assignment_membership() -> None:
    with bootstrap_fixture(grant_migration_membership=False) as fixture:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _execute(fixture, _render(fixture))
        assert not _schema_exists(fixture.app_schema)
        assert not _schema_exists(fixture.migration_schema)


def test_postcheck_failure_rolls_back_both_schemas() -> None:
    with bootstrap_fixture() as fixture:
        rendered = _render(fixture)
        runtime_grant = (
            f"GRANT USAGE ON SCHEMA {_identifier(fixture.app_schema)}\n"
            f"  TO {_identifier(fixture.runtime_role)};"
        )
        rendered = rendered.replace(runtime_grant, "-- runtime grant intentionally omitted by test")
        with pytest.raises(psycopg.errors.RaiseException, match="access control is unsafe"):
            _execute(fixture, rendered)
        assert not _schema_exists(fixture.app_schema)
        assert not _schema_exists(fixture.migration_schema)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
