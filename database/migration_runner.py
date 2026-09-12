"""Apply checksum-locked PostgreSQL migrations with keyless production authentication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import sqlparse
from sqlparse import tokens

MIGRATION_ID_PATTERN = re.compile(r"^V[0-9]{4}$")
MIGRATION_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
SCHEMA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ROLE_NAME_PATTERN = re.compile(r"^[a-z0-9_.@-]{1,63}$")
CHECKSUM_PATTERN = re.compile(r"^[a-f0-9]{64}$")
REVISION_PATTERN = re.compile(r"^[a-f0-9]{40}$")
DEFAULT_MANIFEST = Path(__file__).with_name("migrations") / "manifest.json"
RUNNER_VERSION = "1.0.0"


class MigrationError(RuntimeError):
    """A safe-to-display migration validation failure."""


@dataclass(frozen=True)
class Migration:
    migration_id: str
    name: str
    path: Path
    checksum: str
    requires_empty: bool
    statements: tuple[str, ...]


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _qualified(schema_name: str, object_name: str) -> str:
    return f"{_quote_identifier(schema_name)}.{_quote_identifier(object_name)}"


def _validate_schema_name(name: str, label: str) -> str:
    if (
        not SCHEMA_NAME_PATTERN.fullmatch(name)
        or name.startswith("pg_")
        or name in {"information_schema", "public"}
    ):
        raise MigrationError(
            f"{label} must be an approved lowercase non-system PostgreSQL identifier."
        )
    return name


def _validate_role_name(name: str, label: str) -> str:
    if not ROLE_NAME_PATTERN.fullmatch(name):
        raise MigrationError(f"{label} is not an approved PostgreSQL role name.")
    return name


def _significant_words(statement: str) -> list[str]:
    parsed = sqlparse.parse(statement)
    if len(parsed) != 1:
        raise MigrationError("A migration contains an ambiguous SQL statement.")
    return [
        token.value.upper()
        for token in parsed[0].flatten()
        if not token.is_whitespace and token.ttype not in tokens.Comment
    ]


def split_migration_statements(sql_text: str) -> tuple[str, ...]:
    """Split procedural PostgreSQL safely and reject transaction-control SQL."""
    statements = tuple(
        item.strip() for item in sqlparse.split(sql_text) if item.strip()
    )
    if not statements:
        raise MigrationError("A migration SQL file is empty.")
    for statement in statements:
        words = _significant_words(statement)
        if not words:
            continue
        first = words[0]
        second = words[1] if len(words) > 1 else ""
        if first in {"BEGIN", "COMMIT", "END", "ABORT", "ROLLBACK", "SAVEPOINT"} or (
            first,
            second,
        ) in {
            ("START", "TRANSACTION"),
            ("PREPARE", "TRANSACTION"),
            ("RELEASE", "SAVEPOINT"),
            ("SET", "TRANSACTION"),
        }:
            raise MigrationError(
                "Migration files cannot control their own transaction."
            )
    return statements


def load_manifest(manifest_path: Path) -> list[Migration]:
    """Load and verify every migration file before opening the database."""
    manifest_path = manifest_path.resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError("The migration manifest cannot be read.") from exc
    if payload.get("manifest_version") != 1 or not isinstance(
        payload.get("migrations"), list
    ):
        raise MigrationError("The migration manifest format is unsupported.")

    migrations: list[Migration] = []
    seen: set[str] = set()
    root = manifest_path.parent
    for entry in payload["migrations"]:
        if not isinstance(entry, dict):
            raise MigrationError("Every migration manifest entry must be an object.")
        migration_id = entry.get("id")
        name = entry.get("name")
        checksum = entry.get("sha256")
        relative_file = entry.get("file")
        requires_empty = entry.get("requires_empty", False)
        if not isinstance(migration_id, str) or not MIGRATION_ID_PATTERN.fullmatch(
            migration_id
        ):
            raise MigrationError("Every migration id must use the V0000 format.")
        if migration_id in seen:
            raise MigrationError(f"Duplicate migration id: {migration_id}.")
        if not isinstance(name, str) or not MIGRATION_NAME_PATTERN.fullmatch(name):
            raise MigrationError(f"Migration {migration_id} has an invalid name.")
        if not isinstance(checksum, str) or not CHECKSUM_PATTERN.fullmatch(checksum):
            raise MigrationError(
                f"Migration {migration_id} has an invalid SHA-256 checksum."
            )
        if relative_file != f"{migration_id}__{name}.sql":
            raise MigrationError(
                f"Migration {migration_id} has an unexpected filename."
            )
        if not isinstance(requires_empty, bool):
            raise MigrationError(
                f"Migration {migration_id} has an invalid requires_empty value."
            )

        migration_path = (root / relative_file).resolve()
        try:
            migration_path.relative_to(root)
        except ValueError as exc:
            raise MigrationError(
                f"Migration {migration_id} leaves the manifest directory."
            ) from exc
        try:
            contents = migration_path.read_bytes()
            sql_text = contents.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise MigrationError(
                f"Migration {migration_id} is not readable UTF-8 SQL."
            ) from exc
        if hashlib.sha256(contents).hexdigest() != checksum:
            raise MigrationError(
                f"Migration {migration_id} does not match its approved checksum."
            )
        migrations.append(
            Migration(
                migration_id=migration_id,
                name=name,
                path=migration_path,
                checksum=checksum,
                requires_empty=requires_empty,
                statements=split_migration_statements(sql_text),
            )
        )
        seen.add(migration_id)

    if not migrations or [item.migration_id for item in migrations] != sorted(seen):
        raise MigrationError("Migrations must be present and ordered by id.")
    return migrations


def _fetchone(
    cursor: Any, statement: str, parameters: tuple[Any, ...] = ()
) -> tuple[Any, ...]:
    cursor.execute(statement, parameters)
    row = cursor.fetchone()
    if row is None:
        raise MigrationError("A required PostgreSQL catalogue record is missing.")
    return tuple(row)


def _fetchall(
    cursor: Any, statement: str, parameters: tuple[Any, ...] = ()
) -> list[tuple[Any, ...]]:
    cursor.execute(statement, parameters)
    return [tuple(row) for row in cursor.fetchall()]


def _schema_exists(cursor: Any, schema_name: str) -> bool:
    return bool(
        _fetchone(cursor, "SELECT to_regnamespace(%s) IS NOT NULL", (schema_name,))[0]
    )


def _verify_role_safety(cursor: Any, role_name: str) -> None:
    row = _fetchone(
        cursor,
        """
        SELECT role.rolsuper,
               role.rolcreatedb,
               role.rolcreaterole,
               role.rolreplication,
               role.rolbypassrls
          FROM pg_roles AS role
         WHERE role.rolname = %s
        """,
        (role_name,),
    )
    inherited_admin = _fetchone(
        cursor,
        """
        WITH RECURSIVE inherited(role_oid) AS (
          SELECT membership.roleid
            FROM pg_auth_members AS membership
           WHERE membership.member = (SELECT oid FROM pg_roles WHERE rolname = %s)
          UNION
          SELECT membership.roleid
            FROM pg_auth_members AS membership
            JOIN inherited ON inherited.role_oid = membership.member
        )
        SELECT EXISTS (
          SELECT 1
            FROM inherited
            JOIN pg_roles AS parent ON parent.oid = inherited.role_oid
           WHERE parent.rolsuper
              OR parent.rolcreatedb
              OR parent.rolcreaterole
              OR parent.rolreplication
              OR parent.rolbypassrls
              OR parent.rolname = 'cloudsqlsuperuser'
        )
        """,
        (role_name,),
    )[0]
    if any(row) or inherited_admin:
        raise MigrationError(
            "Migration and runtime roles must not have administrative privileges."
        )


def _verify_schema_contract(
    cursor: Any,
    schema_name: str,
    owner_role: str,
    runtime_role: str,
    *,
    allow_runtime_usage: bool,
) -> None:
    owner, unsafe_privileges = _fetchone(
        cursor,
        """
        SELECT owner.rolname,
               EXISTS (
                 SELECT 1
                   FROM aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) AS acl
                  WHERE acl.grantee <> n.nspowner
                    AND NOT (
                      %s
                      AND acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
                      AND acl.privilege_type = 'USAGE'
                    )
               )
          FROM pg_namespace AS n
          JOIN pg_roles AS owner ON owner.oid = n.nspowner
         WHERE n.nspname = %s
        """,
        (allow_runtime_usage, runtime_role, schema_name),
    )
    if owner != owner_role or unsafe_privileges:
        raise MigrationError("Bootstrap schema ownership or access control is unsafe.")


def _schema_objects(cursor: Any, schema_name: str) -> list[str]:
    rows = _fetchall(
        cursor,
        """
        SELECT object_kind || ':' || object_name
          FROM (
            SELECT 'relation' AS object_kind, c.relname AS object_name
              FROM pg_class AS c
             WHERE c.relnamespace = to_regnamespace(%s)
               AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            UNION ALL
            SELECT 'routine', p.proname
              FROM pg_proc AS p
             WHERE p.pronamespace = to_regnamespace(%s)
            UNION ALL
            SELECT 'type', t.typname
              FROM pg_type AS t
             WHERE t.typnamespace = to_regnamespace(%s)
               AND t.typtype IN ('e', 'd')
          ) AS objects
         ORDER BY object_kind, object_name
        """,
        (schema_name, schema_name, schema_name),
    )
    return [str(row[0]) for row in rows]


def _unexpected_external_objects(
    cursor: Any, app_schema: str, migration_schema: str
) -> list[str]:
    rows = _fetchall(
        cursor,
        """
        SELECT schema_name || '.' || object_kind || ':' || object_name
          FROM (
            SELECT n.nspname AS schema_name, 'relation' AS object_kind, c.relname AS object_name
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname !~ '^pg_'
               AND n.nspname <> 'information_schema'
               AND n.nspname NOT IN (%s, %s)
               AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            UNION ALL
            SELECT n.nspname, 'routine', p.proname
              FROM pg_proc AS p
              JOIN pg_namespace AS n ON n.oid = p.pronamespace
             WHERE n.nspname !~ '^pg_'
               AND n.nspname <> 'information_schema'
               AND n.nspname NOT IN (%s, %s)
            UNION ALL
            SELECT n.nspname, 'type', t.typname
              FROM pg_type AS t
              JOIN pg_namespace AS n ON n.oid = t.typnamespace
             WHERE n.nspname !~ '^pg_'
               AND n.nspname <> 'information_schema'
               AND n.nspname NOT IN (%s, %s)
               AND t.typtype IN ('e', 'd')
          ) AS objects
         ORDER BY schema_name, object_kind, object_name
        """,
        (
            app_schema,
            migration_schema,
            app_schema,
            migration_schema,
            app_schema,
            migration_schema,
        ),
    )
    return [str(row[0]) for row in rows]


def _ledger_exists(cursor: Any, migration_schema: str) -> bool:
    return bool(
        _fetchone(
            cursor,
            """
            SELECT EXISTS (
              SELECT 1
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
               WHERE n.nspname = %s
                 AND c.relname = 'schema_migrations'
                 AND c.relkind IN ('r', 'p')
            )
            """,
            (migration_schema,),
        )[0]
    )


def _create_ledger(cursor: Any, migration_schema: str) -> None:
    ledger = _qualified(migration_schema, "schema_migrations")
    cursor.execute(
        f"""
        CREATE TABLE {ledger} (
          migration_id varchar(64) PRIMARY KEY,
          migration_name varchar(120) NOT NULL,
          checksum char(64) NOT NULL CHECK (checksum ~ '^[a-f0-9]{{64}}$'),
          applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          applied_by text NOT NULL DEFAULT current_user,
          source_revision text NOT NULL,
          runner_version varchar(32) NOT NULL,
          execution_id uuid NOT NULL UNIQUE
        )
        """
    )
    cursor.execute(f"REVOKE ALL ON {ledger} FROM PUBLIC")


def _verify_ledger(cursor: Any, migration_schema: str, migration_role: str) -> None:
    ledger = _qualified(migration_schema, "schema_migrations")
    objects = _schema_objects(cursor, migration_schema)
    if objects != ["relation:schema_migrations"]:
        raise MigrationError(
            "The migration control schema contains unexpected objects."
        )
    owner = _fetchone(
        cursor,
        "SELECT tableowner FROM pg_tables WHERE schemaname = %s AND tablename = 'schema_migrations'",
        (migration_schema,),
    )[0]
    ledger_state = _fetchone(
        cursor,
        """
        SELECT c.relkind = 'r',
               NOT c.relhasrules,
               NOT c.relrowsecurity,
               NOT c.relforcerowsecurity,
               NOT EXISTS (
                 SELECT 1 FROM pg_trigger WHERE tgrelid = c.oid AND NOT tgisinternal
               ),
               NOT EXISTS (
                 SELECT 1 FROM pg_policy WHERE polrelid = c.oid
               )
          FROM pg_class AS c
         WHERE c.oid = to_regclass(%s)
        """,
        (ledger,),
    )
    columns = _fetchall(
        cursor,
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod),
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid)
          FROM pg_attribute AS a
          LEFT JOIN pg_attrdef AS d
            ON d.adrelid = a.attrelid
           AND d.adnum = a.attnum
         WHERE a.attrelid = to_regclass(%s)
           AND a.attnum > 0
           AND NOT a.attisdropped
         ORDER BY a.attnum
        """,
        (ledger,),
    )
    expected_columns = [
        ("migration_id", "character varying(64)", True, None),
        ("migration_name", "character varying(120)", True, None),
        ("checksum", "character(64)", True, None),
        ("applied_at", "timestamp with time zone", True, "clock_timestamp()"),
        ("applied_by", "text", True, "CURRENT_USER"),
        ("source_revision", "text", True, None),
        ("runner_version", "character varying(32)", True, None),
        ("execution_id", "uuid", True, None),
    ]
    constraints = _fetchall(
        cursor,
        """
        SELECT contype::text, pg_get_constraintdef(oid, true)
          FROM pg_constraint
         WHERE conrelid = to_regclass(%s)
         ORDER BY contype, pg_get_constraintdef(oid, true)
        """,
        (ledger,),
    )
    nonowner_access = _fetchone(
        cursor,
        """
        SELECT EXISTS (
          SELECT 1
            FROM pg_class AS c
            CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) AS acl
           WHERE c.oid = to_regclass(%s)
             AND acl.grantee <> c.relowner
        )
        """,
        (ledger,),
    )[0]
    if (
        owner != migration_role
        or not all(ledger_state)
        or columns != expected_columns
        or sorted(kind for kind, _ in constraints) != ["c", "p", "u"]
        or not any(
            kind == "c" and "checksum" in definition and "^[a-f0-9]{64}$" in definition
            for kind, definition in constraints
        )
        or ("p", "PRIMARY KEY (migration_id)") not in constraints
        or ("u", "UNIQUE (execution_id)") not in constraints
        or nonowner_access
    ):
        raise MigrationError(
            "The migration ledger structure, owner, or access is unsafe."
        )


