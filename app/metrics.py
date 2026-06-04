from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ("service", "method", "endpoint", "status"),
)
REQUEST_ERRORS_TOTAL = Counter(
    "http_request_errors_total",
    "Total HTTP request errors.",
    ("service", "method", "endpoint", "error_type"),
)
REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("service", "method", "endpoint"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


def install_metrics(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def prometheus_metrics(request: Request, call_next):
        started_at = time.perf_counter()
        status_code = 500
        endpoint = request.url.path
        try:
            response = await call_next(request)
            status_code = response.status_code
            endpoint = endpoint_label(request)
            return response
        except Exception as exc:
            endpoint = endpoint_label(request)
            REQUEST_ERRORS_TOTAL.labels(service_name, request.method, endpoint, type(exc).__name__).inc()
            raise
        finally:
            elapsed = time.perf_counter() - started_at
            status = str(status_code)
            REQUESTS_TOTAL.labels(service_name, request.method, endpoint, status).inc()
            REQUEST_DURATION_SECONDS.labels(service_name, request.method, endpoint).observe(elapsed)
            if status_code >= 400:
                REQUEST_ERRORS_TOTAL.labels(service_name, request.method, endpoint, status).inc()

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
