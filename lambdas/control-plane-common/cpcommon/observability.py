"""Structured-logging bootstrap and narrative for the control-plane verbs.

Seven names — ``init``, ``flush``, ``traced``, ``step``, ``info``, ``warning``, ``error``::

    from cpcommon import observability

    observability.init(service="data-quality")

    @observability.step("probe-columns")
    def _probe_columns(bucket, key): ...

    @observability.traced("inspect-source")
    def handler(event, context):
        observability.info("listed source", objects=142, format="csv")

``init`` configures ``log-foundry`` once per container; ``traced`` opens a span around the
handler and flushes on the way out, on both the success and the failure path; ``step`` opens
a child span around one named internal step; the three level emitters attach an event to
whichever span is currently open.

Nothing outside this module imports ``log_foundry``, so the field rule has one door rather
than thirty-four. Messages are literals and everything variable is a field: a literal groups
across invocations and can be counted, filtered and alerted on, while an f-string mints a
distinct message per run and can do none of those things.

**Read the field rule in ``docs/decisions.md`` before instrumenting any call site** — user
metadata in, file contents out, tokens and emails always out. The emitters do not enforce it
at runtime, deliberately: it turns on provenance, which no filter over a field name or value
shape can see, and a filter that looked like enforcement would be worse than none because it
would be trusted. Shape notes, the stack-trace exemption and the one-run-is-nine-traces
caveat are in ``docs/lambda-rationale.md``.

Import-safety is the point of this module's shape. The cpcommon layer attaches to every
control-plane verb, and ``config._require`` runs at import — one missing variable is a
cold-start crash across a whole control plane, which is this fleet's own recorded outage
(PR #196). So ``LOGS_QUEUE_URL`` is read with ``os.environ.get`` and never ``_require``: a
function that misses it logs to stdout instead of failing to start. It joins
``NOTIFICATIONS_QUEUE_URL`` as an explicitly optional variable.

Attributes:
  LOGS_QUEUE_URL: Optional and never required, for the cold-start reason above. Unset means
    stdout, not a crash.
  _VERSION: A build stamp when one is set. The library needs a version, and "0.0.0" reads as
    unstamped rather than as a real release.
"""

import functools
import json
import logging
import os

import log_foundry as lf

from cpcommon import clients

logger = logging.getLogger(__name__)

LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")

_VERSION = os.environ.get("BUILD_VERSION", "0.0.0")

_initialized = False


def init(service: str, **defaults: object) -> None:
    """Configures log-foundry for this container, once per process.

    With a queue URL the sink is an SQS sink alone, deliberately not a MultiSink with stdout:
    if the queue or the sweep breaks, that window's trace data is gone and the only breadcrumb
    is the sink's own stderr write. The existing ``logging.getLogger()`` call sites are
    untouched, so CloudWatch still receives every one of them. Its client comes from
    ``clients.sqs()`` so a warm container holds one boto3 SQS client across this path and the
    notifications path, and its message group is the service rather than log-foundry's default
    of one group per trace — a simpler ordering story, and the sweep is a single consumer
    anyway. The sink infers FIFO from the queue URL and mints a UUID deduplication id per
    event, which is why the queue must not enable content-based deduplication.

    Without a queue URL, events go to stdout, and stdout in Lambda is CloudWatch. That is the
    one named exposure to the "narrative never reaches the console" rule, and the fallback
    stays anyway because it is the cold-start safety property this whole module is shaped
    around. It exposes nothing CloudWatch does not already hold.

    Args:
      service: The control-plane name — ``data-quality``, never
          ``data-quality-inspect-source``. It becomes an S3 key prefix under ``logs/`` when
          the sweep partitions the events, so one plane's runs stay one queryable set; the
          per-verb identity rides as the ``verb`` field that ``traced`` stamps.
      **defaults: Extra fields stamped on every event from this process.

    Returns:
      None.

    Raises:
      None.

    Note:
      ``lf.trace`` is used with no argument- or return-capture option here or anywhere in
      this repo, and that is deliberate: it is the single setting that would turn every
      traced verb into a data-exfiltration path, writing user data into an operator store
      retained forever. The library captures nothing by default; keep it that way.
    """
    global _initialized
    if _initialized:
        return

    if LOGS_QUEUE_URL:
        from log_foundry.sinks.sqs import SQSSink

        sink: object = SQSSink(
            LOGS_QUEUE_URL, client=clients.sqs(), message_group_id=service
        )
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
    """Drains the worker's queue through the sink.

    Lambda freezes the execution environment the instant a handler returns, so the worker's
    one-second flush loop stops mid-interval and anything still queued dies with the
    container. This is the drain that prevents that.

    Calls ``lf.flush()`` and never ``lf.shutdown()``: shutdown is terminal — it closes the
    sink, joins the worker thread and sets a once-only flag — so a handler that called it
    would log nothing for the rest of that warm container's life. The failure would present
    as "logging works locally, and in production only the first invocation appears."

    Args:
      None.

    Returns:
      None.

    Raises:
      None. Every exception is swallowed and logged at warning, protecting the invariant that
      logging must never be the reason a verb fails.
    """
    try:
        lf.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("structured logging: flush failed (%s: %s)", type(exc).__name__, exc)