def _read_ledger(cursor: Any, migration_schema: str) -> list[tuple[str, str, str]]:
    statement = (
        f"SELECT migration_id, migration_name, checksum "  # noqa: S608  # nosec B608
        f"FROM {_qualified(migration_schema, 'schema_migrations')} ORDER BY migration_id"
    )
    return _fetchall(cursor, statement)


def _validate_ledger(
    entries: list[tuple[str, str, str]], migrations: list[Migration]
) -> None:
    expected_ids = [migration.migration_id for migration in migrations]
    recorded_ids = [migration_id for migration_id, _, _ in entries]
    if recorded_ids != expected_ids[: len(recorded_ids)]:
        raise MigrationError("The migration ledger is not an approved manifest prefix.")
    expected = {
        migration.migration_id: (migration.name, migration.checksum)
        for migration in migrations
    }
    for migration_id, name, checksum in entries:
        if (name, checksum) != expected[migration_id]:
            raise MigrationError(
                f"Applied migration {migration_id} has a checksum mismatch."
            )


def _apply_runtime_privileges(
    cursor: Any, app_schema: str, migration_schema: str, runtime_role: str
) -> None:
    app = _quote_identifier(app_schema)
    control = _quote_identifier(migration_schema)
    runtime = _quote_identifier(runtime_role)
    audit = _qualified(app_schema, "audit_events")
    statements = [
        f"REVOKE ALL ON SCHEMA {control} FROM {runtime}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {app} FROM PUBLIC",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {app} FROM PUBLIC",
        f"REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA {app} FROM PUBLIC",
        f"GRANT USAGE ON SCHEMA {app} TO {runtime}",
        f"REVOKE CREATE ON SCHEMA {app} FROM {runtime}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {app} TO {runtime}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {app} TO {runtime}",
        f"REVOKE UPDATE, DELETE, TRUNCATE ON {audit} FROM {runtime}",
        (
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {app} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime}"
        ),
        (
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {app} "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {runtime}"
        ),
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {app} GRANT USAGE ON TYPES TO {runtime}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {app} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {app} REVOKE USAGE ON TYPES FROM PUBLIC",
    ]
    for statement in statements:
        cursor.execute(statement)
    type_names = _fetchall(
        cursor,
        """
        SELECT t.typname
          FROM pg_type AS t
         WHERE t.typnamespace = to_regnamespace(%s)
           AND t.typtype IN ('e', 'd')
         ORDER BY t.typname
        """,
        (app_schema,),
    )
    for (type_name,) in type_names:
        cursor.execute(
            f"REVOKE ALL ON TYPE {_qualified(app_schema, str(type_name))} FROM PUBLIC"
        )
        cursor.execute(
            f"GRANT USAGE ON TYPE {_qualified(app_schema, str(type_name))} TO {runtime}"
        )


