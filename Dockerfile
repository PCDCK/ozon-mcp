# Minimal container for ozon-mcp. Used by Glama's introspection checks and
# anyone who wants to run the server in a sandbox instead of `uv run` on host.
# The image does not embed credentials — pass OZON_* at runtime via -e or
# --env-file.

FROM python:3.12-slim AS builder

# uv is installed to /usr/local/bin via the official installer. Keeping the
# dependency install in a dedicated stage lets the final image ship without
# the uv binary or build metadata.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (no project yet) so this layer caches across
# source changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Now bring in the actual package and install it without dev extras.
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Run as an unprivileged user — MCP stdio servers don't need any elevated
# privileges and Glama's automated checks prefer it.
RUN useradd --create-home --shell /bin/bash mcp
WORKDIR /app

# Copy just the virtual environment and source. Skip caches, git, tests.
COPY --from=builder --chown=mcp:mcp /app/.venv ./.venv
COPY --from=builder --chown=mcp:mcp /app/src ./src
COPY --chown=mcp:mcp pyproject.toml README.md ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER mcp

# MCP stdio protocol: stdin/stdout are the transport, logs go to stderr.
ENTRYPOINT ["ozon-mcp"]
