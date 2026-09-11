from pathlib import Path

SERVICE_ROOT = Path(__file__).parents[1]


def test_container_source_is_root_owned_and_immutable_at_runtime():
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12.14-slim-bookworm@sha256:" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY --chown=engagement:engagement app" not in dockerfile
    assert "RUN chmod -R a-w /app/app" in dockerfile
    assert dockerfile.index("RUN chmod -R a-w /app/app") < dockerfile.index("USER engagement")
    assert 'ARG SOURCE_REVISION=unavailable' in dockerfile
    assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "socket.create_connection(('127.0.0.1', 8080), 2)" in dockerfile


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


def test_container_runtime_contract_is_cloud_run_compatible():
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "PORT=8080" in dockerfile
    assert "--host 0.0.0.0" in dockerfile
    assert "--port ${PORT}" in dockerfile
    assert "USER engagement" in dockerfile
    assert "COPY tests" not in dockerfile


def test_candidate_smoke_request_uses_the_configured_trusted_host():
    workflow_path = (
        SERVICE_ROOT.parents[1] / ".github" / "workflows" / "build-development-candidate.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "EE_TRUSTED_HOSTS=localhost" in workflow
    assert "--header 'Host: localhost' http://127.0.0.1:18080/health" in workflow