def _verify_runtime_privileges(
    cursor: Any, app_schema: str, migration_schema: str, runtime_role: str
) -> None:
    app_usage, app_create, control_usage = _fetchone(
        cursor,
        "SELECT has_schema_privilege(%s, %s, 'USAGE'), "
        "has_schema_privilege(%s, %s, 'CREATE'), "
        "has_schema_privilege(%s, %s, 'USAGE')",
        (
            runtime_role,
            app_schema,
            runtime_role,
            app_schema,
            runtime_role,
            migration_schema,
        ),
    )
    table_privileges = _fetchone(
        cursor,
        """
        SELECT COALESCE(bool_and(
                 has_table_privilege(%s, quote_ident(schemaname) || '.' || quote_ident(tablename), 'SELECT')
                 AND has_table_privilege(
                   %s, quote_ident(schemaname) || '.' || quote_ident(tablename), 'INSERT'
                 )
                 AND has_table_privilege(
                   %s, quote_ident(schemaname) || '.' || quote_ident(tablename), 'UPDATE'
                 )
                 AND has_table_privilege(
                   %s, quote_ident(schemaname) || '.' || quote_ident(tablename), 'DELETE'
                 )
               ), false)
          FROM pg_tables
         WHERE schemaname = %s
           AND tablename <> 'audit_events'
        """,
        (runtime_role, runtime_role, runtime_role, runtime_role, app_schema),
    )[0]
    audit_select_insert, audit_update_delete = _fetchone(
        cursor,
        "SELECT has_table_privilege(%s, %s, 'SELECT') "
        "AND has_table_privilege(%s, %s, 'INSERT'), "
        "has_table_privilege(%s, %s, 'UPDATE') "
        "OR has_table_privilege(%s, %s, 'DELETE') "
        "OR has_table_privilege(%s, %s, 'TRUNCATE')",
        (
            runtime_role,
            _qualified(app_schema, "audit_events"),
            runtime_role,
            _qualified(app_schema, "audit_events"),
            runtime_role,
            _qualified(app_schema, "audit_events"),
            runtime_role,
            _qualified(app_schema, "audit_events"),
            runtime_role,
            _qualified(app_schema, "audit_events"),
        ),
    )
    ledger_access = _fetchone(
        cursor,
        "SELECT has_table_privilege(%s, %s, 'SELECT') "
        "OR has_table_privilege(%s, %s, 'INSERT') "
        "OR has_table_privilege(%s, %s, 'UPDATE') "
        "OR has_table_privilege(%s, %s, 'DELETE') "
        "OR has_table_privilege(%s, %s, 'TRUNCATE')",
        (
            runtime_role,
            _qualified(migration_schema, "schema_migrations"),
            runtime_role,
            _qualified(migration_schema, "schema_migrations"),
            runtime_role,
            _qualified(migration_schema, "schema_migrations"),
            runtime_role,
            _qualified(migration_schema, "schema_migrations"),
            runtime_role,
            _qualified(migration_schema, "schema_migrations"),
        ),
    )[0]
    type_privileges = _fetchone(
        cursor,
        """
        SELECT COALESCE(bool_and(has_type_privilege(%s, t.oid, 'USAGE')), false)
          FROM pg_type AS t
         WHERE t.typnamespace = to_regnamespace(%s)
           AND t.typtype IN ('e', 'd')
        """,
        (runtime_role, app_schema),
    )[0]
    public_object_access = _fetchone(
        cursor,
        """
        SELECT EXISTS (
          SELECT 1
            FROM pg_class AS c
            CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) AS acl
           WHERE c.relnamespace = to_regnamespace(%s)
             AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             AND acl.grantee = 0
          UNION ALL
          SELECT 1
            FROM pg_proc AS p
            CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
           WHERE p.pronamespace = to_regnamespace(%s)
             AND acl.grantee = 0
          UNION ALL
          SELECT 1
            FROM pg_type AS t
            CROSS JOIN LATERAL aclexplode(COALESCE(t.typacl, acldefault('T', t.typowner))) AS acl
           WHERE t.typnamespace = to_regnamespace(%s)
             AND t.typtype IN ('e', 'd')
             AND acl.grantee = 0
        )
        """,
        (app_schema, app_schema, app_schema),
    )[0]
    if (
        not app_usage
        or app_create
        or control_usage
        or not table_privileges
        or not audit_select_insert
        or audit_update_delete
        or ledger_access
        or not type_privileges
        or public_object_access
    ):
        raise MigrationError(
            "Runtime database privileges do not match the approved policy."
        )


