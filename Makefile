.PHONY: test lint run pipeline dashboard init-db format typecheck check clean

# Install dependencies
install:
	pip install -e ".[dev]"

# Run tests with coverage
test:
	PYTHONPATH=. pytest --cov=app --cov=connectors --cov=pipelines --cov-report=term-missing -v tests/

# Run only unit tests
test-unit:
	PYTHONPATH=. pytest -v tests/unit/

# Run only integration tests
test-integration:
	PYTHONPATH=. pytest -v tests/integration/

# Lint with ruff
lint:
	ruff check . && echo "Lint OK"

# Format with ruff
format:
	ruff format . && echo "Format OK"

# Type check with mypy
typecheck:
	PYTHONPATH=. mypy app/ connectors/ pipelines/

# Run all checks
check: lint typecheck test
	@echo "All checks passed!"

# Start FastAPI dev server
run:
	uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

# Start Streamlit dashboard
dashboard:
	streamlit run dashboard/main.py --server.port 8501

# Initialize database schema (Alembic)
init-db:
	alembic upgrade head

# Run full pipeline
pipeline:
	PYTHONPATH=. python -m pipelines.run_all

# Clean build artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
