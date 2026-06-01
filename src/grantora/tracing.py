from __future__ import annotations

import sys
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import INVALID_SPAN, Span, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from grantora.config import Settings


@dataclass
class TraceManager:
    enabled: bool
    tracer: Any | None = None
    provider: TracerProvider | None = None
    propagator: TraceContextTextMapPropagator | None = None

    def start_as_current_span(
        self,
        name: str,
        *,
        carrier: dict[str, str] | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ):
        if not self.enabled or self.tracer is None or self.propagator is None:
            return nullcontext(INVALID_SPAN)

        context = self.propagator.extract(carrier=carrier or {})
        return self.tracer.start_as_current_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes or {},
        )

    def inject_current_context(self, headers: dict[str, str]) -> None:
        if not self.enabled or self.propagator is None:
            return

        carrier: dict[str, str] = {}
        self.propagator.inject(carrier)
        if "traceparent" in carrier:
            headers["traceparent"] = carrier["traceparent"]
        if "tracestate" in carrier:
            headers["tracestate"] = carrier["tracestate"]

    def shutdown(self) -> None:
        if self.provider is None:
            return
        self.provider.force_flush()
        self.provider.shutdown()


def create_trace_manager(
    settings: Settings,
    *,
    exporter: SpanExporter | None = None,
    use_simple_processor: bool | None = None,
) -> TraceManager:
    if not settings.otel_tracing_enabled:
        return TraceManager(enabled=False)

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.environment,
            }
        )
    )
    resolved_exporter = exporter or _default_exporter(settings)
    use_simple = (
        use_simple_processor
        if use_simple_processor is not None
        else (settings.environment == "test")
    )
    if use_simple:
        provider.add_span_processor(SimpleSpanProcessor(resolved_exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(resolved_exporter))

    return TraceManager(
        enabled=True,
        tracer=provider.get_tracer("grantora"),
        provider=provider,
        propagator=TraceContextTextMapPropagator(),
    )


def span_ids(span: Span) -> tuple[str | None, str | None]:
    context = span.get_span_context()
    if not context.is_valid:
        return None, None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def _default_exporter(settings: Settings) -> SpanExporter:
    if settings.otel_exporter_otlp_endpoint:
        return OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            timeout=settings.otel_exporter_otlp_timeout_seconds,
        )
    return ConsoleSpanExporter(out=sys.stderr)
