# One image for tests and scripts. Models are served on the host (vLLM or
# Ollama), not in this image. Rebuild anywhere with: docker compose build
FROM python:3.13-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The optional `ca` build secret supports networks with a TLS-inspecting proxy.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir uv==0.11.32

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
