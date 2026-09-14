"""Safety tests for the immutable migration runner on disposable PostgreSQL 16 schemas."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pg8000.dbapi
import psycopg
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

DATABASE_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATABASE_DIRECTORY))

from migration_runner import (  # noqa: E402
    MigrationError,
    _validate_schema_name,
    apply_migrations,
    load_manifest,
    run_test_migrations,
    split_migration_statements,
)

ADMIN_DATABASE_URL = os.environ["DATABASE_URL"]
BASELINE_MANIFEST = DATABASE_DIRECTORY / "migrations" / "manifest.json"
TEST_PASSWORD = "ci-only-migration-password"  # noqa: S105


@dataclass(frozen=True)
class DatabaseFixture:
    database_name: str
    migration_role: str
    runtime_role: str
    app_schema: str
    migration_schema: str
    migration_url: str
    runtime_url: str


def _role_url(role: str) -> str:
    parameters = conninfo_to_dict(ADMIN_DATABASE_URL)
    parameters.update(user=role, password=TEST_PASSWORD)
    return make_conninfo(**parameters)


@contextmanager
def database_fixture() -> Iterator[DatabaseFixture]:
    suffix = uuid.uuid4().hex[:10]
    migration_role = f"eemig_{suffix}"
    runtime_role = f"eert_{suffix}"
    app_schema = f"eeapp_{suffix}"
    migration_schema = f"eectl_{suffix}"

    try:
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
            database_name = admin.execute("SELECT current_database()").fetchone()[0]
            for role in (migration_role, runtime_role):
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(TEST_PASSWORD)
                    )
                )
            admin.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                    sql.Identifier(app_schema), sql.Identifier(migration_role)
                )
            )
            admin.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                    sql.Identifier(migration_schema), sql.Identifier(migration_role)
                )
            )
            admin.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                    sql.Identifier(app_schema)
                )
            )
            admin.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                    sql.Identifier(migration_schema)
                )
            )
        fixture = DatabaseFixture(
            database_name=database_name,
            migration_role=migration_role,
            runtime_role=runtime_role,
            app_schema=app_schema,
            migration_schema=migration_schema,
            migration_url=_role_url(migration_role),
            runtime_url=_role_url(runtime_role),
        )
        yield fixture
    finally:
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(app_schema)
                )
            )
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(migration_schema)
                )
            )
            for role in (runtime_role, migration_role):
                if admin.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (role,)
                ).fetchone()[0]:
                    admin.execute(
                        sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role))
                    )
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _run(fixture: DatabaseFixture, manifest: Path = BASELINE_MANIFEST) -> list[str]:
    return run_test_migrations(
        fixture.migration_url,
        manifest,
        fixture.app_schema,
        fixture.migration_schema,
        expected_database=fixture.database_name,
        expected_migration_role=fixture.migration_role,
        expected_runtime_role=fixture.runtime_role,
        lock_timeout_seconds=5,
        statement_timeout_seconds=30,
        source_revision="ci-test",
    )


def _run_pg8000(
    fixture: DatabaseFixture, manifest: Path = BASELINE_MANIFEST
) -> list[str]:
    parameters = conninfo_to_dict(ADMIN_DATABASE_URL)
    connection = pg8000.dbapi.connect(
        user=fixture.migration_role,
        password=TEST_PASSWORD,
        host=parameters.get("host", "127.0.0.1"),
        port=int(parameters.get("port", "5432")),
        database=parameters["dbname"],
    )
    try:
        return apply_migrations(
            connection,
            load_manifest(manifest),
            fixture.app_schema,
            fixture.migration_schema,
            expected_database=fixture.database_name,
            expected_migration_role=fixture.migration_role,
            expected_runtime_role=fixture.runtime_role,
            lock_timeout_seconds=5,
            statement_timeout_seconds=30,
            source_revision="ci-pg8000-test",
        )
    finally:
        connection.close()


def _temporary_manifest(directory: Path, migration_id: str, script: str) -> Path:
    migration_file = directory / f"{migration_id}__test.sql"
    migration_file.write_text(script, encoding="utf-8", newline="\n")
    checksum = hashlib.sha256(migration_file.read_bytes()).hexdigest()
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "migrations": [
                    {
                        "id": migration_id,
                        "name": "test",
                        "file": migration_file.name,
                        "sha256": checksum,
                        "requires_empty": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def _expect_migration_error(action, contains: str) -> None:
    try:
        action()
    except MigrationError as exc:
        assert contains in str(exc), exc
    else:
        raise AssertionError("Expected the migration to be rejected.")


def test_empty_apply_and_rerun() -> None:
    with database_fixture() as fixture:
        assert _run(fixture) == ["V0001", "V0002", "V0003"]
        assert _run(fixture) == []
        with psycopg.connect(fixture.migration_url) as connection:
            table_count = connection.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = %s",
                (fixture.app_schema,),
            ).fetchone()[0]
            ledger = connection.execute(
                sql.SQL(
                    "SELECT migration_id, checksum, source_revision, runner_version "
                    "FROM {}.schema_migrations ORDER BY migration_id"
                ).format(sql.Identifier(fixture.migration_schema))
            ).fetchall()
        entries = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))["migrations"]
        assert table_count == 18
        assert ledger == [(entry["id"], entry["sha256"], "ci-test", "1.0.0") for entry in entries]


def test_baseline_upgrade_preserves_existing_accounts_and_sessions() -> None:
    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        directory = Path(temp_directory)
        current = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
        baseline = current["migrations"][0]
        (directory / baseline["file"]).write_bytes(
            (BASELINE_MANIFEST.parent / baseline["file"]).read_bytes()
        )
        prefix = directory / "manifest.json"
        prefix.write_text(json.dumps({"manifest_version": 1, "migrations": [baseline]}), encoding="utf-8")
        assert _run(fixture, prefix) == ["V0001"]
        with psycopg.connect(fixture.runtime_url) as connection:
            owner = connection.execute(
                sql.SQL("INSERT INTO {}.app_users (public_id, role, status, username) "
                        "VALUES ('AMI-UPGRADE-SYNTHETIC','contributor','active','synthetic-upgrade') "
                        "RETURNING id")
                .format(sql.Identifier(fixture.app_schema))
            ).fetchone()[0]
            connection.execute(
                sql.SQL("INSERT INTO {}.staff_credentials (user_id, password_hash) VALUES (%s,%s)")
                .format(sql.Identifier(fixture.app_schema)),
                (owner, "non-working-upgrade-hash-fixture"),
            )
            session = connection.execute(
                sql.SQL("INSERT INTO {}.auth_sessions "
                        "(user_id, token_family_id, refresh_token_hash, installation_id, "
                        "platform, expires_at) "
                        "VALUES (%s,%s,'non-working-upgrade-refresh-hash',%s,'android', "
                        "now()+interval '1 day') "
                        "RETURNING id").format(sql.Identifier(fixture.app_schema)),
                (owner, uuid.uuid4(), uuid.uuid4()),
            ).fetchone()[0]
        assert _run(fixture) == ["V0002", "V0003"]
        assert _run(fixture) == []
        with psycopg.connect(fixture.runtime_url) as connection:
            credential = connection.execute(
                sql.SQL("SELECT password_hash, second_factor_enabled, mfa_secret_ciphertext, "
                        "last_accepted_totp_step, credential_version FROM {}.staff_credentials "
                        "WHERE user_id=%s")
                .format(sql.Identifier(fixture.app_schema)), (owner,),
            ).fetchone()
            assert credential[:4] == ("non-working-upgrade-hash-fixture", False, None, None)
            assert credential[4] is not None
            saved = connection.execute(
                sql.SQL("SELECT user_id, revoked_at, staff_credential_version "
                        "FROM {}.auth_sessions WHERE id=%s")
                .format(sql.Identifier(fixture.app_schema)), (session,),
            ).fetchone()
            assert saved == (owner, None, None)


def test_v0002_upgrade_revokes_sessions_with_runtime_permissions() -> None:
    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        directory = Path(temp_directory)
        entries = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))["migrations"][:2]
        for entry in entries:
            (directory / entry["file"]).write_bytes(
                (BASELINE_MANIFEST.parent / entry["file"]).read_bytes()
            )
        prefix = directory / "manifest.json"
        prefix.write_text(json.dumps({"manifest_version": 1, "migrations": entries}), encoding="utf-8")
        assert _run(fixture, prefix) == ["V0001", "V0002"]
        with psycopg.connect(fixture.runtime_url) as connection:
            owner = connection.execute(
                sql.SQL("INSERT INTO {}.app_users (public_id,role,status,username) "
                        "VALUES ('AMI-ROLE-UPGRADE','contributor','active','synthetic-role-upgrade') "
                        "RETURNING id").format(sql.Identifier(fixture.app_schema))
            ).fetchone()[0]
            connection.execute(
                sql.SQL("INSERT INTO {}.staff_credentials (user_id,password_hash) "
                        "VALUES (%s,'non-working-upgrade-hash-fixture')")
                .format(sql.Identifier(fixture.app_schema)), (owner,),
            )
            connection.execute(
                sql.SQL("INSERT INTO {}.auth_sessions "
                        "(user_id,token_family_id,refresh_token_hash,installation_id,platform,expires_at) "
                        "VALUES (%s,%s,'non-working-role-upgrade-refresh',%s,'web',now()+interval '1 day')")
                .format(sql.Identifier(fixture.app_schema)), (owner, uuid.uuid4(), uuid.uuid4()),
            )
        assert _run(fixture) == ["V0003"]
        assert _run(fixture) == []
        with psycopg.connect(fixture.runtime_url) as connection:
            connection.execute(
                sql.SQL("UPDATE {}.app_users SET role='administrator' WHERE id=%s")
                .format(sql.Identifier(fixture.app_schema)), (owner,),
            )
            assert connection.execute(
                sql.SQL("SELECT bool_and(revoked_at IS NOT NULL) FROM {}.auth_sessions WHERE user_id=%s")
                .format(sql.Identifier(fixture.app_schema)), (owner,),
            ).fetchone()[0]


def test_ledger_checksum_mismatch_is_rejected() -> None:
    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(ADMIN_DATABASE_URL) as admin:
            admin.execute(
                sql.SQL("UPDATE {}.schema_migrations SET checksum = %s").format(
                    sql.Identifier(fixture.migration_schema)
                ),
                ("0" * 64,),
            )
        _expect_migration_error(lambda: _run(fixture), "checksum mismatch")


def test_file_checksum_mismatch_is_rejected_before_connection() -> None:
    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        directory = Path(temp_directory)
        manifest = _temporary_manifest(
            directory, "V9002", "CREATE TABLE approved (id integer);"
        )
        (directory / "V9002__test.sql").write_text(
            "CREATE TABLE changed_after_approval (id integer);",
            encoding="utf-8",
            newline="\n",
        )
        _expect_migration_error(lambda: _run(fixture, manifest), "approved checksum")


def test_unexpected_object_is_rejected() -> None:
    with database_fixture() as fixture:
        with psycopg.connect(fixture.migration_url) as connection:
            connection.execute(
                sql.SQL("CREATE TABLE {}.unexpected_object (id integer)").format(
                    sql.Identifier(fixture.app_schema)
                )
            )
        _expect_migration_error(
            lambda: _run(fixture), "requires empty application and control schemas"
        )
        with psycopg.connect(fixture.migration_url) as connection:
            assert (
                connection.execute(
                    "SELECT to_regclass(%s) IS NULL",
                    (f"{fixture.migration_schema}.schema_migrations",),
                ).fetchone()[0]
                is True
            )


def test_public_or_other_schema_objects_are_rejected() -> None:
    with database_fixture() as fixture:
        public_table = f"ee_unexpected_{uuid.uuid4().hex[:10]}"
        other_schema = f"eeother_{uuid.uuid4().hex[:10]}"
        try:
            with psycopg.connect(ADMIN_DATABASE_URL) as admin:
                admin.execute(
                    sql.SQL("CREATE TABLE public.{} (id integer)").format(
                        sql.Identifier(public_table)
                    )
                )
            _expect_migration_error(
                lambda: _run(fixture), "outside the approved schemas"
            )
        finally:
            with psycopg.connect(ADMIN_DATABASE_URL) as admin:
                admin.execute(
                    sql.SQL("DROP TABLE IF EXISTS public.{}").format(
                        sql.Identifier(public_table)
                    )
                )

        with psycopg.connect(ADMIN_DATABASE_URL) as admin:
            admin.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                    sql.Identifier(other_schema), sql.Identifier(fixture.migration_role)
                )
            )
            admin.execute(
                sql.SQL("CREATE TABLE {}.unexpected (id integer)").format(
                    sql.Identifier(other_schema)
                )
            )
        _expect_migration_error(lambda: _run(fixture), "outside the approved schemas")


def test_control_schema_object_and_fake_ledger_are_rejected() -> None:
    with database_fixture() as fixture:
        with psycopg.connect(fixture.migration_url) as connection:
            connection.execute(
                sql.SQL("CREATE TABLE {}.unexpected (id integer)").format(
                    sql.Identifier(fixture.migration_schema)
                )
            )
        _expect_migration_error(
            lambda: _run(fixture), "requires empty application and control schemas"
        )

    with database_fixture() as fixture:
        with psycopg.connect(fixture.migration_url) as connection:
            connection.execute(
                sql.SQL("CREATE TABLE {}.schema_migrations (id integer)").format(
                    sql.Identifier(fixture.migration_schema)
                )
            )
        _expect_migration_error(lambda: _run(fixture), "ledger structure")


def test_transaction_control_forms_are_rejected() -> None:
    forms = [
        "BEGIN; SELECT 1;",
        "COMMIT WORK;",
        "END TRANSACTION;",
        "ABORT WORK;",
        "ROLLBACK WORK;",
        "START TRANSACTION;",
        "PREPARE TRANSACTION 'x';",
        "SAVEPOINT x;",
        "RELEASE SAVEPOINT x;",
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;",
    ]
    for statement in forms:
        _expect_migration_error(
            lambda statement=statement: split_migration_statements(statement),
            "cannot control their own transaction",
        )


def test_system_schema_names_are_rejected() -> None:
    for schema_name in ("public", "information_schema", "pg_catalog", "pg_custom"):
        _expect_migration_error(
            lambda schema_name=schema_name: _validate_schema_name(
                schema_name, "Application schema"
            ),
            "non-system PostgreSQL identifier",
        )


def test_pg8000_apply_rerun_and_rollback() -> None:
    with database_fixture() as fixture:
        assert _run_pg8000(fixture) == ["V0001", "V0002", "V0003"]
        assert _run_pg8000(fixture) == []

    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        manifest = _temporary_manifest(
            Path(temp_directory),
            "V9003",
            "CREATE TABLE pg8000_rollback_probe (id integer); SELECT 1 / 0;",
        )
        try:
            _run_pg8000(fixture, manifest)
        except pg8000.dbapi.DatabaseError:
            pass
        else:
            raise AssertionError("The pg8000 rollback test unexpectedly succeeded.")
        with psycopg.connect(fixture.migration_url) as connection:
            assert connection.execute(
                "SELECT to_regclass(%s) IS NULL",
                (f"{fixture.app_schema}.pg8000_rollback_probe",),
            ).fetchone()[0]


def test_permission_and_owner_drift_are_rejected() -> None:
    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL("GRANT TRIGGER ON {}.app_users TO {}").format(
                    sql.Identifier(fixture.app_schema),
                    sql.Identifier(fixture.runtime_role),
                )
            )
        _expect_migration_error(lambda: _run(fixture), "access control has drifted")

    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(ADMIN_DATABASE_URL) as admin:
            admin.execute(
                sql.SQL("ALTER TABLE {}.app_users OWNER TO {}").format(
                    sql.Identifier(fixture.app_schema),
                    sql.Identifier(fixture.runtime_role),
                )
            )
        _expect_migration_error(lambda: _run(fixture), "ownership or access control")

    with database_fixture() as fixture:
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT TRUNCATE ON TABLES TO {}"
                ).format(
                    sql.Identifier(fixture.app_schema),
                    sql.Identifier(fixture.runtime_role),
                )
            )
        _expect_migration_error(lambda: _run(fixture), "ownership or access control")


def test_ledger_grant_drift_is_rejected() -> None:
    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL("GRANT SELECT ON {}.schema_migrations TO {}").format(
                    sql.Identifier(fixture.migration_schema),
                    sql.Identifier(fixture.runtime_role),
                )
            )
        _expect_migration_error(lambda: _run(fixture), "ledger structure")

    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL(
                    "CREATE RULE ignore_insert AS ON INSERT TO {}.schema_migrations "
                    "DO INSTEAD NOTHING"
                ).format(sql.Identifier(fixture.migration_schema))
            )
        _expect_migration_error(lambda: _run(fixture), "ledger structure")

    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL(
                    "ALTER TABLE {}.schema_migrations ENABLE ROW LEVEL SECURITY"
                ).format(sql.Identifier(fixture.migration_schema))
            )
            migration.execute(
                sql.SQL(
                    "CREATE POLICY ledger_policy ON {}.schema_migrations USING (true)"
                ).format(sql.Identifier(fixture.migration_schema))
            )
        _expect_migration_error(lambda: _run(fixture), "ledger structure")


def test_transitive_administrative_role_is_rejected() -> None:
    with database_fixture() as fixture:
        suffix = uuid.uuid4().hex[:10]
        intermediate_role = f"eemid_{suffix}"
        admin_role = f"eeadm_{suffix}"
        try:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN").format(
                        sql.Identifier(intermediate_role)
                    )
                )
                admin.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN CREATEDB").format(
                        sql.Identifier(admin_role)
                    )
                )
                admin.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(admin_role), sql.Identifier(intermediate_role)
                    )
                )
                admin.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(intermediate_role),
                        sql.Identifier(fixture.migration_role),
                    )
                )
            _expect_migration_error(
                lambda: _run(fixture), "must not have administrative privileges"
            )
        finally:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(intermediate_role),
                        sql.Identifier(fixture.migration_role),
                    )
                )
                admin.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(admin_role), sql.Identifier(intermediate_role)
                    )
                )
                admin.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(intermediate_role))
                )
                admin.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(admin_role))
                )


def test_runtime_and_migration_role_inheritance_is_rejected() -> None:
    with database_fixture() as fixture:
        try:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(fixture.migration_role),
                        sql.Identifier(fixture.runtime_role),
                    )
                )
            _expect_migration_error(
                lambda: _run(fixture), "must not inherit from each other"
            )
        finally:
            with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(fixture.migration_role),
                        sql.Identifier(fixture.runtime_role),
                    )
                )


def test_concurrent_runners_serialize() -> None:
    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        baseline_sql = (
            DATABASE_DIRECTORY / "migrations" / "V0001__engagement_baseline.sql"
        ).read_text(encoding="utf-8")
        manifest = _temporary_manifest(
            Path(temp_directory),
            "V9000",
            f"SELECT pg_sleep(0.5);\n{baseline_sql}",
        )
        results: list[list[str]] = []
        failures: list[BaseException] = []

        def worker() -> None:
            try:
                results.append(_run(fixture, manifest))
            except (MigrationError, psycopg.Error) as exc:  # pragma: no cover
                failures.append(exc)

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)
        assert failures == [], [repr(failure) for failure in failures]
        assert sorted(results, key=len) == [[], ["V9000"]]


def test_failed_sql_rolls_back_everything() -> None:
    with database_fixture() as fixture, tempfile.TemporaryDirectory() as temp_directory:
        manifest = _temporary_manifest(
            Path(temp_directory),
            "V9001",
            "CREATE TABLE rollback_probe (id integer); SELECT 1 / 0;",
        )
        try:
            _run(fixture, manifest)
        except errors.DivisionByZero:
            pass
        else:
            raise AssertionError(
                "The injected migration failure unexpectedly succeeded."
            )
        with psycopg.connect(fixture.migration_url) as connection:
            assert (
                connection.execute(
                    "SELECT to_regclass(%s) IS NULL",
                    (f"{fixture.app_schema}.rollback_probe",),
                ).fetchone()[0]
                is True
            )
            assert (
                connection.execute(
                    "SELECT to_regclass(%s) IS NULL",
                    (f"{fixture.migration_schema}.schema_migrations",),
                ).fetchone()[0]
                is True
            )


def test_runtime_role_has_dml_but_not_ddl_or_ledger_access() -> None:
    with database_fixture() as fixture:
        _run(fixture)
        with psycopg.connect(fixture.migration_url) as migration:
            migration.execute(
                sql.SQL(
                    "CREATE TABLE {}.future_table (id integer PRIMARY KEY, value text)"
                ).format(sql.Identifier(fixture.app_schema))
            )
        with psycopg.connect(ADMIN_DATABASE_URL) as admin:
            role_flags = admin.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = %s",
                (fixture.migration_role,),
            ).fetchone()
            runtime_flags = admin.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = %s",
                (fixture.runtime_role,),
            ).fetchone()
        assert role_flags == (False, False, False)
        assert runtime_flags == (False, False, False)

        with psycopg.connect(fixture.runtime_url) as runtime:
            runtime.execute(
                "SELECT set_config('search_path', %s, false)", (fixture.app_schema,)
            )
            runtime.execute(
                "INSERT INTO app_users (public_id, role, username) "
                "VALUES ('CI-MEMBER-1', 'member', 'ci-member')"
            )
            runtime.execute(
                "UPDATE app_users SET status = 'active' WHERE public_id = 'CI-MEMBER-1'"
            )
            assert (
                runtime.execute(
                    "SELECT status::text FROM app_users WHERE public_id = 'CI-MEMBER-1'"
                ).fetchone()[0]
                == "active"
            )
            runtime.execute("DELETE FROM app_users WHERE public_id = 'CI-MEMBER-1'")
            runtime.execute(
                "INSERT INTO future_table (id, value) VALUES (1, 'created later')"
            )
            runtime.execute("UPDATE future_table SET value = 'updated' WHERE id = 1")
            assert (
                runtime.execute(
                    "SELECT value FROM future_table WHERE id = 1"
                ).fetchone()[0]
                == "updated"
            )
            runtime.execute("DELETE FROM future_table WHERE id = 1")
            runtime.execute(
                "INSERT INTO audit_events (action, entity_type, trace_id) "
                "VALUES ('ci.test', 'test', 'ci-trace')"
            )
            assert (
                runtime.execute(
                    "SELECT count(*) FROM audit_events WHERE trace_id = 'ci-trace'"
                ).fetchone()[0]
                == 1
            )

        forbidden_statements = [
            sql.SQL("CREATE TABLE {}.forbidden (id integer)").format(
                sql.Identifier(fixture.app_schema)
            ),
            sql.SQL("ALTER TABLE {}.app_users ADD COLUMN forbidden integer").format(
                sql.Identifier(fixture.app_schema)
            ),
            sql.SQL("DROP TABLE {}.app_users").format(
                sql.Identifier(fixture.app_schema)
            ),
            sql.SQL("SELECT * FROM {}.schema_migrations").format(
                sql.Identifier(fixture.migration_schema)
            ),
            sql.SQL(
                "INSERT INTO {}.schema_migrations (migration_id) VALUES ('V9999')"
            ).format(sql.Identifier(fixture.migration_schema)),
            sql.SQL("UPDATE {}.schema_migrations SET checksum = checksum").format(
                sql.Identifier(fixture.migration_schema)
            ),
            sql.SQL("DELETE FROM {}.schema_migrations").format(
                sql.Identifier(fixture.migration_schema)
            ),
            sql.SQL("DELETE FROM {}.audit_events").format(
                sql.Identifier(fixture.app_schema)
            ),
        ]
        for statement in forbidden_statements:
            try:
                with psycopg.connect(fixture.runtime_url) as runtime:
                    runtime.execute(statement)
            except errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError(
                    f"Runtime role unexpectedly executed: {statement!s}"
                )


def main() -> None:
    tests = [
        test_empty_apply_and_rerun,
        test_baseline_upgrade_preserves_existing_accounts_and_sessions,
        test_v0002_upgrade_revokes_sessions_with_runtime_permissions,
        test_ledger_checksum_mismatch_is_rejected,
        test_file_checksum_mismatch_is_rejected_before_connection,
        test_unexpected_object_is_rejected,
        test_public_or_other_schema_objects_are_rejected,
        test_control_schema_object_and_fake_ledger_are_rejected,
        test_transaction_control_forms_are_rejected,
        test_system_schema_names_are_rejected,
        test_pg8000_apply_rerun_and_rollback,
        test_permission_and_owner_drift_are_rejected,
        test_ledger_grant_drift_is_rejected,
        test_transitive_administrative_role_is_rejected,
        test_runtime_and_migration_role_inheritance_is_rejected,
        test_concurrent_runners_serialize,
        test_failed_sql_rolls_back_everything,
        test_runtime_role_has_dml_but_not_ddl_or_ledger_access,
    ]
    for test in tests:
        test()
    print(f"PostgreSQL 16 migration safety tests passed: {len(tests)} cases.")


if __name__ == "__main__":
    main()