def _verify_app_object_ownership(
    cursor: Any, app_schema: str, migration_role: str
) -> None:
    ownership_violation = _fetchone(
        cursor,
        """
        SELECT EXISTS (
          SELECT 1
            FROM pg_class AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.relnamespace
            JOIN pg_roles AS owner ON owner.oid = object.relowner
           WHERE namespace.nspname = %s
             AND object.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             AND owner.rolname <> %s
          UNION ALL
          SELECT 1
            FROM pg_proc AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.pronamespace
            JOIN pg_roles AS owner ON owner.oid = object.proowner
           WHERE namespace.nspname = %s
             AND owner.rolname <> %s
          UNION ALL
          SELECT 1
            FROM pg_type AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.typnamespace
            JOIN pg_roles AS owner ON owner.oid = object.typowner
           WHERE namespace.nspname = %s
             AND object.typtype IN ('e', 'd')
             AND owner.rolname <> %s
        )
        """,
        (
            app_schema,
            migration_role,
            app_schema,
            migration_role,
            app_schema,
            migration_role,
        ),
    )[0]
    if ownership_violation:
        raise MigrationError(
            "Application object ownership or access control has drifted."
        )


def _verify_app_object_contract(
    cursor: Any, app_schema: str, migration_role: str, runtime_role: str
) -> None:
    _verify_app_object_ownership(cursor, app_schema, migration_role)
    excessive_acl = _fetchone(
        cursor,
        """
        SELECT EXISTS (
          SELECT 1
            FROM pg_class AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.relnamespace
            CROSS JOIN LATERAL aclexplode(
              COALESCE(object.relacl, acldefault(
                CASE WHEN object.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                object.relowner
              ))
            ) AS acl
           WHERE namespace.nspname = %s
             AND object.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             AND acl.grantee <> object.relowner
             AND NOT (
               acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
               AND (
                 (object.relkind = 'S' AND acl.privilege_type IN ('USAGE', 'SELECT'))
                 OR (
                   object.relkind <> 'S'
                   AND object.relname <> 'audit_events'
                   AND acl.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
                 )
                 OR (
                   object.relname = 'audit_events'
                   AND acl.privilege_type IN ('SELECT', 'INSERT')
                 )
               )
             )
          UNION ALL
          SELECT 1
            FROM pg_proc AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.pronamespace
            CROSS JOIN LATERAL aclexplode(
              COALESCE(object.proacl, acldefault('f', object.proowner))
            ) AS acl
           WHERE namespace.nspname = %s
             AND acl.grantee <> object.proowner
          UNION ALL
          SELECT 1
            FROM pg_type AS object
            JOIN pg_namespace AS namespace ON namespace.oid = object.typnamespace
            CROSS JOIN LATERAL aclexplode(
              COALESCE(object.typacl, acldefault('T', object.typowner))
            ) AS acl
           WHERE namespace.nspname = %s
             AND object.typtype IN ('e', 'd')
             AND acl.grantee <> object.typowner
             AND NOT (
               acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
               AND acl.privilege_type = 'USAGE'
             )
        )
        """,
        (app_schema, runtime_role, app_schema, app_schema, runtime_role),
    )[0]
    default_acl_rows = _fetchall(
        cursor,
        """
        SELECT owner.rolname,
               defaults.defaclobjtype::text,
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type
          FROM pg_default_acl AS defaults
          JOIN pg_roles AS owner ON owner.oid = defaults.defaclrole
          CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
          LEFT JOIN pg_roles AS grantee ON grantee.oid = acl.grantee
         WHERE defaults.defaclnamespace = to_regnamespace(%s)
           AND acl.grantee <> defaults.defaclrole
         ORDER BY 1, 2, 3, 4
        """,
        (app_schema,),
    )
    expected_default_acl = sorted(
        [
            (migration_role, "r", runtime_role, privilege)
            for privilege in ("DELETE", "INSERT", "SELECT", "UPDATE")
        ]
        + [
            (migration_role, "S", runtime_role, privilege)
            for privilege in ("SELECT", "USAGE")
        ]
        + [(migration_role, "T", runtime_role, "USAGE")]
    )
    if excessive_acl or sorted(default_acl_rows) != expected_default_acl:
        raise MigrationError(
            "Application object ownership or access control has drifted."
        )


