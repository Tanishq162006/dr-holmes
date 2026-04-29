"""Dr. Holmes FastAPI application entry point."""
from __future__ import annotations
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST,
)

from dr_holmes.api.lifespan import lifespan
from dr_holmes.api.routes import cases, agents, intel, ws
from dr_holmes.api.schemas.requests import HealthResponse


logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("dr_holmes.api")


# ── Prometheus metrics ─────────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests",
    labelnames=["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request latency",
    labelnames=["method", "path"],
)
cases_total = Counter("cases_total", "Total cases", labelnames=["status"])
ws_connections_active = Gauge("ws_connections_active", "Active WebSocket clients")


# ── App factory ────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Dr. Holmes API",
        description="Multi-agent diagnostic deliberation. ⚠ NOT FOR CLINICAL USE.",
        version="0.4.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def metrics_and_logging(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        path = request.url.path
        # Strip case_id from metric path to keep cardinality bounded
        bucket_path = path
        if bucket_path.startswith("/api/cases/") and len(bucket_path) > len("/api/cases/"):
            parts = bucket_path.split("/")
            if len(parts) >= 4:
                parts[3] = "{case_id}"
                bucket_path = "/".join(parts)
        http_requests_total.labels(request.method, bucket_path, response.status_code).inc()
        http_request_duration_seconds.labels(request.method, bucket_path).observe(duration)
        log.info(
            f"{request.method} {path} -> {response.status_code} ({duration*1000:.1f}ms)"
        )
        return response

    # Routes
    app.include_router(cases.router)
    app.include_router(agents.router)
    app.include_router(intel.router)
    app.include_router(ws.router)

    # ── Health endpoints ───────────────────────────────────────────────
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz():
        from dr_holmes.api.routes.intel import intel_health
        return await intel_health()

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/")
    async def root():
        return {
            "name": "Dr. Holmes API",
            "version": "0.4.0",
            "docs": "/docs",
            "health": "/healthz",
            "readiness": "/readyz",
            "metrics": "/metrics",
            "warning": "NOT FOR CLINICAL USE — AI simulation only",
        }

    return app


app = create_app()
