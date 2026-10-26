"""Business spans and metrics shared by API, agent and worker execution."""

import time
from contextlib import contextmanager

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

llm_requests = Counter("llm_requests_total", "Model requests", ["model", "status"])
llm_latency = Histogram("llm_latency_seconds", "Model request latency", ["model"])
llm_tokens = Counter("llm_tokens_total", "Model token usage", ["model", "direction"])
llm_cost = Counter("llm_cost_total", "Estimated model cost", ["model"])
tool_calls = Counter("tool_calls_total", "Tool calls", ["tool", "status"])
tool_latency = Histogram("tool_latency_seconds", "Tool latency", ["tool"])
rag_latency = Histogram("rag_search_seconds", "Retrieval stage latency", ["stage"])
first_token = Histogram("chat_first_token_seconds", "First output token latency", ["model"])
active_streams = Gauge("stream_active_sessions", "Active agent streams")
agent_iterations = Histogram("agent_iterations", "Model calls in an agent run")


def configure_tracing(cfg, service_name, app=None):
    if not cfg.otel_endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.otel_endpoint.rstrip("/") + "/v1/traces"))
        )
        trace.set_tracer_provider(provider)
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)


@contextmanager
def operation(name, *, model=None, tool=None, stage=None):
    started = time.monotonic()
    status = "ok"
    attributes = {}
    if model:
        attributes["llm.model"] = model
    if tool:
        attributes["tool.name"] = tool
    with trace.get_tracer("zhixing").start_as_current_span(name, attributes=attributes):
        try:
            yield
        except BaseException:
            status = "error"
            raise
        finally:
            elapsed = time.monotonic() - started
            if model:
                llm_requests.labels(model, status).inc()
                llm_latency.labels(model).observe(elapsed)
            if tool:
                tool_calls.labels(tool, status).inc()
                tool_latency.labels(tool).observe(elapsed)
            if stage:
                rag_latency.labels(stage).observe(elapsed)


def record_usage(desc, message):
    usage = getattr(message, "usage_metadata", None) or {}
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    name = desc.model["model_name"]
    llm_tokens.labels(name, "prompt").inc(prompt)
    llm_tokens.labels(name, "completion").inc(completion)
    cost = (
        float(desc.model.get("input_price", 0)) * prompt
        + float(desc.model.get("output_price", 0)) * completion
    ) / 1_000_000
    llm_cost.labels(name).inc(cost)
