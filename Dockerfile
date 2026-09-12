# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes --requirement requirements.lock

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src ./src
# Operator-only chaos/evaluation code is deliberately absent from service images.
RUN rm -rf ./src/incidentpilot/chaos ./src/incidentpilot/evaluation
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
# Explicit service command comes from Compose. No runtime package installation.
