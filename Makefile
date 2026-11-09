.PHONY: help install test test-eval eval-gate calibrate lint format build docker-up docker-down docker-logs migrate clean

SHELL := /bin/bash
PYTHON := ./.venv/bin/python
PYTEST := ./.venv/bin/pytest

help:
	@echo "======================================================================"
	@echo "                   कथा Studio Engineering CLI                        "
	@echo "======================================================================"
	@echo "make install       Install backend (pip/poetry) and frontend (npm) dependencies"
	@echo "make test          Run full backend test suite (49+ unit & integration tests)"
	@echo "make test-eval     Run Phase 5 evaluation & observability tests"
	@echo "make eval-gate     Execute production CI evaluation quality & cost gate"
	@echo "make calibrate     Run LLM Judge calibration against 30 ground-truth scripts"
	@echo "make lint          Run TypeScript compiler and Python linters"
	@echo "make build         Run production frontend Vite build"
	@echo "make migrate       Execute Alembic database migrations"
	@echo "make docker-up     Start complete Docker Compose stack (App + PG + Redis)"
	@echo "make docker-down   Stop and tear down Docker Compose containers"
	@echo "make docker-logs   Stream container logs"
	@echo "make clean         Remove build artifacts and temporary cache files"
	@echo "======================================================================"

install:
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Installing backend dependencies..."
	pip install -r backend/requirements.txt || poetry install --directory backend

test:
	@echo "Running all backend unit and integration tests..."
	PYTHONPATH=backend $(PYTEST) backend/tests -v

test-eval:
	@echo "Running evaluation tests..."
	PYTHONPATH=backend $(PYTEST) backend/tests/test_evaluation.py -v

eval-gate:
	@echo "Running CI Evaluation Quality & Cost Gate..."
	PYTHONPATH=backend $(PYTHON) backend/scripts/eval_gate.py --samples 5

calibrate:
	@echo "Running LLM Judge Calibration Analysis..."
	PYTHONPATH=backend $(PYTHON) -c "import asyncio; from app.services.evaluator import evaluator_service; r = asyncio.run(evaluator_service.run_calibration()); print('Status:', r.calibration_status); print('Spearman Rho:', r.spearman_correlation); print('Weighted Kappa:', r.weighted_cohens_kappa); print('MAE:', r.mean_absolute_error)"

lint:
	@echo "Running TypeScript typecheck..."
	cd frontend && npm run build
	@echo "Running Python syntax & import checks..."
	PYTHONPATH=backend $(PYTHON) -m py_compile backend/app/main.py

build:
	@echo "Building production frontend assets..."
	cd frontend && npm run build

migrate:
	@echo "Running database migrations..."
	cd backend && alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf frontend/dist

