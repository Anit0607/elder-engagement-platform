"""Execute staff-role race regressions against a disposable PostgreSQL 16 database."""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import errors, sql

DATABASE_URL = os.environ["DATABASE_URL"]
SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "V0001__engagement_baseline.sql"
)
USER_ID = "00000000-0000-4000-8000-000000000001"
PASSWORD_HASH = "test-only-password-hash"
SCHEMA_NAME = f"staff_guard_{uuid.uuid4().hex[:12]}"


def connect(application_name: str = "staff-role-test") -> psycopg.Connection:
    return psycopg.connect(
        DATABASE_URL,
        application_name=application_name,
        options=f"-csearch_path={SCHEMA_NAME},pg_catalog",
    )


def reset_user() -> None:
    with connect() as connection:
        connection.execute("DELETE FROM app_users WHERE id = %s", (USER_ID,))
        connection.execute(
            """
            INSERT INTO app_users (id, public_id, role, username)
            VALUES (%s, 'TEST-STAFF-1', 'contributor', 'test-staff-1')
            """,
            (USER_ID,),
        )


def wait_until_blocked(application_name: str) -> None:
    deadline = time.monotonic() + 5
    with connect("staff-role-observer") as observer:
        while time.monotonic() < deadline:
            waiting = observer.execute(
                """
                SELECT EXISTS (
                  SELECT 1
                    FROM pg_stat_activity
                   WHERE application_name = %s
                     AND wait_event_type = 'Lock'
                )
                """,
                (application_name,),
            ).fetchone()[0]
            if waiting:
                return
            time.sleep(0.05)
    raise AssertionError(f"{application_name} did not block on the protected user row")


def run_expected_check_violation(
    application_name: str, statement: str, result: list[object]
) -> None:
    try:
        with connect(application_name) as connection:
            connection.execute("SET LOCAL lock_timeout = '5s'")
            connection.execute(statement, (USER_ID,))
    except errors.CheckViolation:
        result.append("check_violation")
    except (
        psycopg.Error
    ) as exc:  # pragma: no cover - failure detail is surfaced to the workflow
        result.append(exc)
    else:
        result.append("unexpected_success")


def assert_final_state(expected_role: str, expected_credentials: bool) -> None:
    with connect() as connection:
        role = connection.execute(
            "SELECT role::text FROM app_users WHERE id = %s", (USER_ID,)
        ).fetchone()[0]
        credentials = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM staff_credentials WHERE user_id = %s)",
            (USER_ID,),
        ).fetchone()[0]
    assert role == expected_role
    assert credentials is expected_credentials


def test_insert_waits_for_concurrent_demotion() -> None:
    reset_user()
    demotion = connect("staff-role-demotion-owner")
    try:
        demotion.execute(
            "UPDATE app_users SET role = 'member' WHERE id = %s", (USER_ID,)
        )
        result: list[object] = []
        worker = threading.Thread(
            target=run_expected_check_violation,
            args=(
                "staff-role-concurrent-insert",
                "INSERT INTO staff_credentials (user_id, password_hash) VALUES (%s, 'test-only-password-hash')",
                result,
            ),
        )
        worker.start()
        wait_until_blocked("staff-role-concurrent-insert")
        demotion.commit()
        worker.join(timeout=6)
        assert not worker.is_alive()
        assert result == ["check_violation"], result
    finally:
        demotion.close()
    assert_final_state("member", False)


def test_demotion_waits_for_concurrent_insert() -> None:
    reset_user()
    credential_insert = connect("staff-role-insert-owner")
    try:
        credential_insert.execute(
            "INSERT INTO staff_credentials (user_id, password_hash) VALUES (%s, %s)",
            (USER_ID, PASSWORD_HASH),
        )
        result: list[object] = []
        worker = threading.Thread(
            target=run_expected_check_violation,
            args=(
                "staff-role-concurrent-demotion",
                "UPDATE app_users SET role = 'member' WHERE id = %s",
                result,
            ),
        )
        worker.start()
        wait_until_blocked("staff-role-concurrent-demotion")
        credential_insert.commit()
        worker.join(timeout=6)
        assert not worker.is_alive()
        assert result == ["check_violation"], result
    finally:
        credential_insert.close()
    assert_final_state("contributor", True)


def main() -> None:
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(SCHEMA_NAME))
            )
        with connect() as connection:
            connection.execute(SCHEMA.read_text(encoding="utf-8"))
        test_insert_waits_for_concurrent_demotion()
        test_demotion_waits_for_concurrent_insert()
        print("PostgreSQL 16 staff-role concurrency tests passed.")
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(SCHEMA_NAME)
                )
            )


if __name__ == "__main__":
    main()
