.PHONY: generate run
PYTHON ?= python3

generate:
	$(PYTHON) scripts/generate_openapi_server.py

run: generate
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
