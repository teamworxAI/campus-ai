# One image for tests, scripts and local models (weights mounted, never downloaded). Rebuild anywhere with:
#   docker compose build
FROM python:3.13-slim

# Optional extras from pyproject.toml, e.g. "embed".
ARG EXTRAS=""

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    MODELS_DIR=/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The optional `ca` build secret supports networks with a TLS-inspecting proxy.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir uv==0.11.32

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-install-project $(for e in $EXTRAS; do printf -- '--extra %s ' "$e"; done)

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen $(for e in $EXTRAS; do printf -- '--extra %s ' "$e"; done)

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
