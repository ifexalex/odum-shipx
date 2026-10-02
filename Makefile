.PHONY: install lint check test test-unit test-integration test-isolation test-all migrate seed deploy clean security-scan \
        up down bootstrap dev e2e

# ─── Local stack ─────────────────────────────────────────────────────────────

# Start Docker containers (Postgres + Moto + Redis + Adminer)
up:
	docker compose -f docker-compose.local.yml up -d
	@echo "Waiting for containers to be healthy..."
	@until docker compose -f docker-compose.local.yml ps | grep -E "shipx_postgres.*healthy" > /dev/null 2>&1; do sleep 1; done
	@until docker compose -f docker-compose.local.yml ps | grep -E "shipx_moto.*healthy" > /dev/null 2>&1; do sleep 1; done
	@until docker compose -f docker-compose.local.yml ps | grep -E "shipx_redis.*healthy" > /dev/null 2>&1; do sleep 1; done
	@echo "All containers ready."

# Stop Docker containers
down:
	docker compose -f docker-compose.local.yml down

# Create SQS queues, EventBridge bus, S3 bucket in Moto
bootstrap:
	bash scripts/bootstrap_local.sh

# Start the local Flask API server (loads .env.local automatically)
dev:
	@lsof -ti :3000 | xargs kill -9 2>/dev/null || true
	set -a; source .env.local; set +a; PYTHONPATH=. python3 scripts/local_server.py

# Full first-time setup: start containers + bootstrap + migrate + seed + start server
# Usage: make stack
stack: up bootstrap
	@echo "==> Resetting database..."
	set -a; source .env.local; set +a && PYTHONPATH=. python3 scripts/reset_db.py
	set -a; source .env.local; set +a && PYTHONPATH=. python3 scripts/migrate.py && PYTHONPATH=. python3 scripts/seed.py
	@echo ""
	@echo "Stack is ready. Run 'make dev' to start the API server on http://localhost:3000"
	@echo ""

# ─── Application ─────────────────────────────────────────────────────────────

install:
	pip install -r requirements-dev.txt

lint:
	ruff check .
	mypy shared/ services/ --ignore-missing-imports

security-scan:
	bandit -r services/ shared/ -ll -q
	safety check -r requirements.txt

test: test-unit

test-unit:
	PYTHONPATH=.:services pytest tests/unit/ -v --cov=services --cov=shared --cov-report=term-missing

test-integration:
	PYTHONPATH=.:services pytest tests/integration/ -v -m integration

test-isolation:
	PYTHONPATH=.:services pytest tests/tenant_isolation/ -v -m isolation

test-all:
	PYTHONPATH=.:services pytest tests/ -v --cov=services --cov=shared --cov-report=xml

# Run lint + type-check + unit tests in one shot
check:
	ruff check .
	mypy shared/ services/ --ignore-missing-imports
	PYTHONPATH=.:services pytest tests/unit/ -v --cov=services --cov=shared --cov-report=term-missing

# Run end-to-end API tests against the local server.
# REQUIRES: 'make dev' running in another terminal first.
# Usage: make e2e
#        make e2e ARGS="--stop-on-fail --output results.json"
e2e:
	@echo "Tip: ensure 'make dev' is running in another terminal."
	python3 scripts/e2e_test.py $(ARGS)

migrate:
	python scripts/migrate.py

seed:
	python scripts/seed.py

# Adds ~200 containers / ~50 customers to Acme Shipping Ltd for volume/UI
# testing. Additive — run after `make seed` (or `make stack`).
seed-stress:
	python scripts/seed_stress.py

package-layer:
	mkdir -p build/layer/python
	pip install -r requirements-layer.txt -t build/layer/python --platform manylinux2014_aarch64 --only-binary=:all:
	cp -r shared/ build/layer/python/shared/
	cd build/layer && zip -r ../shared-layer.zip python/

clean:
	rm -rf build/ dist/ *.egg-info __pycache__ .pytest_cache .mypy_cache .ruff_cache