def traced(verb: str):
    """Builds a decorator wrapping a Lambda handler in a span, flushing on the way out.

    The flush runs in a ``finally``, so it also runs on the failure path — the invocation
    whose trace is most worth having is the one that raised, and a flush written at the end of
    a handler body is exactly the line that does not execute when it does.

    The span is named explicitly. Without a name, log-foundry falls back to the qualified
    function name and every root span in the fleet reads ``handler``, because every Lambda
    entry point in this repo is named ``handler``. That rename is a discontinuity in a store
    retained forever, accepted rather than migrated: the objects are appended NDJSON, and
    rewriting them to tidy a field boundary would risk a day of logs to save a WHERE clause.
    ``fields.verb`` is populated on both sides of the cutover.

    ``functools.wraps`` is required, not cosmetic: Lambda resolves the entry point as
    ``module.handler`` by name, and an unwrapped wrapper would be invisible to the runtime.

    Args:
      verb: The control-plane verb name. Names the span and rides as baggage on every event
          in it, children included.

    Returns:
      A decorator for a Lambda handler.

    Raises:
      None.
    """

    def decorate(fn):
        """Wraps one Lambda handler in the verb's span.

        Args:
          fn: The handler to wrap.

        Returns:
          The wrapped handler.

        Raises:
          None.
        """
        span = lf.trace(name=verb)(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            """Stamps this invocation's baggage, runs the span, and flushes on the way out.

            Args:
              *args: The handler's positional arguments; the first is the event.
              **kwargs: The handler's keyword arguments.

            Returns:
              Whatever the handler returned.

            Raises:
              Exception: Whatever the handler raised; the flush still runs.
            """
            _reset_baggage()
            _stamp_verb(verb)
            _stamp_request_id(args[0] if args else None)
            try:
                return span(*args, **kwargs)
            finally:
                flush()

        return wrapper

    return decorate


def step(name: str):
    """Opens a child span around one named internal step.

    Turns "the verb took 8 seconds and failed" into "the listing took 40ms, the column probe
    took 7.9s and raised" — the child gets its own function, duration and status, parented to
    the handler's span inside the same trace.

    A thin alias for ``lf.trace(name=...)``, and it stays one on purpose. The library's
    decorator is non-swallowing by design, recording the failure and re-raising the original
    exception unchanged, and that property has to survive contact with this wrapper. A step
    that swallowed would convert a terminal failure into a silent wrong answer, under
    ``@traced``, which sits outermost above ``@notifies_on_failure``. Nothing worth adding
    here justifies putting a ``try`` between a raise and its notification.

    Which functions get a step is a per-call-site decision: every event is an SQS message and
    a line in a day object the sweep rewrites in full, so a step inside a per-item loop is a
    volume decision.

    Args:
      name: The step name, emitted as the child span's function.

    Returns:
      A decorator for the step function.

    Raises:
      None.
    """
    return lf.trace(name=name)


def stamp(**fields: object) -> None:
    """Binds fields to every event for the rest of this invocation.

    Trace baggage: unlike a per-call field it reaches the boundary spans and every child span,
    which is what makes it usable as a join key — and a join key present on only one side of
    the join is not a join key. Use it for the one or two values identifying the invocation,
    never for per-item detail.

    ``traced`` clears baggage at the start of every invocation, so a warm container cannot
    leak one invocation's identity onto the next. Call this inside the handler, after that
    clear. It exists so a call site never has to import ``log_foundry`` directly — the one-door
    rule survives by widening the door, not by making an exception to it.

    Args:
      **fields: Field names and values to bind for the rest of the invocation.

    Returns:
      None.

    Raises:
      None. Logging must never fail a verb.
    """
    try:
        lf.set_baggage(**fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not stamp %s (%s: %s)",
            ", ".join(fields) or "(nothing)",
            type(exc).__name__,
            exc,
        )


def info(message: str, **fields: object) -> None:
    """Emits an INFO event on the current span.

    Args:
      message: A literal. Everything variable belongs in a field.
      **fields: Event fields. See the module docstring for what may become a field value.

    Returns:
      None.

    Raises:
      None.
    """
    _emit(lf.info, message, fields)


def warning(message: str, **fields: object) -> None:
    """Emits a WARNING event for a degraded-but-continuing path.

    Args:
      message: A literal. Everything variable belongs in a field.
      **fields: Event fields.

    Returns:
      None.

    Raises:
      None.
    """
    _emit(lf.warning, message, fields)


def error(message: str, **fields: object) -> None:
    """Emits an ERROR event for a path that failed.

    Args:
      message: A literal. Everything variable belongs in a field.
      **fields: Event fields.

    Returns:
      None.

    Raises:
      None.
    """
    _emit(lf.error, message, fields)


def _emit(level_fn, message: str, fields: dict[str, object]) -> None:
    """Routes one level event through log-foundry, never failing the caller.

    ``echo`` is dropped and warned rather than forwarded. It is an unusually quiet mistake:
    ``**fields`` swallows the keyword, so an author who sets it gets neither a failure nor a
    console line, just a silently emitted field named ``echo`` that an operator cannot tell
    from an intentional one.

    Swallowing matters most on the orphan path — an emitter called with no span open goes
    straight to the sink synchronously, so a sink that raises raises here, in the middle of
    business logic, rather than on the worker thread where the span path absorbs it.

    Args:
      level_fn: The log-foundry level function to call.
      message: The literal message.
      fields: Event fields, mutated in place to drop a prohibited ``echo``.

    Returns:
      None.

    Raises:
      None. Logging must never be the reason a verb fails.
    """
    try:
        if "echo" in fields:
            del fields["echo"]
            logger.warning(
                "structured logging: `echo` is prohibited and was dropped from %r — the "
                "narrative goes to the logs queue, never the console (SPEC-130 FR-006)",
                message,
            )
        level_fn(message, echo=False, **fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: event %r dropped (%s: %s)", message, type(exc).__name__, exc
        )


def _reset_baggage() -> None:
    """Clears trace baggage at the start of every invocation.

    Baggage lives in a context variable, and a warm Lambda container reuses the same context
    across invocations. Without this, a run that sets a request id leaves it set for the next
    run, and a verb that fails to set one would silently emit the previous run's id. That is
    worse than an unjoinable event: a fabricated correlation key merges two unrelated runs
    into one query result and nothing about the output looks wrong. A missing request id must
    stay missing rather than be invented, and a leaked one is an invented one.

    Uses the library's private context variable because there is no public clear —
    ``set_baggage`` only merges.

    Args:
      None.

    Returns:
      None.

    Raises:
      None. Guarded so a library refactor degrades to a warning, never a failed verb.
    """
    try:
        from log_foundry import context as lf_context

        lf_context._baggage.set({})
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not reset baggage (%s: %s)", type(exc).__name__, exc
        )


