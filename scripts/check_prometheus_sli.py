from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


PROMETHEUS_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9090"
OUTPUT_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("artifacts/prometheus-sli.json")

QUERIES = {
    "api_error_rate": '(sum(rate(http_request_errors_total{service="marketplace-api"}[1m])) or vector(0)) / clamp_min(sum(rate(http_requests_total{service="marketplace-api"}[1m])), 0.001)',
    "api_latency_p95_seconds": 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="marketplace-api"}[1m])) by (le))',
    "api_availability": '1 - ((sum(rate(http_request_errors_total{service="marketplace-api"}[1m])) or vector(0)) / clamp_min(sum(rate(http_requests_total{service="marketplace-api"}[1m])), 0.001))',
}

THRESHOLDS = {
    "api_error_rate": ("<", 0.01),
    "api_latency_p95_seconds": ("<", 0.5),
    "api_availability": (">", 0.995),
}


def query_prometheus(expr: str) -> float:
    encoded = urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(f"{PROMETHEUS_URL}/api/v1/query?{encoded}", timeout=10) as response:
        payload = json.loads(response.read())
    if payload["status"] != "success":
        raise RuntimeError(payload)
    result = payload["data"]["result"]
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def passes(value: float, operator: str, threshold: float) -> bool:
    if operator == "<":
        return value < threshold
    if operator == ">":
        return value > threshold
    raise ValueError(operator)


def main() -> None:
    time.sleep(10)
    results = {}
    failed = []
    for name, query in QUERIES.items():
        value = query_prometheus(query)
        operator, threshold = THRESHOLDS[name]
        ok = passes(value, operator, threshold)
        results[name] = {
            "value": value,
            "query": query,
            "threshold": f"{operator} {threshold}",
            "ok": ok,
        }
        if not ok:
            failed.append(name)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    if failed:
        raise SystemExit(f"SLI check failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
