.PHONY: test run pipeline

test:
	PYTHONPATH=. pytest -q

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

pipeline:
	python -m pipelines.run_pipeline
