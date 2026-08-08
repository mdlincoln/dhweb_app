# DH Conferences CRUD App

Application for editing, searching, and browsing historical DH conference abstracts.

Development lead: [Matthew Lincoln](https://matthewlincoln.net)

## Overview

This is a **host-first** Django application for local development. Local development
runs Django directly on the host via `uv run ...`, with Docker Compose used only to run
the two backing services: **Postgres** and **Redis**. The full application stack
(app + nginx + redis + postgres) for production deployments lives in
[`docker-compose.prod.yml`](docker-compose.prod.yml).

- **Redis** — cache backend (`django.core.cache.backends.redis.RedisCache`), ephemeral
  (no persistence volume).
- **Postgres** — the Django app relies on several
  [PostgreSQL-only functions and fields](https://docs.djangoproject.com/en/3.0/ref/contrib/postgres/fields/),
  including full-text search. Data is stored in a named `db` docker volume, shared
  between the dev and prod compose files. `make backup` dumps the database to `data/`.
- **Django (host)** — the application runs on the host and builds from `pyproject.toml` /
  `uv.lock`, installed via `uv sync`. `docker-compose.prod.yml` builds the app image
  from `/Dockerfile` for production.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (≥ 0.11, for `uv run --env-file`)
- Docker (with Compose v2)

## Setup & Running (local development)

1. Copy `.env.template` → `.env` and fill in `POSTGRES_PASSWORD`, `POSTGRES_USER`,
   `POSTGRES_DB`, `DH_SECRET`, and `ALLOWED_HOSTS`.
2. Install dependencies: `uv sync` (from the repo root; this also installs dev
   tooling like `ruff` and `mypy`).
3. Start the backing services: `make infra` (starts Postgres and Redis; also
   auto-starts as a prerequisite of `make migrate`, `make test`, etc.).
4. Apply migrations: `make migrate`.
5. Start the host Django dev server with debug enabled: `make local`. It serves at
   `http://localhost:8000`.

Settings are env-driven with host-first defaults, so no new environment variables are
required for local dev: DB host/port default to `127.0.0.1`/`5432`, Redis to
`redis://127.0.0.1:6379`, `STATIC_ROOT` to `<repo>/staticfiles`, and
`DATA_OUTPUT_PATH` to `<repo>/data`.

> **Note:** `make` (or `make detached`) now only starts the Postgres + Redis infra.
> The app itself runs on the host. For interactive dev, use `make local`.

## Deployment

The full production stack is defined in [`docker-compose.prod.yml`](docker-compose.prod.yml)
(app + nginx + redis + postgres). Running it locally or in production requires an `.env`
file based on `.env.template`, with a DB password and secret, and the proper hostname,
email server, etc.

In production we currently use gunicorn to serve, so `SERVE_COMMAND` is set to
`'gunicorn dhweb.wsgi -b 0.0.0.0:8000 -w $SOME_INT'` where the number of workers
`$SOME_INT` is appropriate to the number of cores on the deployment machine.
`SERVE_COMMAND` is consumed only by the prod compose file.

Prod operations are handled by the corresponding Makefile targets, which reference
`docker-compose.prod.yml` and run migrations **inside** the app container:

```bash
make deploy     # migrate + collectstatic + restart inside the prod stack
make rebuild    # rebuild app & nginx images without cache
make restart    # restart app, nginx, redis
make stop       # stop app and nginx
make attach     # exec bash into the app container
```

## Updates

Update nginx, redis, and postgres versions by incrementing their version tags in
`docker-compose.prod.yml`.

Update the underlying Python version in `Dockerfile` (used by the prod compose
`app` build).

Update python packages in `pyproject.toml` and regenerate the lockfile with `uv lock`
(run from repo root).