def apply_migrations(
    connection: Any,
    migrations: list[Migration],
    app_schema: str,
    migration_schema: str,
    *,
    expected_database: str,
    expected_migration_role: str,
    expected_runtime_role: str,
    lock_timeout_seconds: int = 30,
    statement_timeout_seconds: int = 300,
    source_revision: str = "local",
) -> list[str]:
    """Apply all pending migrations in one transaction on an existing connection."""
    if lock_timeout_seconds < 1 or statement_timeout_seconds < 1:
        raise MigrationError("Migration timeouts must be positive whole seconds.")
    if not expected_database:
        raise MigrationError("Expected database is required.")
    app_schema = _validate_schema_name(app_schema, "Application schema")
    migration_schema = _validate_schema_name(migration_schema, "Migration schema")
    migration_role = _validate_role_name(expected_migration_role, "Migration role")
    runtime_role = _validate_role_name(expected_runtime_role, "Runtime role")
    if app_schema == migration_schema or migration_role == runtime_role:
        raise MigrationError(
            "Application/control schemas and migration/runtime roles must differ."
        )

    cursor = connection.cursor()
    try:
        database_name, session_user, server_version = _fetchone(
            cursor,
            "SELECT current_database(), session_user, current_setting('server_version_num')::integer",
        )
        if int(server_version) // 10000 != 16:
            raise MigrationError(
                "The migration runner requires PostgreSQL major version 16."
            )
        if database_name != expected_database or session_user != migration_role:
            raise MigrationError(
                "The connected database or migration identity is not the approved target."
            )
        _verify_role_safety(cursor, migration_role)
        _verify_role_safety(cursor, runtime_role)
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{lock_timeout_seconds}s",),
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{statement_timeout_seconds}s",),
        )
        cursor.execute(
            "SELECT set_config('idle_in_transaction_session_timeout', %s, true)",
            (f"{statement_timeout_seconds}s",),
        )
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"elder-engagement:{database_name}:{app_schema}",),
        )

        if not _schema_exists(cursor, app_schema) or not _schema_exists(
            cursor, migration_schema
        ):
            raise MigrationError(
                "Bootstrap must create both approved schemas before migration."
            )
        _verify_schema_contract(
            cursor,
            app_schema,
            migration_role,
            runtime_role,
            allow_runtime_usage=True,
        )
        _verify_schema_contract(
            cursor,
            migration_schema,
            migration_role,
            runtime_role,
            allow_runtime_usage=False,
        )
        external_objects = _unexpected_external_objects(
            cursor, app_schema, migration_schema
        )
        if external_objects:
            raise MigrationError(
                "The target database contains unexpected objects outside the approved schemas."
            )

        if _ledger_exists(cursor, migration_schema):
            _verify_ledger(cursor, migration_schema, migration_role)
        else:
            if _schema_objects(cursor, app_schema) or _schema_objects(
                cursor, migration_schema
            ):
                raise MigrationError(
                    "The first migration requires empty application and control schemas."
                )
            _create_ledger(cursor, migration_schema)
            _verify_ledger(cursor, migration_schema, migration_role)

        entries = _read_ledger(cursor, migration_schema)
        _validate_ledger(entries, migrations)
        pending = migrations[len(entries) :]
        applied: list[str] = []
        for migration in pending:
            if migration.requires_empty and _schema_objects(cursor, app_schema):
                raise MigrationError(
                    f"Migration {migration.migration_id} requires an empty application schema."
                )
            cursor.execute(
                "SELECT set_config('search_path', %s, true)",
                (f"{app_schema},pg_catalog",),
            )
            for statement in migration.statements:
                cursor.execute(statement)
            statement = (
                f"INSERT INTO {_qualified(migration_schema, 'schema_migrations')} "  # noqa: S608  # nosec B608
                "(migration_id, migration_name, checksum, source_revision, "
                "runner_version, execution_id) VALUES (%s, %s, %s, %s, %s, %s)"
            )
            cursor.execute(
                statement,
                (
                    migration.migration_id,
                    migration.name,
                    migration.checksum,
                    source_revision,
                    RUNNER_VERSION,
                    str(uuid.uuid4()),
                ),
            )
            applied.append(migration.migration_id)

        final_entries = _read_ledger(cursor, migration_schema)
        _validate_ledger(final_entries, migrations)
        if len(final_entries) != len(migrations):
            raise MigrationError(
                "The migration ledger did not record every applied migration."
            )
        _verify_app_object_ownership(cursor, app_schema, migration_role)
        _apply_runtime_privileges(cursor, app_schema, migration_schema, runtime_role)
        _verify_runtime_privileges(cursor, app_schema, migration_schema, runtime_role)
        _verify_app_object_contract(cursor, app_schema, migration_role, runtime_role)
        connection.commit()
        return applied
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def run_test_migrations(
    database_url: str,
    manifest_path: Path,
    app_schema: str,
    migration_schema: str,
    *,
    expected_database: str,
    expected_migration_role: str,
    expected_runtime_role: str,
    lock_timeout_seconds: int = 30,
    statement_timeout_seconds: int = 300,
    source_revision: str = "ci-test",
) -> list[str]:
    """Password connection supported only by the disposable test harness."""
    if not database_url:
        raise MigrationError("The test DATABASE_URL is required.")
    migrations = load_manifest(manifest_path)
    connection = psycopg.connect(
        database_url, application_name="engagement-schema-migration-test"
    )
    try:
        return apply_migrations(
            connection,
            migrations,
            app_schema,
            migration_schema,
            expected_database=expected_database,
            expected_migration_role=expected_migration_role,
            expected_runtime_role=expected_runtime_role,
            lock_timeout_seconds=lock_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            source_revision=source_revision,
        )
    finally:
        connection.close()


