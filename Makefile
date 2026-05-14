.PHONY: test run pipeline init-db

test:
	PYTHONPATH=. pytest -q

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

init-db:
	python -m pipelines.init_db

pipeline:
	python -m pipelines.run_pipeline
