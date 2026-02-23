FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/erauner/homelab-autodoist-events"
LABEL org.opencontainers.image.description="Autodoist Todoist webhook events worker"

RUN useradd -r -u 1000 -m app

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && cp -R .venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}"

RUN mkdir -p /app/data && chown -R app:app /app

USER app
WORKDIR /app/data

ENTRYPOINT ["autodoist-events"]
