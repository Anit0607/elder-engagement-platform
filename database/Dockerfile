FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ARG SOURCE_REVISION=unavailable
ARG SOURCE_URL=https://github.com/replace-at-build-time

LABEL org.opencontainers.image.title="Elder Engagement Database Migration" \
      org.opencontainers.image.description="Checksum-locked Elder Engagement PostgreSQL migration runner" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /migration

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --requirement requirements.lock \
    && addgroup --system engagement \
    && adduser --system --ingroup engagement --home /nonexistent engagement

COPY migration_runner.py ./migration_runner.py
COPY migrations ./migrations
RUN chmod -R a-w /migration

USER engagement

ENTRYPOINT ["python", "migration_runner.py"]
