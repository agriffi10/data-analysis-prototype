"""Structured-logging bootstrap for the control-plane verbs (SPEC-127).

Three names, and a handler needs only the third::

    from cpcommon import observability

    observability.init(service="data-quality")

    @observability.traced("inspect-source")
    def handler(event, context): ...

``init`` configures ``log-foundry`` once per container; ``traced`` opens a span around the
handler and flushes on the way out, on both the success and the failure path.

**Import-safety is the point of this module's shape.** The ``cpcommon`` layer attaches to every
control-plane verb, and its ``config._require`` runs at import — one missing variable is a
cold-start crash across a whole control plane (the table-builder production break, PR #196).
So ``LOGS_QUEUE_URL`` is read with ``os.environ.get`` and never ``_require``: a function that
misses it logs to stdout instead of failing to start.

**One run is nine traces, not one.** A data-quality run is nine Lambda invocations and
``log-foundry``'s trace context is per-process, so ``trace_id`` never crosses a Lambda boundary
and ``parent_span_id`` is always null at a handler's root span. Correlate on
``fields.request_id`` instead (SPEC-128 FR-002). The fix, when it is worth the cost, is
``lf.continue_trace(traceparent)`` — the library ships it as of log-foundry 0.3.0 (log-forge
SPEC-014) — plus threading the traceparent through the Step Functions state payload on every
state, exactly as ``reportKey`` is threaded today. Deliberately sequenced after the pipe is
proven live (SPEC-128 FR-005).
"""

import functools
import logging
import os

import log_foundry as lf

from cpcommon import clients

logger = logging.getLogger(__name__)

# Optional (never _require) — it joins NOTIFICATIONS_QUEUE_URL as an explicitly optional
# variable, for the cold-start reason in the module docstring. Unset means stdout, not a crash.
LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")

# A build stamp when one is set; the library needs *a* version and "0.0.0" reads as "unstamped"
# rather than as a real release.
_VERSION = os.environ.get("BUILD_VERSION", "0.0.0")

_initialized = False


def init(service: str, **defaults: object) -> None:
    """Configure ``log-foundry`` for this container. Idempotent within a process.

    ``service`` is the **control plane**, not the function — ``data-quality``, never
    ``data-quality-inspect-source``. It becomes an S3 key prefix under ``logs/`` when the sweep
    partitions the events, so one plane's runs stay one queryable set; the per-verb identity
    rides as the ``verb`` field that :func:`traced` stamps.

    Args:
        service: The control-plane name.
        **defaults: Extra fields stamped on every event from this process.

    Note:
        ``lf.trace`` is used with **no** argument- or return-capture option here or anywhere in
        this repo, and that is deliberate rather than an oversight: it is the single setting that
        would turn every traced verb into a data-exfiltration path, writing user data into an
        operator store that is retained forever (SPEC-127 FR-009). The library captures nothing
        by default; keep it that way.
    """
    global _initialized
    if _initialized:
        return

    if LOGS_QUEUE_URL:
        from log_foundry.sinks.sqs import SQSSink

        # SQSSink ALONE — deliberately not a MultiSink with StdoutSink (user decision,
        # 2026-07-22). The cost, recorded so it is not rediscovered during an incident: if the
        # queue or the sweep breaks, that window's trace data is gone, and the only breadcrumb
        # is SQSSink's own stderr write (which does reach CloudWatch). What is NOT affected:
        # the ~20 existing logging.getLogger() call sites are untouched and CloudWatch still
        # receives every one of them, so SPEC-126 FR-004's forensic log is unchanged by this.
        #
        # The client comes from clients.sqs() so a warm container holds ONE boto3 SQS client
        # across the notifications path and this one.
        sink: object = SQSSink(LOGS_QUEUE_URL, client=clients.sqs())
    else:
        from log_foundry.sinks.stdout import StdoutSink

        sink = StdoutSink()
        logger.info(
            "structured logging: LOGS_QUEUE_URL unset — events go to stdout, not the logs queue"
        )

    lf.configure(
        service=service,
        version=_VERSION,
        env=os.environ.get("ENV_NAME", ""),
        sink=sink,  # type: ignore[arg-type]
        defaults=dict(defaults),
    )
    _initialized = True


def flush() -> None:
    """Drain the worker's queue through the sink. Never raises.

    Lambda freezes the execution environment the instant a handler returns, so the worker's
    1-second flush loop stops mid-interval and anything still queued dies with the container.
    This is the drain that prevents that.

    Calls ``lf.flush()`` and **never** ``lf.shutdown()``: ``shutdown()`` is terminal — it closes
    the sink, joins the worker thread and sets a once-only flag — so a handler that called it
    would log nothing for the rest of that warm container's life. The failure would present as
    "logging works locally, and in production only the first invocation appears."

    Every exception is swallowed and logged at warning, protecting one invariant: *logging must
    never be the reason a verb fails*.
    """
    try:
        lf.flush()
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning("structured logging: flush failed (%s: %s)", type(exc).__name__, exc)


def traced(verb: str):
    """Wrap a Lambda handler in a span stamped with ``verb``, flushing on the way out.

    The flush runs in a ``finally``, so it also runs on the failure path — the invocation whose
    trace is most worth having is the one that raised, and a flush written at the end of a
    handler body is exactly the line that does not execute when it does.

    Args:
        verb: The control-plane verb name, stamped as a field on every event in the span.
    """

    def decorate(fn):
        span = lf.trace(defaults={"verb": verb})(fn)

        # functools.wraps because Lambda resolves the entry point as `module.handler` BY NAME —
        # an unwrapped wrapper would be invisible to the runtime.
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return span(*args, **kwargs)
            finally:
                flush()

        return wrapper

    return decorate
