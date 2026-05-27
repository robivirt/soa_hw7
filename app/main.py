from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request

from app.errors import add_error_handlers


GENERATED_SRC = Path(__file__).resolve().parent / "generated" / "openapi" / "src"
if GENERATED_SRC.exists() and str(GENERATED_SRC) not in sys.path:
    sys.path.insert(0, str(GENERATED_SRC))

from generated_server.apis.auth_api import router as AuthApiRouter
from generated_server.apis.orders_api import router as OrdersApiRouter
from generated_server.apis.products_api import router as ProductsApiRouter
from generated_server.apis.promo_codes_api import router as PromoCodesApiRouter


app = FastAPI(title="Marketplace API", version="1.0.0")
add_error_handlers(app)


def load_openapi() -> dict[str, Any]:
    spec_path = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
    return yaml.safe_load(spec_path.read_text())


app.openapi = load_openapi


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if "password" in key.lower() else mask_sensitive(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


@app.middleware("http")
async def api_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
    request.state.request_id = request_id
    started_at = utcnow()
    body_for_log = None
    if request.method in {"POST", "PUT", "DELETE"}:
        raw_body = await request.body()
        if raw_body:
            try:
                body_for_log = mask_sensitive(json.loads(raw_body))
            except json.JSONDecodeError:
                body_for_log = "<non-json>"

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        duration_ms = round((utcnow() - started_at).total_seconds() * 1000, 2)
        log_record = {
            "request_id": request_id,
            "method": request.method,
            "endpoint": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "user_id": getattr(request.state, "user_id", None),
            "timestamp": started_at.isoformat(),
        }
        if body_for_log is not None:
            log_record["request_body"] = body_for_log
        print(json.dumps(log_record, default=str), flush=True)
    response.headers["X-Request-Id"] = request_id
    return response


app.include_router(AuthApiRouter)
app.include_router(OrdersApiRouter)
app.include_router(ProductsApiRouter)
app.include_router(PromoCodesApiRouter)
