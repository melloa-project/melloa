ARG MELLOA_UV_IMAGE=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105
ARG MELLOA_PYTHON_IMAGE=python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

FROM ${MELLOA_UV_IMAGE} AS uv

FROM ${MELLOA_PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1 \
    UV_SYSTEM_CERTS=1
WORKDIR /opt/melloa
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=build_ca,required=true \
    SSL_CERT_FILE=/run/secrets/build_ca \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations

FROM ${MELLOA_PYTHON_IMAGE} AS runtime
ARG MELLOA_SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.title="Melloa private runtime" \
      org.opencontainers.image.source="https://github.com/melloa-project/melloa" \
      org.opencontainers.image.revision="${MELLOA_SOURCE_REVISION}"
ENV PATH="/opt/melloa/.venv/bin:${PATH}" \
    PYTHONPATH="/opt/melloa/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/melloa
COPY --from=build --chown=10001:10001 /opt/melloa /opt/melloa
USER 10001:10001
ENTRYPOINT ["/opt/melloa/.venv/bin/python", "-m", "melloa.apps.cli"]
CMD ["--help"]
