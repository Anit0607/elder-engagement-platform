FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ARG SOURCE_REVISION=unavailable
ARG SOURCE_URL=https://github.com/replace-at-build-time

LABEL org.opencontainers.image.title="Elder Engagement API" \
      org.opencontainers.image.description="Elder Engagement Platform REST service" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --requirement requirements.lock \
    && addgroup --system engagement \
    && adduser --system --ingroup engagement --home /nonexistent engagement

COPY app ./app
RUN chmod -R a-w /app/app

USER engagement
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()"]

CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --no-access-log"]
