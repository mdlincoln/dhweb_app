# AGENTS.md

Guidance for AI agents (and humans) working in this codebase.

## Project Overview

**DH Conferences CRUD App** (`dh_abstracts` / `dhweb`) — a Django application for editing,
searching, and browsing historical Digital Humanities (DH) conference abstracts. Data is
sourced primarily from ADHO (Alliance for Digital Humanities Organizations) TEI XML files.

Development lead: [Matthew Lincoln](https://matthewlincoln.net). Hosted under the
dSHARP-CMU / cmu-lib GitHub organizations.

## Tech Stack

| Component      | Version   | Notes                                                            |
| -------------- | --------- | ---------------------------------------------------------------- |
| Python         | 3.12      | Pinned in `Dockerfile`; deps managed by uv                        |
| Django         | 5.2.x LTS | LTS release (supported through April 2028)                        |
| PostgreSQL     | 18       | **Required** — uses `contrib.postgres` full-text search fields   |
| Redis          | 7.4       | Cache backend (Django built-in RedisCache, redis-py driver), 10-minute default timeout |
| nginx          | 1.22.0    | Reverse proxy + static file serving                              |
| gunicorn       | 23.0      | Production WSGI server (via `SERVE_COMMAND` env var)              |

Key Python dependencies (declared in `pyproject.toml`, locked in `uv.lock`):

- `django-autocomplete-light` (dal) — autocomplete widgets throughout forms/views
- `django-crispy-forms` + `crispy-bootstrap4` — form rendering (template pack is a separate package as of crispy-forms 2.0)
- `django-filer` — file/media management
- `django-compressor` + `django-libsass` — SCSS compilation, static asset bundling
- `django-markdownify` — markdown rendering (bleach-whitelisted)
- `django-mptt`, `django-polymorphic` — tree structures, polymorphic models
- `lxml` — TEI XML parsing and validation
- `psycopg[binary]` — PostgreSQL driver (psycopg3)
- `redis` (redis-py) — drives Django's built-in `RedisCache` cache backend
- `easy-thumbnails` — image thumbnails

Dev tooling: `ruff` (formatting + linting), `coverage` + `django-coverage-plugin`.
Note that `ruff` is in `[dependency-groups] dev` in `pyproject.toml` and is excluded
from the Docker image via `uv sync --no-dev` — it is not installed inside the Docker
container and must be run on the host or a separate dev environment. `coverage`
and `django-coverage-plugin` are in `pyproject.toml` dependencies and available in-container.

## Repository Layout

```
.
├── docker-compose.yml          # Orchestrates postgres, app, redis, nginx
├── Dockerfile                  # App image build (uv-based)
├── pyproject.toml              # PEP 621 dependency spec (uv)
├── uv.lock                     # Locked dependency manifest (uv)
├── .dockerignore               # Docker build context exclusions
├── Makefile                    # All common dev/deploy operations
├── .env.template               # Copy to .env and fill in secrets
├── nginx/                      # nginx conf.d templates (mounted into container)
├── data/                       # DB backups, exports, locust ID dumps (gitignored)
├── locust/                     # Load testing (locustfile.py)
└── dh_abstracts/               # Django project
    ├── manage.py
    ├── .coveragerc             # coverage.py config
    ├── dhweb/                  # Django project package
    │   ├── settings.py
    │   ├── urls.py             # Root URL conf (admin, accounts, filer, sitemaps)
    │   └── wsgi.py
    └── abstracts/              # The single application
        ├── models.py           # Domain models (~1200 lines)
        ├── views.py            # Views (~2765 lines)
        ├── forms.py
        ├── admin.py
        ├── urls.py             # App URL conf (all app routes)
        ├── apps.py
        ├── migrations/         # 77 migrations
        ├── management/commands/  # Data import/export/maintenance scripts
        ├── templatetags/
        ├── tests/              # test_models.py, test_views.py, test_views_autocomplete.py
        ├── static/tei/         # TEI XML test fixtures (valid_tei/, invalid_tei/)
        └── fixtures/test.json
```

## Setup & Running

Everything runs through Docker Compose via the `Makefile`.

1. Copy `.env.template` → `.env` and fill in `POSTGRES_PASSWORD`, `POSTGRES_USER`,
   `POSTGRES_DB`, `DH_SECRET`, and `ALLOWED_HOSTS`.
2. `make` (or `make detached` for background) — builds and starts all services.
3. `make migrate` — apply database migrations.
4. The app is served at `http://localhost` (nginx) or `:8000` directly in dev.

For local dev, `SERVE_COMMAND` defaults to `python manage.py runserver 0.0.0.0:8000`
and `DEBUG_STATUS=True`.

### Environment Variables

Beyond the required `POSTGRES_*`, `DH_SECRET`, and `ALLOWED_HOSTS` vars, the following
are read from `.env`:

- `EMAIL_HOST` — SMTP server hostname. Email sending is not configured by default and will
  fail if this is not set; optional for deployments that do not need email.
- `EMAIL_PORT` — SMTP port, defaults to `25`.
- `EMAIL_ADDRESS` — read by `settings.py` as `DEFAULT_FROM_EMAIL`.
- Port 25 is exposed on the app container for SMTP.

## Common Makefile Targets

| Target          | Action                                                        |
| --------------- | ------------------------------------------------------------- |
| `make`          | `docker-compose up`                                           |
| `make detached` | `docker-compose up -d`                                        |
| `make stop`     | Stop the app container                                        |
| `make down`     | Tear down all containers                                      |
| `make attach`   | `exec bash` into the app container                            |
| `make db`       | Open `psql` into postgres (user `dh`)                          |
| `make restart`  | `docker-compose restart app nginx redis`                  |
| `make migrate`  | Run `manage.py migrate`                                       |
| `make deploy`   | migrate + collectstatic + restart                              |
| `make rebuild`  | Rebuild app & nginx images without cache                      |
| `make wipe`     | Drop & recreate the `dh` database, then migrate (fresh slate) |
| `make blank`    | Drop the `dh` database (internal helper used by `wipe`/`restore`) |
| `make backup`   | `pg_dump` to `data/backup.sql`                               |
| `make restore`  | Restore `data/backup.sql`                                     |
| `make test`     | Run test suite with `--parallel 4` (⚠️ see note below)            |
| `make coverage` | Run tests under coverage, generate HTML report                |
| `make check`    | `manage.py check`                                             |
| `make dumptest` | Dump test fixture to `abstracts/fixtures/test.json`           |
| `make loadtest` | Wipe + load the test fixture                                  |
| `make nightly`  | ⚠️ **Broken** — calls `regenerate_text_indices` + `export_all_csv`, neither of which exists as a management command. The working export command is `export_tables`. |

All `manage.py` commands run inside the `app` container. To run an arbitrary command:

```bash
make attach
# then inside the container:
python manage.py <command>
```

## Testing

- Tests live in `dh_abstracts/abstracts/tests/`.
- Test classes use `fixtures = ["test.json"]` (generated via `make dumptest`).
- `CachelessTestCase` (in `test_views.py`) clears the cache (Redis) before each test —
  use it for view tests that depend on cache state. The cache backend is Django's
  built-in `RedisCache` (redis-py driver).
- Run the full suite: `make test`.
- ⚠️ **Parallel test runner note:** `make test` uses `--parallel 4`. On Python 3.12 with
  lxml 5.x, the `test_invalid_tei` test raises an `lxml.etree.XMLSchemaParseError` whose
  exception object cannot be pickled across process boundaries, causing the parallel
  runner to crash. If this occurs, run `docker-compose exec app python manage.py test`
  (without `--parallel`) instead. The test itself passes when run serially.
- Regenerate the test fixture after model/data changes: `make wipe && make dumptest`.
- Load testing uses Locust (`locust/locustfile.py`); it requires `data/all_ids.json`,
  produced by `python manage.py dump_ids`.
- **Pre-existing test failures:** As of the Django 5.2 upgrade (July 2026), the test suite has
  5 known failures that are **not** caused by the upgrade — they fail identically on the
  old Django 3.2 environment as well. The upgrade to Django 5.2 introduced no new
  failures (verified: 204 tests, same 5 failures before and after).
  - `CreateConferenceViewTest.test_post` — POST to `conference_create` returns a response
    without the expected "created" success message (form validation issue).
  - `EditConferenceViewTest.test_post` — same pattern; expects "updated" message.
  - `CreateOrganizerViewTest.test_post` — same pattern; expects "created" message.
  - `CreateWorkTest.test_post` — same pattern; expects "created" message.
  - `DownloadPageTest.test_render` — `FileNotFoundError: '/vol/data/dh_conferences_works.zip'`;
    the download page view expects a pre-generated zip file that does not exist in the test
    environment.
  
  When these failures are investigated and fixed, **update this section of AGENTS.md** to
  reflect the current test state.

## Domain Model

The core entities (in `abstracts/models.py`) model DH conference abstracts and their
bibliographic relationships:

- **ConferenceSeries** → **Conference** (linked via `SeriesMembership`). Conferences can
  also be standalone events.
- **Conference** has `Organizer`s, hosting `Institution`s, a location, year, theme, and
  URL. Owns the TEI XML import logic (`import_xml_file`, `import_xml_directory`).
- **ConferenceDocument** — files/documents attached to a `Conference`, with `basename`
  and `url` helper methods.
- **Work** — an abstract/paper. Belongs to a `Conference`, has a `WorkType`, `License`,
  keywords, topics, languages, and optional full text (plain text or TEI XML). Can have a
  parent work (for sessions/panels).
- **Author** → **Authorship** → **Work** (many-to-many through `Authorship`).
- **Authorship** has `Affiliation`s → `Institution`. Authors have `Appellation`s (name
  variants) and `Attribute`s (e.g. ORCID), tracked over time.
- **Tag** subclasses: `Keyword`, `Language`, `Topic` — controlled vocabularies attached to
  works.
- **Country** / **CountryLabel** — geographic data with multilingual labels.
- **FileImport** / **FileImportTries** / **FileImportMessgaes** — tracking for bulk XML
  imports (note the historical typo "Messgaes" in the model name; do not "fix" it without
  a migration).

Base classes:
- `ChangeTrackedModel` — adds `last_updated` and `user_last_updated` auto fields.
- `TextIndexedModel` — adds a `search_text` field for Postgres full-text search.

Several models implement `merge()` methods for deduplication (Author, Institution,
Keyword, Topic, etc.). These are invoked from the editor views.

## Key Conventions

- **PostgreSQL is mandatory.** The app uses `django.contrib.postgres` full-text search
  (`SearchVector`, `SearchRank`, `SearchQuery`) and `SearchVectorField`. Do not assume
  SQLite/MySQL compatibility.
- **Caching:** Views are wrapped with `cache_for_anon()` (caches responses for anonymous
  users only). Redis is the cache backend. Be aware of cache invalidation when
  modifying data through editor views.
- **TEI XML namespace:** `http://www.tei-c.org/ns/1.0`. XML files are validated against
  a TEI schema during import (see `import_xml_file`).
- **Autocomplete:** django-autocomplete-light (`dal`) is used extensively. Autocomplete
  views are defined in `views.py` and routed in `urls.py` (e.g. `author-autocomplete`,
  `keyword-autocomplete`). Forms use `ModelSelect2` / `ModelSelect2Multiple`.
- **Authentication / staff access:** `LoginRequiredMiddleware` enforces login site-wide
  (anonymous users hitting a protected view are redirected to `LOGIN_URL` with `?next=…`).
  Publicly readable views are exempted via `cache_for_anon` (it sets `login_required = False`
  using `functools.wraps`) or, for the few not cache-wrapped, an explicit `@login_not_required`
  (public downloads, sitemaps, flatpages). Staff-only editor views use the
  `UserPassesTestMixin`-based `StaffRequiredMixin` (CBVs) or the `@user_is_staff` decorator
  (merge FBVs); both redirect authenticated non-staff users to `home_view` with the
  `PERMISSIONS_ERROR_TEXT` warning. `XMLView` keeps its own `LoginRequiredMixin` so work XML
  stays login-gated.
- **Static assets:** SCSS compiled via django-compressor + libsass. Run
  `collectstatic` on deploy (`make deploy` handles this).
- **`DEFAULT_AUTO_FIELD`** is `BigAutoField` (with explicit `id = models.BigAutoField(primary_key=True)`
  on each concrete model). New models inherit this unless a migration explicitly changes it.
- **Time zone:** `America/New_York`.
- **Code style:** Format and lint with `ruff`. Line length is 88 (ruff formatter is
  black-compatible). ruff is a dev dependency excluded from the Docker image via
  `uv sync --no-dev`. Run it on the **host** via `uv run ruff format .` /
  `uv run ruff check .` (or `make format` / `make lint`) after running `uv sync`
  locally (without `--no-dev`). Do NOT run these inside the Docker container. A
  pre-commit hook (`.pre-commit-config.yaml`) enforces both formatting and linting on
  commit; run `pre-commit install` once after cloning.
- **Debug toolbar:** `django-debug-toolbar` is wired into `INSTALLED_APPS`,
  `MIDDLEWARE`, and routed at `__debug__/` (visible only when `DEBUG=True`).
- **Django contrib apps in use** (beyond the standard admin/auth/sessions/contenttypes/
  messages/staticfiles):
  - `django.contrib.flatpages` — routed at `/pages/`
  - `django.contrib.sites` (`SITE_ID = 1`)
  - `django.contrib.redirects` (via `RedirectFallbackMiddleware`)
  - `django.contrib.sitemaps` — full sitemap config in `dhweb/urls.py` (`/sitemap.xml`
    with sections: series, work, author, flatpages, core views)
  - `django.contrib.humanize`
  - `django.contrib.postgres` (see PostgreSQL note above)
- **Other config:** `LOGIN_URL = "/accounts/login"` (login URL for staff-gated editor
  routes). `DATA_OUTPUT_PATH = "/vol/data"` (in-container path where CSV exports are
  written).

## Type Checking

The project uses **mypy + django-stubs** for static type checking. Like `ruff`, these are
**dev-only dependencies** (in the `[dependency-groups] dev` table in `pyproject.toml`),
excluded from the Docker image via `uv sync --no-dev`, and run on the **host** via
`uv run mypy`.

The django-stubs mypy plugin bootstraps the Django app at type-check time, synthesizing
types for model fields, reverse relations, queryset generics, and Meta classes. This means
useful ORM type checking without manually annotating every model relationship.

**How to run:**

- `make typecheck` — runs mypy and prints errors to stdout.
- `make typecheck-baseline` — runs mypy and writes output to `data/mypy_baseline.txt`
  (the `data/` directory is gitignored).
- Direct: `cd dh_abstracts && POSTGRES_DB=dh POSTGRES_USER=dh POSTGRES_PASSWORD=dummy DH_SECRET=dummy uv run mypy . --exclude abstracts/migrations/`

**Why dummy env vars are required:** The django-stubs plugin imports `dhweb.settings` at
type-check time. That module reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` from
`os.environ` with no defaults (KeyError if unset), crashing mypy before it can produce any
output. The Makefile targets and pre-commit hook bake in dummy values to prevent this.

**Config location:** `[tool.mypy]` and `[tool.django-stubs]` in `pyproject.toml`.

**Exclusions (and why):**
- **Migrations** (`[[tool.mypy.overrides]] module = "*.migrations.*"`): Auto-generated
  migrations reference models that may no longer exist and use string-based field
  references; they don't type-check and shouldn't. Also excluded via `--exclude
  abstracts/migrations/` on the command line.
- **settings.py** (`module = "dhweb.settings"`): Reads `os.environ` with no defaults for
  required vars; generates type-check noise that isn't actionable. Note: this override
  suppresses type errors but does NOT prevent the `KeyError` at import time — that's why
  dummy env vars are still needed.

**`django-stubs-ext` monkeypatch:** `dhweb/settings.py` contains a guarded
`django_stubs_ext.monkeypatch()` call (wrapped in `try/except ImportError`) that patches
Django's generic types (`QuerySet`, `Manager`, etc.) to support subscripting at runtime
(e.g. `QuerySet[Work]`). The guard makes it a no-op in production (where django-stubs-ext
is not installed). This does not change existing runtime behavior.

**Current status:** `strict = false` — the type check passes with **0 errors** across 30
source files. M2M `through=` references in `models.py` use app-qualified strings
(e.g. `"abstracts.Authorship"`) so the django-stubs plugin can resolve them; third-party
packages without stubs (`filer`, `dal`, `debug_toolbar`) are suppressed via
`ignore_missing_imports` overrides in `pyproject.toml`.

**Pre-commit hook:** The mypy hook in `.pre-commit-config.yaml` is in `stages: [manual]`
— it only runs when explicitly invoked (`pre-commit run mypy`), not on every commit.
Since the type check now passes with zero errors, the hook can be moved to the commit
stage in a future change.

**Makefile targets:**

| Target | Action |
| --- | --- |
| `make typecheck` | Run mypy, print errors to stdout |
| `make typecheck-baseline` | Run mypy, write output to `data/mypy_baseline.txt` |

**Future work:**
- Gradual annotation of existing code (models, views, forms, management commands)
- Tightening mypy strictness flags (`disallow_untyped_defs`, `no_implicit_optional`, etc.)
- Moving the pre-commit hook from manual to commit stage
- Setting up pyright for editor-time feedback (optional)

## Dependency Management

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

- **Declaration:** Direct dependencies are declared in `pyproject.toml` using
  the PEP 621 `[project]` table. Dev dependencies (`ruff`) are in the
  `[dependency-groups] dev` table.
- **Lockfile:** `uv.lock` is the single source of truth for resolved versions.
  Regenerate after changing `pyproject.toml` with `uv lock` (run from repo root).
- **Adding a dependency:** `uv add <package>` (updates `pyproject.toml` and `uv.lock`).
  For a dev dependency: `uv add --dev <package>`.
- **Docker install:** The Dockerfile runs `uv sync --frozen --no-dev` from `uv.lock`.
  `--frozen` refuses to update the lockfile; `--no-dev` excludes `ruff` from the
  image. The venv is placed at `/opt/venv` (outside the dev volume mount) and added to
  `PATH`, so `python` and `gunicorn` resolve to it transparently.
- **Local dev sync:** Run `uv sync` (without `--no-dev`) on the host to install all deps
  including dev tools, then use `uv run ruff format .` / `uv run ruff check .` to run them.

## Management Commands

Located in `abstracts/management/commands/`. Run via
`docker-compose exec app python manage.py <command>`.

| Command              | Purpose                                                        |
| -------------------- | -------------------------------------------------------------- |
| `import_dh_xml`      | Load a directory of TEI XML files into a conference (`--conference <pk>`) |
| `import_conferences` | One-time load of DH conferences from a spreadsheet              |
| `import_2016`        | One-time load of DH 2016 full text                             |
| `import_2020`        | One-time load of DH 2020 data                                  |
| `import_2020_topics` | One-time load of DH 2020 topic vocabulary                      |
| `ia_load`            | Load data from Internet Archive (with exponential backoff)    |
| `export_tables`      | Export all models to zipped CSVs (public & private configs)    |
| `dump_ids`           | Export entity IDs to `data/all_ids.json` for Locust testing    |
| `clean_hanging`      | Delete orphaned records (authors, affiliations, etc. with no FK) |
| `refresh_labels`     | Re-save all authors to refresh appellation autocomplete index |
| `lowercase_topics`   | Normalize topic labels to lowercase                           |
| `lowercase_keywords` | Normalize keyword labels to lowercase                         |

## Data Export

The app produces two flavors of CSV exports (configured in `settings.py`):

- `PUBLIC_DATA_TABLE_CONFIG` — censors works without a public license; zipped as
  `dh_conferences_tables.zip`.
- `PRIVATE_DATA_TABLE_CONFIG` — includes all works; zipped as
  `private_dh_conferences_tables.zip`.

A denormalized "works" CSV (`dh_conferences_works.csv`) is also available, with column
definitions in `DENORMALIZED_HEADERS`.

## Future Django 5.2 Feature Adoption

The following opportunities for adopting newer Django features remain **not** implemented yet
and would each require careful design, testing, and potentially migrations.

1. **`STORAGES` setting (Django 4.2+)**: The `FILER_STORAGES` dict (`settings.py`) and the
   implicit default static/file storage backends could be consolidated into Django 4.2+'s
   unified `STORAGES` setting, which provides a cleaner configuration interface and supports
   multiple named storage backends.

2. **`Model.choices` with Python `enum` (Django 5.0+)**: Model fields using choices tuples
   (e.g., `WorkType`, `License`) could be refactored to use `enum` classes with
   `models.Field.choices`, providing better type safety and IDE support.

3. **Async views and ORM (Django 3.1+ / 4.2+)**: Views that perform I/O-bound work (e.g.,
   the TEI XML import, CSV export, Internet Archive loading in `ia_load.py`) could be
   converted to async views using `async def` and async ORM methods (`adelete()`,
   `acreate()`, `aget()`). This would improve throughput for concurrent requests during
   long-running operations.

4. **Fix `make nightly`**: The broken `make nightly` target (calling nonexistent
   `regenerate_text_indices` and `export_all_csv`) could be fixed to use the actual
   `export_tables` command. With `GeneratedField` adoption, the text index regeneration
   would become automatic, potentially eliminating the need for a nightly regeneration
   command entirely.

5. **Fix email env var mismatch**: The `EMAIL_ADDRESS` vs `DEFAULT_FROM_EMAIL` mismatch
   in `.env.template` and the missing `=` on `EMAIL_PORT` are pre-existing issues that
   could be addressed alongside the settings.py changes.

## Things to Watch Out For

- **Migrations are committed and historical.** There are 78 migrations including merge
  migrations. Never squash or renumber existing migrations. New migrations should continue
  the numbering sequence. Migration 0077 is a state-only migration generated during the
  Django 5.2 upgrade — it syncs field serialization (lowercase model names in `to=`
  references) with Django 5.2's representation; no database schema changes. Migration 0078
  (the PostgreSQL 18 / auto-field modernization) carries the generated `search_text`
  column, the `BigAutoField` PK+FK conversions, and the `db_default` additions.
- **The `FileImportMessgaes` model name has a typo** (should be "Messages"). Renaming it
  requires a migration and updates across models, admin, views, and tests. Leave it unless
  explicitly tasked to fix it.
- **Editor views require staff login.** The `StaffRequiredMixin` and `user_is_staff`
  decorator gate all `/editor/` routes. Anonymous users get cached read-only views.
- **`make wipe` destroys all data.** Only use it on dev databases. Always `make backup`
  first on any database you care about.
- **Environment variables are required at runtime.** `settings.py` reads
  `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` directly from `os.environ` (no
  defaults) — the app will not start without a valid `.env`.
- **`make nightly` is currently broken.** It calls `regenerate_text_indices` and
  `export_all_csv`, neither of which exists as a management command. The working export
  command is `export_tables`. This is a known issue, not yet fixed.
- **Email env var mismatch.** `settings.py` reads `os.environ.get("EMAIL_ADDRESS")` for
  `DEFAULT_FROM_EMAIL`, but `.env.template` provides `DEFAULT_FROM_EMAIL=` (mismatched
  name). Additionally, `.env.template` has `EMAIL_PORT` with no `=` sign (invalid
  assignment). Email sending will not work until these are aligned. This is a known
  issue, not yet fixed.
