"""Métricas, tracing OTLP e captura opcional de exceções."""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from prometheus_client import Gauge

REQUISICOES = Counter("advocacia_http_requests_total", "Requisições HTTP", ("method", "path", "status"))
LATENCIA = Histogram("advocacia_http_request_seconds", "Latência HTTP", ("method", "path"))
FILA = Gauge("advocacia_queue_size", "Jobs aguardando por fila", ("queue",))


def configurar(app: FastAPI) -> None:
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")))

    otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "advocacia-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)

    @app.middleware("http")
    async def medir(request: Request, call_next):
        inicio = time.perf_counter()
        status = 500
        try:
            resposta = await call_next(request)
            status = resposta.status_code
            return resposta
        finally:
            rota = request.scope.get("route")
            caminho = getattr(rota, "path", request.url.path)
            REQUISICOES.labels(request.method, caminho, str(status)).inc()
            LATENCIA.labels(request.method, caminho).observe(time.perf_counter() - inicio)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        try:
            from redis import Redis
            redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6380/0"))
            for fila in ("gpu_realtime", "gpu_background", "ai", "documents", "default", "low"):
                FILA.labels(fila).set(redis.llen(fila))
        except Exception:
            pass
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
