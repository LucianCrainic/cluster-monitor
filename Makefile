SHELL := /bin/bash

UV ?= uv
NPM ?= npm

.PHONY: help install backend frontend dev generate-api test lint typecheck build

help:
	@echo "cluster-monitor developer commands"
	@echo "  make install      Install backend and frontend dependencies"
	@echo "  make backend      Start FastAPI on 127.0.0.1:8000"
	@echo "  make frontend     Start Vite on 127.0.0.1:5173"
	@echo "  make dev          Start both development servers"
	@echo "  make generate-api  Refresh OpenAPI and generated frontend types"
	@echo "  make test         Run backend and frontend tests"
	@echo "  make lint         Run Ruff and ESLint"
	@echo "  make typecheck    Run mypy and TypeScript checks"
	@echo "  make build        Build the frontend"

install:
	@command -v "$(UV)" >/dev/null || { echo "error: uv is required (https://docs.astral.sh/uv/)" >&2; exit 127; }
	@command -v "$(NPM)" >/dev/null || { echo "error: npm is required (install Node.js LTS)" >&2; exit 127; }
	cd backend && "$(UV)" sync --extra dev
	@if [[ -f frontend/package-lock.json ]]; then \
		"$(NPM)" --prefix frontend ci; \
	else \
		"$(NPM)" --prefix frontend install; \
	fi

backend:
	./scripts/backend.sh

frontend:
	./scripts/frontend.sh

dev:
	./scripts/dev.sh

generate-api:
	cd backend && "$(UV)" run --extra dev python scripts/export_openapi.py
	cd backend && "$(UV)" run --extra dev python scripts/generate_typescript.py \
		openapi.json ../frontend/src/types/api.generated.ts

test:
	cd backend && "$(UV)" run --extra dev pytest
	"$(NPM)" --prefix frontend run test

lint:
	cd backend && "$(UV)" run --extra dev ruff check .
	cd backend && "$(UV)" run --extra dev ruff format --check .
	"$(NPM)" --prefix frontend run lint

typecheck:
	cd backend && "$(UV)" run --extra dev mypy src tests scripts
	"$(NPM)" --prefix frontend run typecheck

build:
	"$(NPM)" --prefix frontend run build
