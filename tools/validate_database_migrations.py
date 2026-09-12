"""Validate migration naming, checksums, safety rules, and released-file immutability."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import sqlparse
from sqlparse import tokens

WORKSPACE = Path(__file__).resolve().parents[1]
MIGRATION_DIRECTORY = WORKSPACE / "database" / "migrations"
MANIFEST_PATH = MIGRATION_DIRECTORY / "manifest.json"
ID_PATTERN = re.compile(r"^V[0-9]{4}$")
NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
FORBIDDEN_SQL = {
    "database creation": re.compile(r"(?i)\b(CREATE|DROP)\s+DATABASE\b"),
    "role administration": re.compile(r"(?i)\b(CREATE|ALTER|DROP)\s+ROLE\b"),
    "extension administration": re.compile(r"(?i)\b(CREATE|ALTER|DROP)\s+EXTENSION\b"),
    "psql command": re.compile(r"(?m)^\s*\\"),
}


def _transaction_control_present(sql_text: str) -> bool:
    for statement_text in sqlparse.split(sql_text):
        parsed = sqlparse.parse(statement_text)
        if len(parsed) != 1:
            return True
        words = [
            token.value.upper()
            for token in parsed[0].flatten()
            if not token.is_whitespace and token.ttype not in tokens.Comment
        ]
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
            return True
    return False


def _load_manifest(contents: str) -> dict:
    try:
        manifest = json.loads(contents)
    except json.JSONDecodeError as exc:
        raise ValueError("Migration manifest is not valid JSON.") from exc
    if manifest.get("manifest_version") != 1 or not isinstance(
        manifest.get("migrations"), list
    ):
        raise ValueError("Migration manifest version or entries are invalid.")
    return manifest


def validate_current() -> list[str]:
    errors: list[str] = []
    try:
        manifest = _load_manifest(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [str(exc)]

    ids: list[str] = []
    files: set[str] = set()
    for entry in manifest["migrations"]:
        if not isinstance(entry, dict):
            errors.append("Every migration entry must be an object.")
            continue
        migration_id = entry.get("id")
        name = entry.get("name")
        filename = entry.get("file")
        checksum = entry.get("sha256")
        if not isinstance(migration_id, str) or not ID_PATTERN.fullmatch(migration_id):
            errors.append(f"Invalid migration id: {migration_id!r}.")
            continue
        ids.append(migration_id)
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            errors.append(f"{migration_id} has an invalid name.")
        expected_filename = f"{migration_id}__{name}.sql"
        if filename != expected_filename:
            errors.append(f"{migration_id} must use filename {expected_filename}.")
            continue
        if filename in files:
            errors.append(f"Duplicate migration file: {filename}.")
        files.add(filename)
        migration_path = MIGRATION_DIRECTORY / filename
        try:
            migration_bytes = migration_path.read_bytes()
            migration_sql = migration_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"{migration_id} cannot be read as UTF-8 SQL.")
            continue
        actual_checksum = hashlib.sha256(migration_bytes).hexdigest()
        if checksum != actual_checksum:
            errors.append(f"{migration_id} does not match its manifest checksum.")
        if _transaction_control_present(migration_sql):
            errors.append(f"{migration_id} contains forbidden transaction control.")
        for label, pattern in FORBIDDEN_SQL.items():
            if pattern.search(migration_sql):
                errors.append(f"{migration_id} contains forbidden {label}.")

    if not ids:
        errors.append("At least one migration is required.")
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        errors.append("Migration ids must be unique and ordered.")
    disk_files = {
        path.name for path in MIGRATION_DIRECTORY.glob("V[0-9][0-9][0-9][0-9]__*.sql")
    }
    if disk_files != files:
        errors.append("Migration files on disk must exactly match the manifest.")
    return errors


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *arguments],  # noqa: S607
        cwd=WORKSPACE,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def validate_immutable_base(base_revision: str) -> list[str]:
    errors: list[str] = []
    manifest_reference = f"{base_revision}:database/migrations/manifest.json"
    previous = _git("show", manifest_reference)
    if previous.returncode != 0:
        return []
    try:
        old_manifest = _load_manifest(previous.stdout)
        current_manifest = _load_manifest(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [str(exc)]

    old_entries = old_manifest["migrations"]
    current_prefix = current_manifest["migrations"][: len(old_entries)]
    if current_prefix != old_entries:
        errors.append(
            "Released migration manifest entries cannot be changed, removed, or reordered."
        )
    for entry in old_entries:
        filename = entry.get("file")
        if not isinstance(filename, str):
            continue
        relative_path = f"database/migrations/{filename}"
        changed = _git("diff", "--name-only", base_revision, "--", relative_path)
        if changed.returncode != 0 or changed.stdout.strip():
            errors.append(f"Released migration file changed: {filename}.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--immutable-base")
    arguments = parser.parse_args()
    errors = validate_current()
    if arguments.immutable_base:
        errors.extend(validate_immutable_base(arguments.immutable_base))
    if errors:
        print(
            f"Migration validation failed with {len(errors)} issue(s):", file=sys.stderr
        )
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Migration validation passed: manifest, checksums, SQL safety and immutability are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
