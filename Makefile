.PHONY: lint lint-fix test-backend test-node test docker-build docker-up docker-down clean backup migrate-passwords

# ── Linting ─────────────────────────────────────────────────────────
lint:
	cd backend && ruff check .
	npx eslint src/ tests/

lint-fix:
	cd backend && ruff check --fix .
	cd backend && ruff format .

# ── Testing ─────────────────────────────────────────────────────────
test-backend:
	cd backend && pytest

test-node:
	npm test

test: test-backend test-node

# ── Docker ──────────────────────────────────────────────────────────
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

# ── Database Ops ─────────────────────────────────────────────────────
backup:
	bash scripts/backup-postgres.sh

migrate-passwords:
	docker compose --env-file .env.docker.local exec app python scripts/migrate-password-hashes.py

# ── Cleanup ─────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf node_modules/.cache
