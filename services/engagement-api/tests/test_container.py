from pathlib import Path

SERVICE_ROOT = Path(__file__).parents[1]


def test_container_source_is_root_owned_and_immutable_at_runtime():
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12.14-slim-bookworm@sha256:" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY --chown=engagement:engagement app" not in dockerfile
    assert "RUN chmod -R a-w /app/app" in dockerfile
    assert dockerfile.index("RUN chmod -R a-w /app/app") < dockerfile.index("USER engagement")


def test_container_context_excludes_local_state_and_credentials():
    ignored = set((SERVICE_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".git", ".venv", "tests", "*.env", "*.db"} <= ignored


def test_local_run_path_is_service_owned_and_does_not_reference_legacy_backend():
    readme = (SERVICE_ROOT / "README.md").read_text(encoding="utf-8")
    runner = (SERVICE_ROOT / "tools" / "run_local.py").read_text(encoding="utf-8")
    assert "..\\..\\backend" not in readme
    assert "py -3.12 -m venv .venv" in readme
    assert ".\\.venv\\Scripts\\python.exe -m tools.run_local" in readme
    assert "from backend" not in runner
    assert "127.0.0.1" in runner