def _stamp_verb(verb: str) -> None:
    """Puts the verb into baggage so child spans and mid-span events inherit it.

    Baggage rather than a span default: a default applies to that span's own events and to
    nothing nested inside it, so the first child step would carry the request id but not the
    verb that produced it — joinable to its run, and unattributable to the verb. Must run
    after ``_reset_baggage``, which clears the whole mapping.

    Args:
      verb: The control-plane verb name.

    Returns:
      None.

    Raises:
      None.
    """
    stamp(verb=verb)


def _extract_request_id(event: object) -> str | None:
    """Pulls the request id out of either event shape a control-plane verb can receive.

    Two shapes, because a control plane has two kinds of entry point. The Step Functions state
    payload is a plain dict carrying the id at the top level — every verb from inspect-source
    onward. The EventBridge Pipe envelope is the raw SQS batch, a list whose single record's
    body is a JSON string — every validate-authorize verb. Missing the second shape is what
    made the verb that establishes the request the one verb that could not be joined to its own
    run, found in live traffic on 2026-07-23: the synthetic empty-event probe could not
    distinguish "absent" from "not extracted", so no test would have caught it.

    Deliberately does not call ``events.parse_sqs_request``, which raises ``TerminalError`` on
    a malformed envelope: a logging helper that can raise a domain terminal is a logging helper
    that can fail a verb.

    Args:
      event: The handler's event, of either shape.

    Returns:
      The request id, or None when there is none to read.

    Raises:
      None. Never parses beyond what it needs.
    """
    if isinstance(event, dict):
        direct = event.get("requestId")
        if isinstance(direct, str) and direct:
            return direct

    record = event[0] if isinstance(event, list) and event else event
    if isinstance(record, dict):
        body = record.get("body")
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
            except (TypeError, ValueError):
                return None
            if isinstance(parsed, dict):
                nested = parsed.get("requestId")
                if isinstance(nested, str) and nested:
                    return nested
    return None


def _stamp_request_id(event: object) -> None:
    """Puts the run's request id into baggage, read from the handler's own event.

    Done here rather than as a hand-written line in each verb: a run that shows eight of nine
    verbs looks like a run that stopped at eight, and a correlation key added by hand in nine
    places is one a tenth verb will be added without. Stamping it at the single point that
    already wraps every handler makes it structural instead of remembered.

    A verb invoked with no usable id emits its span with the field absent rather than
    defaulted, because a fabricated correlation key silently merges unrelated runs.

    Args:
      event: The handler's event.

    Returns:
      None.

    Raises:
      None. Logging must never fail a verb.
    """
    request_id = None
    try:
        request_id = _extract_request_id(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not read request_id (%s: %s)", type(exc).__name__, exc
        )
    if not request_id:
        return
    stamp(request_id=request_id)
