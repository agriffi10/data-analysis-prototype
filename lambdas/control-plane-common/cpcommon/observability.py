"""Structured-logging bootstrap and narrative for the control-plane verbs.

Nine names — ``init``, ``flush``, ``traced``, ``step``, ``stamp``, ``run_traceparent``, ``info``,
``warning``, ``error``::

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

No VERB imports ``log_foundry``, so the field rule has one door rather than thirty-four. Two
test harnesses do — ``lambdas/conftest.py`` and ``log-sweep/test_log_sweep.py`` — because a
harness that swaps the process sink has to call ``configure``; the rule binds the code that
runs in production. Messages are literals and everything variable is a field: a literal groups
across invocations and can be counted, filtered and alerted on, while an f-string mints a
distinct message per run and can do none of those things.

**Read the field rule in ``docs/decisions/control-planes.md`` before instrumenting any call site** — user
metadata in, file contents out, tokens and emails always out. The emitters do not enforce it
at runtime, deliberately: it turns on provenance, which no filter over a field name or value
shape can see, and a filter that looked like enforcement would be worse than none because it
would be trusted. Shape notes, the stack-trace exemption and how a run becomes ONE trace are
in ``lambdas/info/shared-layer.md``. The FAILURE path is threaded too, including the one where the
error REPLACED the state: its traceparent is reachable nowhere ASL can read, which is still true and
is why the machines are shaped as they are, so the envelope travels on the state instead and this
module reads the value out of it in Python.

Import-safety is the point of this module's shape. ``cpcommon`` is resolved by every
control-plane verb, including three that set almost none of ``config``'s environment — and
when ``config._require`` ran at import, one missing variable was a cold-start crash across a
whole control plane, this fleet's own recorded outage. That read moved
to first read, which narrows the window but does not change this module's obligation: it must
reach ``config`` for nothing. So ``LOGS_QUEUE_URL`` is read with ``os.environ.get`` and never
``_require``: a function that misses it logs to stdout instead of failing to start. It joins
``NOTIFICATIONS_QUEUE_URL`` as an explicitly optional variable.

Attributes:
  PROHIBITED_FIELDS: Field names a call site may not use, mapped to the reason each is
    refused — ``_emit`` reads this mapping, so adding a name here is sufficient to prohibit it.
    They are refused for DIFFERENT reasons: ``echo`` collides with the keyword this module
    always passes to the library, so an un-dropped one raises ``TypeError``; ``fields`` is the
    library's own parameter, so an un-dropped one raises nothing and is silently REINTERPRETED,
    the event landing with the mapping's contents in place of a field of that name.
  LOGS_QUEUE_URL: Optional and never required, for the cold-start reason above. Unset means
    stdout, not a crash.
  UNSTAMPED_VERSION: What ``version`` reads when no build stamp can be found at all. It is a
    sentinel, not a release, and a test forbids a deployed record carrying it.
  _VERSION: The commit this function's code was built from, resolved once per container.
    Read publicly through ``build_version``.
  _ADOPTED: The inbound traceparent this invocation joined, VERBATIM, read publicly through
    ``run_traceparent``. It exists because the library's only accessor,
    ``context.get_adopted_context()``, hands back ``(trace_id, parent_span_id)`` — version and
    flags already discarded — so a string rebuilt from it is not the string that arrived, and an
    inbound unsampled ``-00`` would be re-emitted as ``-01``. A ``ContextVar`` rather than a
    module global for the reason the library's own state is one: it is then correct under threads
    and asyncio for free. Set by ``_adopt_trace`` and cleared by ``_reset_context``, so its
    lifetime is exactly one invocation.
"""

import contextvars
import functools
import json
import logging
import os
from collections.abc import Iterator

import log_foundry as lf

from cpcommon import clients

logger = logging.getLogger(__name__)

_ADOPTED: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cpcommon_adopted_traceparent", default=None
)

PROHIBITED_FIELDS = {
    "echo": (
        "the narrative goes to the logs queue, never the console — and left in place this one "
        "collides with the keyword `_emit` always passes, raising TypeError"
    ),
    "fields": (
        "`fields` is the library's own parameter: a mapping passed under that name is unpacked "
        "over the event instead of landing as a field, so nothing raises and the field vanishes"
    ),
}

LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")

UNSTAMPED_VERSION = "0.0.0"


def _build_version():
    """Resolves the commit this function's code was built from.

    Before the stamp shipped in the package every record carried ``"0.0.0"``, because
    nothing set ``BUILD_VERSION``. The field exists to correlate a record with a deploy.

    The stamp travels IN THE ARTEFACT — ``BUILD_VERSION`` in the task root — rather than in the
    function's environment, because Tofu owns the environment map:
    ``update-function-configuration --environment`` replaces it whole, so an env-borne version
    would either race an apply or be reverted by the next one, and Deploy Infrastructure is
    path-filtered to ``infra/**``, so a Tofu-set value would name the last infra commit rather
    than the running code. ``test_fleet_environment.py`` holds Terraform to that across
    EVERY module, and ``test_api_module.py`` separately for the API's own.

    TWO PIPELINES WRITE THAT FILE and the path is the same for both, which is the whole reason
    this function needed no change when the fleet moved to a container image: ``Deploy Lambdas``
    writes it into each zip beside the handler, and ``lambdas/Dockerfile`` writes it into the
    image's task root from a build argument. A zip function and a container function therefore
    answer this identically.

    The environment variable is still honoured first, so a test or a future release tag can
    override without a rebuild.

    Read at import and never again: the answer cannot change within a container, and a
    per-record file read would pay for that on every event.

    Args:
      None.

    Returns:
      The commit sha, or ``UNSTAMPED_VERSION`` when no stamp is present — which now means
      genuinely unstamped rather than "nobody wired this up".

    Raises:
      None.
    """
    stamped = os.environ.get("BUILD_VERSION", "").strip()
    if stamped:
        return stamped
    # LAMBDA_TASK_ROOT is set by the runtime; its absence means this is not a Lambda (a unit
    # test, or the local CLI), where there is no artefact to identify.
    root = os.environ.get("LAMBDA_TASK_ROOT", "")
    if not root:
        return UNSTAMPED_VERSION
    try:
        with open(os.path.join(root, "BUILD_VERSION"), encoding="utf-8") as handle:
            return handle.read().strip() or UNSTAMPED_VERSION
    except OSError:
        # A missing or unreadable stamp must never keep a function from starting: every
        # control-plane verb resolves this module, and a real outage is what an import-time
        # failure here costs.
        return UNSTAMPED_VERSION


_VERSION: str = _build_version()


def build_version() -> str:
    """Reports the commit this function's code was built from.

    A public reader of the value ``_build_version`` already resolved once at import. It exists
    because the API's ``/healthz`` must report the same stamp the log records carry, and a
    second resolution in the handler would be a second copy of the environment-then-package
    fallback chain — the one that decides whether an unstamped deploy reads as ``0.0.0`` or as
    a crash. One algorithm, one owner.

    Args:
      None.

    Returns:
      The commit sha, or ``UNSTAMPED_VERSION`` when no stamp is present.

    Raises:
      None.
    """
    return _VERSION


_initialized = False


