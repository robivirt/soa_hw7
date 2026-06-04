.PHONY: generate run unit integration e2e load sli
PYTHON ?= python3

generate:
	$(PYTHON) scripts/generate_openapi_server.py

run: generate
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

unit:
	pytest tests/unit -q

integration:
	pytest tests/integration -q

e2e:
	pytest tests/e2e -q

load:
	docker compose run --rm k6

sli:
	$(PYTHON) scripts/check_prometheus_sli.py
