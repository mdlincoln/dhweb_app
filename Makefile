COMPOSE_DEV := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml
PY := cd dh_abstracts && uv run --env-file ../.env
# GNU Make does not read .env files. `docker compose` reads .env itself for the
# compose services, but the raw `psql`/`pg_dump` exec targets need the values in
# Make. Read them via a minimal inline parser (avoids `include .env`, which would
# mis-handle the quoted SERVE_COMMAND='...' value).
POSTGRES_USER := $(shell grep -E '^POSTGRES_USER=' .env | head -1 | cut -d= -f2-)
POSTGRES_DB := $(shell grep -E '^POSTGRES_DB=' .env | head -1 | cut -d= -f2-)

all:
	$(COMPOSE_DEV) up -d postgres
infra: all
detached:
	$(COMPOSE_DEV) up -d postgres
local: all
	$(PY) python manage.py runserver 0.0.0.0:8000
stop:
	$(COMPOSE_PROD) stop app nginx
down:
	$(COMPOSE_DEV) down
attach:
	$(COMPOSE_PROD) exec app bash
db: infra
	$(COMPOSE_DEV) exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
restart:
	$(COMPOSE_PROD) restart app nginx
migrate: infra
	$(PY) python manage.py migrate
	$(PY) python manage.py createcachetable
deploy:
	$(COMPOSE_PROD) exec app python manage.py migrate
	$(COMPOSE_PROD) exec app python manage.py createcachetable
	$(COMPOSE_PROD) exec app python manage.py collectstatic --no-input
	$(MAKE) restart
rebuild:
	$(COMPOSE_PROD) build --no-cache app nginx
blank: infra
	$(COMPOSE_DEV) exec postgres psql -U $(POSTGRES_USER) -d postgres -c 'DROP DATABASE IF EXISTS $(POSTGRES_DB);'
wipe: blank
	$(COMPOSE_DEV) exec postgres psql -U $(POSTGRES_USER) -d postgres -c 'CREATE DATABASE $(POSTGRES_DB);'
	$(MAKE) migrate
backup: infra
	mkdir -p data
	$(COMPOSE_DEV) exec postgres pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) > data/backup.sql
restore: blank
	$(COMPOSE_DEV) up -d postgres
	mkdir -p data
	$(COMPOSE_DEV) exec postgres psql -U $(POSTGRES_USER) -d postgres -c 'CREATE DATABASE $(POSTGRES_DB);'
	$(COMPOSE_DEV) exec -T postgres psql -U $(POSTGRES_USER) $(POSTGRES_DB) < data/backup.sql
dumptest: infra
	$(PY) python manage.py dumpdata --indent 2 -e admin.logentry -e auth.permission -e contenttypes -e sessions -o abstracts/fixtures/test.json
loadtest: wipe
	$(PY) python manage.py loaddata abstracts/fixtures/test.json
test: infra
	$(PY) python manage.py test --parallel 4
test-serial: infra
	$(PY) python manage.py test
coverage: infra
	-$(PY) coverage run manage.py test
	$(PY) coverage html
nightly: infra
	$(PY) python manage.py export_tables
check:
	$(PY) python manage.py check
lint:
	uv run ruff check .
format:
	uv run ruff format .
typecheck:
	cd dh_abstracts && POSTGRES_DB=dh POSTGRES_USER=dh POSTGRES_PASSWORD=dummy DH_SECRET=dummy uv run mypy . --exclude abstracts/migrations/
typecheck-baseline:
	cd dh_abstracts && POSTGRES_DB=dh POSTGRES_USER=dh POSTGRES_PASSWORD=dummy DH_SECRET=dummy uv run mypy . --exclude abstracts/migrations/ > ../data/mypy_baseline.txt