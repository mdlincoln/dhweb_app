FROM python:3.12

# Install uv (pinned to a specific stable version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

# Place the venv outside /vol/dh so it is not shadowed by the dev volume mount.
# PATH ensures `python` and `gunicorn` resolve to the venv automatically,
# so all existing Makefile targets (which call `python manage.py`) work unchanged.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /vol/dh

# Install dependencies from the lockfile (cached layer; rebuilt only when lock changes).
# --frozen: refuse to update uv.lock; --no-dev: exclude ruff (never in the container).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy Django project source
COPY dh_abstracts/ /vol/dh/

EXPOSE 8000
