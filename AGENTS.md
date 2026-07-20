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
| Python         | 3.9.13    | Pinned in `dh_abstracts/Dockerfile`; deps managed by uv          |
| Django         | 3.2.14    | LTS release                                                      |
| PostgreSQL     | 12.11     | **Required** — uses `contrib.postgres` full-text search fields  |
| Memcached      | 1.6.15    | Cache backend, 10-minute default timeout                         |
| nginx          | 1.22.0    | Reverse proxy + static file serving                             |
| gunicorn       | 20.1.0    | Production WSGI server (via `SERVE_COMMAND` env var)             |

Key Python dependencies (declared in `dh_abstracts/pyproject.toml`, locked in `dh_abstracts/uv.lock`):

- `django-autocomplete-light` (dal) — autocomplete widgets throughout forms/views
- `django-crispy-forms` (bootstrap4 template pack) — form rendering
- `django-filer` — file/media management
- `django-compressor` + `django-libsass` — SCSS compilation, static asset bundling
- `django-markdownify` — markdown rendering (bleach-whitelisted)
- `django-mptt`, `django-polymorphic` — tree structures, polymorphic models
- `lxml` — TEI XML parsing and validation
- `psycopg2-binary` — PostgreSQL driver
- `easy-thumbnails` — image thumbnails

Dev tooling: `black` (formatting), `flake8` (linting), `coverage` + `django-coverage-plugin`.
Note that `black` and `flake8` are in `[dependency-groups] dev` in `pyproject.toml` and
are excluded from the Docker image via `uv sync --no-dev` — they are not installed inside
the Docker container and must be run on the host or a separate dev environment. `coverage`
and `django-coverage-plugin` are in `pyproject.toml` dependencies and available in-container.

## Repository Layout

```
.
├── docker-compose.yml          # Orchestrates postgres, app, memcached, nginx
├── Makefile                    # All common dev/deploy operations
├── .env.template               # Copy to .env and fill in secrets
├── nginx/                      # nginx conf.d templates (mounted into container)
├── data/                       # DB backups, exports, locust ID dumps (gitignored)
├── locust/                     # Load testing (locustfile.py)
└── dh_abstracts/               # Django project
    ├── Dockerfile
    ├── uv.lock                # Locked dependency manifest (uv)
    ├── pyproject.toml         # PEP 621 dependency spec (uv)
    └── app/                    # Django project root (manage.py lives here)
        ├── manage.py
        ├── dhweb/              # Django project package
        │   ├── settings.py
        │   ├── urls.py         # Root URL conf (admin, accounts, filer, sitemaps)
        │   └── wsgi.py
        └── abstracts/          # The single application
            ├── models.py       # Domain models (~1200 lines)
            ├── views.py        # Views (~2765 lines)
            ├── forms.py
            ├── admin.py
            ├── urls.py         # App URL conf (all app routes)
            ├── apps.py
            ├── migrations/     # 76 migrations
            ├── management/commands/  # Data import/export/maintenance scripts
            ├── templatetags/
            ├── tests/          # test_models.py, test_views.py, test_views_autocomplete.py
            ├── static/tei/     # TEI XML test fixtures (valid_tei/, invalid_tei/)
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

- `MEMCACHED_COMMAND` — memcached launch command, defaults to `memcached -m 1024` (used in
  `docker-compose.yml`).
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
| `make restart`  | `docker-compose restart app nginx memcached`                  |
| `make migrate`  | Run `manage.py migrate`                                       |
| `make deploy`   | migrate + collectstatic + restart                              |
| `make rebuild`  | Rebuild app & nginx images without cache                      |
| `make wipe`     | Drop & recreate the `dh` database, then migrate (fresh slate) |
| `make blank`    | Drop the `dh` database (internal helper used by `wipe`/`restore`) |
| `make backup`   | `pg_dump` to `data/backup.sql`                               |
| `make restore`  | Restore `data/backup.sql`                                     |
| `make test`     | Run test suite with `--parallel 4`                            |
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

- Tests live in `dh_abstracts/app/abstracts/tests/`.
- Test classes use `fixtures = ["test.json"]` (generated via `make dumptest`).
- `CachelessTestCase` (in `test_views.py`) clears memcached before each test — use it
  for view tests that depend on cache state.
- Run the full suite: `make test`.
- Regenerate the test fixture after model/data changes: `make wipe && make dumptest`.
- Load testing uses Locust (`locust/locustfile.py`); it requires `data/all_ids.json`,
  produced by `python manage.py dump_ids`.
- **Pre-existing test failures:** As of the uv migration (July 2026), the test suite has
  5 known failures that are **not** caused by the migration — they fail identically on the
  old `requirements.txt`-based environment as well:
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
  users only). Memcached is the cache backend. Be aware of cache invalidation when
  modifying data through editor views.
- **TEI XML namespace:** `http://www.tei-c.org/ns/1.0`. XML files are validated against
  a TEI schema during import (see `import_xml_file`).
- **Autocomplete:** django-autocomplete-light (`dal`) is used extensively. Autocomplete
  views are defined in `views.py` and routed in `urls.py` (e.g. `author-autocomplete`,
  `keyword-autocomplete`). Forms use `ModelSelect2` / `ModelSelect2Multiple`.
- **Static assets:** SCSS compiled via django-compressor + libsass. Run
  `collectstatic` on deploy (`make deploy` handles this).
- **`DEFAULT_AUTO_FIELD`** is `AutoField` (not `BigAutoField`). New models should follow
  this unless a migration explicitly changes it.
- **Time zone:** `America/New_York`.
- **Code style:** Format with `black` (default line length 88). Lint with `flake8`.
  black and flake8 are dev dependencies excluded from the Docker image via `uv sync --no-dev`.
  Run them on the **host** via `uv run black .` / `uv run flake8 .` after running `uv sync`
  locally (without `--no-dev`). Do NOT run these inside the Docker container.
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

## Dependency Management

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

- **Declaration:** Direct dependencies are declared in `dh_abstracts/pyproject.toml` using
  the PEP 621 `[project]` table. Dev dependencies (`black`, `flake8`) are in the
  `[dependency-groups] dev` table.
- **Lockfile:** `dh_abstracts/uv.lock` is the single source of truth for resolved versions.
  Regenerate after changing `pyproject.toml` with `uv lock` (run from `dh_abstracts/`).
- **Adding a dependency:** `uv add <package>` (updates `pyproject.toml` and `uv.lock`).
  For a dev dependency: `uv add --dev <package>`.
- **Docker install:** The Dockerfile runs `uv sync --frozen --no-dev` from `uv.lock`.
  `--frozen` refuses to update the lockfile; `--no-dev` excludes `black`/`flake8` from the
  image. The venv is placed at `/opt/venv` (outside the dev volume mount) and added to
  `PATH`, so `python` and `gunicorn` resolve to it transparently.
- **Local dev sync:** Run `uv sync` (without `--no-dev`) on the host to install all deps
  including dev tools, then use `uv run black .` / `uv run flake8 .` to run them.

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

## Things to Watch Out For

- **Migrations are committed and historical.** There are 76 migrations including merge
  migrations. Never squash or renumber existing migrations. New migrations should continue
  the numbering sequence.
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