def run_production_migrations() -> list[str]:
    """Use private-IP Cloud SQL Connector with automatic IAM database authentication."""
    if os.environ.get("DATABASE_URL"):
        raise MigrationError(
            "Production migration refuses password connection strings."
        )
    instance = os.environ.get("INSTANCE_CONNECTION_NAME", "")
    database_name = os.environ.get("DB_NAME", "")
    migration_role = os.environ.get("DB_MIGRATION_IAM_USER", "")
    runtime_role = os.environ.get("DB_RUNTIME_IAM_USER", "")
    source_revision = os.environ.get("SOURCE_REVISION", "")
    if (
        not instance
        or instance.count(":") != 2
        or any(character.isspace() for character in instance)
    ):
        raise MigrationError("INSTANCE_CONNECTION_NAME is invalid.")
    if not database_name:
        raise MigrationError("DB_NAME is required.")
    if not REVISION_PATTERN.fullmatch(source_revision):
        raise MigrationError(
            "SOURCE_REVISION must be the exact 40-character Git revision."
        )
    _validate_role_name(migration_role, "Migration role")
    _validate_role_name(runtime_role, "Runtime role")

    try:
        from google.cloud.sql.connector import Connector, IPTypes
    except ImportError as exc:  # pragma: no cover - production image gate
        raise MigrationError(
            "The production Cloud SQL Connector is unavailable."
        ) from exc

    migrations = load_manifest(DEFAULT_MANIFEST)
    with Connector(
        ip_type=IPTypes.PRIVATE,
        enable_iam_auth=True,
        refresh_strategy="LAZY",
    ) as connector:
        connection = connector.connect(
            instance,
            "pg8000",
            user=migration_role,
            db=database_name,
            enable_iam_auth=True,
            ip_type=IPTypes.PRIVATE,
        )
        try:
            return apply_migrations(
                connection,
                migrations,
                os.environ.get("APP_SCHEMA", "engagement_app"),
                os.environ.get("MIGRATION_SCHEMA", "engagement_migrations"),
                expected_database=database_name,
                expected_migration_role=migration_role,
                expected_runtime_role=runtime_role,
                source_revision=source_revision,
            )
        finally:
            connection.close()


def main() -> int:
    mode = os.environ.get("MIGRATION_MODE", "")
    try:
        if mode == "production":
            applied = run_production_migrations()
        elif mode == "test":
            applied = run_test_migrations(
                os.environ.get("DATABASE_URL", ""),
                DEFAULT_MANIFEST,
                os.environ.get("APP_SCHEMA", "engagement_app"),
                os.environ.get("MIGRATION_SCHEMA", "engagement_migrations"),
                expected_database=os.environ.get("EXPECTED_DATABASE", ""),
                expected_migration_role=os.environ.get("EXPECTED_MIGRATION_ROLE", ""),
                expected_runtime_role=os.environ.get("EXPECTED_RUNTIME_ROLE", ""),
                source_revision=os.environ.get("SOURCE_REVISION", "ci-test"),
            )
        else:
            raise MigrationError(
                "MIGRATION_MODE must explicitly be test or production."
            )
    except MigrationError as exc:
        print(f"Migration rejected: {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - sanitize all driver/connector errors at the CLI boundary
        print(
            "Migration failed; PostgreSQL rolled back the transaction. Review private logs.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"applied": applied, "status": "ok"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