def init(service: str, max_stack_bytes: int | None = None, **defaults: object) -> None:
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

    ``max_stack_bytes`` is a NAMED parameter rather than one more entry in ``defaults``, and
    the distinction is not cosmetic: passed through ``**defaults`` the name would be stamped on
    every event as a FIELD called ``max_stack_bytes`` and would bound nothing at all. It is a
    ceiling on the stack attached to a failed span, not a control over whether one is attached —
    ``log-foundry`` offers no way to turn that capture off, and its validator rejects any value
    below 1, so a caller that must not emit credentials scrubs at its boundary and does not
    reach for this.

    Args:
      service: The control-plane name — ``data-quality``, never
          ``data-quality-inspect-source``. It becomes an S3 key prefix under ``logs/`` when
          the sweep partitions the events, so one plane's runs stay one queryable set; the
          per-verb identity rides as the ``verb`` field that ``traced`` stamps.
      max_stack_bytes: Ceiling on ``error.stack``. ``None`` inherits the library's default,
          which is what every control plane does.
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
        # Read here rather than at import: unlike the build stamp this is a plain variable
        # with no file behind it, and reading it at configure time keeps it overridable.
        env=os.environ.get("ENV_NAME", ""),
        sink=sink,  # type: ignore[arg-type]
        defaults=dict(defaults),
        max_stack_bytes=max_stack_bytes,
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
            """Stamps this invocation's baggage, joins the run's trace, runs the span, flushes.

            The order is the contract. ``_reset_context`` clears baggage AND any adopted trace,
            so everything below it belongs to this invocation alone; ``_adopt_trace`` comes last
            because the adoption is consumed by the next root span opened here, and that span is
            the one the line below opens. Adopting before the reset would clear the adoption.

            Args:
              *args: The handler's positional arguments; the first is the event.
              **kwargs: The handler's keyword arguments.

            Returns:
              Whatever the handler returned.

            Raises:
              Exception: Whatever the handler raised; the flush still runs.
            """
            event = args[0] if args else None
            _reset_context()
            _stamp_verb(verb)
            _stamp_request_id(event)
            _adopt_trace(event)
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

    ``traced`` clears the trace context at the start of every invocation, so a warm container cannot
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

    ``PROHIBITED_FIELDS`` are dropped and warned rather than forwarded, and the two are dropped
    for DIFFERENT reasons — a reader who collapses them will merge the warnings and lose one.
    ``echo`` collides with the keyword this function always passes, so leaving it in raises
    ``TypeError: got multiple values for keyword argument 'echo'`` at the call boundary, inside
    business logic. ``fields`` is the library's own escape hatch, so leaving it in raises
    NOTHING: the mapping is unpacked over the event and the author's field silently disappears.
    Measured both ways.

    The ``try`` therefore still earns its place, and not for the reason it used to give. The
    library now absorbs a sink failure on both the span path and the orphan path, so a raising
    SINK no longer reaches here. What reaches here is the ``TypeError`` above — raised by this
    function's own call, before the library sees it.

    Args:
      level_fn: The log-foundry level function to call.
      message: The literal message.
      fields: Event fields, mutated in place to drop any name in ``PROHIBITED_FIELDS``.

    Returns:
      None.

    Raises:
      None. Logging must never be the reason a verb fails.
    """
    try:
        for name, reason in PROHIBITED_FIELDS.items():
            if name in fields:
                del fields[name]
                logger.warning(
                    "structured logging: `%s` is prohibited and was dropped from %r — %s",
                    name,
                    message,
                    reason,
                )
        level_fn(message, echo=False, **fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: event %r dropped (%s: %s)", message, type(exc).__name__, exc
        )


def _reset_context() -> None:
    """Clears trace baggage AND any adopted trace context at the start of every invocation.

    Baggage lives in a context variable, and a warm Lambda container reuses the same context
    across invocations. Without this, a run that sets a request id leaves it set for the next
    run, and a verb that fails to set one would silently emit the previous run's id. That is
    worse than an unjoinable event: a fabricated correlation key merges two unrelated runs
    into one query result and nothing about the output looks wrong. A missing request id must
    stay missing rather than be invented, and a leaked one is an invented one.

    ``reset_context`` clears an adopted trace context as well as baggage, which is more than
    this function's old name advertised and is the reason it was renamed. ``_adopt_trace`` is
    the caller that made that load-bearing: an adopted context outliving its invocation would
    put a warm container into a trace whose run had ended — the same fabricated-correlation
    failure as a leaked request id, one level up.

    The module's own record of the adopted traceparent is cleared in the same breath and
    OUTSIDE the guard, because the two must not be able to disagree: a library clear that threw
    while this one was skipped would leave ``run_traceparent`` handing out a finished run's
    value to the next invocation, which is the failure this function exists to prevent.

    Args:
      None.

    Returns:
      None.

    Raises:
      None. Guarded so a library refactor degrades to a warning, never a failed verb.
    """
    _ADOPTED.set(None)
    try:
        from log_foundry import context as lf_context

        lf_context.reset_context()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not reset the trace context (%s: %s)",
            type(exc).__name__,
            exc,
        )


def _stamp_verb(verb: str) -> None:
    """Puts the verb into baggage so child spans and mid-span events inherit it.

    Baggage rather than a span default: a default applies to that span's own events and to
    nothing nested inside it, so the first child step would carry the request id but not the
    verb that produced it — joinable to its run, and unattributable to the verb. Must run
    after ``_reset_context``, which clears the whole mapping.

    Args:
      verb: The control-plane verb name.

    Returns:
      None.

    Raises:
      None.
    """
    stamp(verb=verb)


def _envelope_values(batch: object, key: str) -> Iterator[object]:
    """Yields one key's value out of a forwarded SQS batch, wherever that batch was found.

    Two shapes reach the same bytes: the Pipe hands the batch to a validate-authorize verb as its
    whole event, and a failure terminal carries the same batch on the state as ``raw``. One walk
    serves both, so the list-only narrowing — a security boundary, argued in ``_shape_values`` —
    cannot be enforced for one shape and forgotten for the other.

    Args:
      batch: The forwarded SQS records, of any type — anything but a non-empty list yields nothing.
      key: The field name to look for inside the first record's JSON body.

    Yields:
      The first record's value for that key, unvalidated and possibly None. Nothing at all when the
      batch is empty, holds no dict, carries no string body, or carries a body that is not JSON —
      every malformed step degrades to silence rather than raising.

    Raises:
      None. Never parses beyond what it needs.
    """
    if not isinstance(batch, list):
        return
    record = batch[0] if batch else None
    if isinstance(record, dict):
        body = record.get("body")
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                yield parsed.get(key)


def _shape_values(event: object, key: str) -> Iterator[object]:
    """Yields one key's value from every event shape a control-plane verb can receive.

    FIVE shapes, because a control plane has five ways a run's identity can reach a verb. The Step
    Functions state payload is a plain dict carrying the value at the top level — every verb from
    inspect-source onward. The EventBridge Pipe envelope is the raw SQS batch, a LIST whose single
    record's body is a JSON string — every validate-authorize verb. A Distributed Map hands its
    child ``{"BatchInput": {...}, "Items": [...]}``, where the manifest lines leave no room for a
    per-run value and the batch block is the only place one can travel. An inline Map nests the
    parent state under ``request``, which is why the three inline-Map children could not be
    joined to their own run at all.

    The fifth is that same forwarded batch carried ON the state as ``raw``, and it is how a failure
    terminal's verb reaches a run whose seed had no traceparent to thread. Where the error REPLACED
    the state there is nothing left to read — but ``$$.Execution.Input`` did not go anywhere, and
    every ``RecordFailure`` copies it onto the state, so the value is reachable in Python even
    though it is reachable nowhere ASL can look. It is walked LAST: a post-identity failure carries
    both a real top-level value and ``raw``, both name the same run, and walking the threaded one
    first keeps it authoritative and skips the parse.

    **The body branch fires for a LIST and nothing else, and that is a security boundary rather
    than a shape detail.** It used to fall back to treating a non-list event as the record, and
    for an API Gateway payload-2.0 request ``body`` is the CALLER'S OWN HTTP body — so a caller
    could name this service's correlation key, and, once a traceparent travels the same walk,
    could put the API's span into a trace of their choosing. Nothing overwrites an adopted trace,
    which is what makes the second one live rather than latent. Production always delivers the
    array, and the API is the only verb in the fleet with a top-level ``body``.

    **The fifth shape does not reopen that**, and the reason is provenance rather than shape.
    ``raw`` is written only by ASL, from ``$$.Execution.Input``, and never by a caller: the value
    is this execution's own input and can be no other run's, and the ``traceparent`` inside its
    body is one the API stamps unconditionally over anything a caller sent. The narrowing itself is
    unchanged and now lives in one place — ``_envelope_values`` yields nothing for a non-list — so a
    BARE dict carrying a top-level ``body`` string still names neither key.

    Deliberately does not call ``events.parse_sqs_request``, which raises ``TerminalError`` on
    a malformed envelope: a logging helper that can raise a domain terminal is a logging helper
    that can fail a verb.

    Args:
      event: The handler's event, of any of the five shapes.
      key: The field name to look for.

    Yields:
      Each shape's value for that key, in shape order, unvalidated and possibly None. A caller
      decides what counts as usable, because the two callers disagree: an unusable request id is
      dropped, while an unusable traceparent is handed on so the library can reject it and the
      rejection can be warned.

    Raises:
      None. Never parses beyond what it needs.
    """
    if isinstance(event, list):
        yield from _envelope_values(event, key)
        return

    if not isinstance(event, dict):
        return

    yield event.get(key)
    for nested in ("BatchInput", "request"):
        block = event.get(nested)
        if isinstance(block, dict):
            yield block.get(key)
    yield from _envelope_values(event.get("raw"), key)


def _extract_request_id(event: object) -> str | None:
    """Pulls the request id out of every event shape a control-plane verb can receive.

    Reaching the forwarded envelope on the state is the intended consequence of the fifth shape and
    not a side effect of it. A seed that supplies ``requestId: null`` used to leave a failure
    correlating on NOTHING — neither a trace nor the join key that exists for everything outside
    one — and the caller's own id is sitting in the envelope beside the traceparent.

    That id is the caller's by design and is not a new exposure: the API echoes it back, the planes
    carry it, and this same field is already read from this same place for every validate-authorize
    in the fleet. What the list-only narrowing refuses is a BARE dict's ``body``, which for an API
    Gateway request is the caller's live HTTP body; ``raw`` is written by ASL and never by a caller,
    so that narrowing is untouched.

    Args:
      event: The handler's event.

    Returns:
      The request id, or None when there is none to read.

    Raises:
      None.
    """
    for value in _shape_values(event, "requestId"):
        if isinstance(value, str) and value:
            return value
    return None


def _extract_traceparent(event: object) -> object | None:
    """Pulls the run's traceparent out of every event shape a control-plane verb can receive.

    Returns an unusable value rather than dropping it, so ``_adopt_trace`` can tell a producer
    sending the WRONG TYPE from one sending nothing and warn about only the first. Dropping a
    non-string here would make those two indistinguishable. An ABSENT traceparent is normal — the
    API is the root of every run and has none by definition — and a null one is normal too,
    because the producer writes the field unconditionally. Both read as None here and neither
    warns; only something present and unusable does.

    Args:
      event: The handler's event.

    Returns:
      The first truthy value any shape carries, of whatever type it arrived as, or None.

    Raises:
      None.
    """
    for value in _shape_values(event, "traceparent"):
        if value:
            return value
    return None


def _adopt_trace(event: object) -> None:
    """Joins this invocation's span to the run's trace, read from the handler's own event.

    Runs AFTER ``_reset_context``, which is what makes one adoption cover one invocation:
    ``reset_context`` clears an adopted context as well as baggage, so a warm container cannot
    carry a finished run's trace into the next, unrelated one. Adoption applies to the next root
    span opened here, which is the span ``traced`` is about to open.

    Args:
      event: The handler's event.

    Returns:
      None.

    Raises:
      None. Logging must never fail a verb.
    """
    try:
        value = _extract_traceparent(event)
        if value is None:
            return
        if not isinstance(value, str):
            logger.warning(
                "structured logging: the inbound traceparent is a %s rather than a string, so "
                "this span opens a fresh trace",
                type(value).__name__,
            )
            return
        outcome = lf.continue_trace(value)
        if outcome:
            _ADOPTED.set(value)
        elif outcome.reason == "rejected":
            logger.warning(
                "structured logging: the inbound traceparent was rejected, so this span opens "
                "a fresh trace"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not adopt the inbound trace (%s: %s)",
            type(exc).__name__,
            exc,
        )


def run_traceparent() -> str | None:
    """The traceparent identifying THIS RUN, for a verb that has to hand it onward.

    The adopted value verbatim, or the current span's where nothing was adopted — which is the
    API, the one place a run begins. Verbatim matters: the library's accessor discards the
    version and the sampling flags, so a rebuilt string is not the one that arrived and an
    inbound ``-00`` would be re-emitted as ``-01``.

    Args:
      None.

    Returns:
      The run's traceparent, or None when there is neither an adopted context nor an open span.

    Raises:
      None. Logging must never fail a verb.
    """
    adopted = _ADOPTED.get()
    if adopted is not None:
        return adopted
    try:
        return lf.current_traceparent()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "structured logging: could not read the current traceparent (%s: %s)",
            type(exc).__name__,
            exc,
        )
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
