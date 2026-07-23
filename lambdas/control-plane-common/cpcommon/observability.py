"""Structured-logging bootstrap and narrative for the control-plane verbs (SPEC-127/130).

Seven names — ``init``, ``flush``, ``traced``, ``step``, ``info``, ``warning``, ``error``::

    from cpcommon import observability

    observability.init(service="data-quality")

    @observability.step("probe-columns")
    def _probe_columns(bucket, key): ...

    @observability.traced("inspect-source")
    def handler(event, context):
        observability.info("listed source", objects=142, format="csv")

``init`` configures ``log-foundry`` once per container; ``traced`` opens a span around the
handler and flushes on the way out, on both the success and the failure path; ``step`` opens a
child span around one named internal step; the three level emitters attach an event to whichever
span is currently open.

**Nothing outside this module imports ``log_foundry``** (SPEC-130 FR-001). The emitters exist so
that the invariant below has one door rather than thirty-four, and an emitter is a far more
attractive place to violate it than a decorator, because it sits in the middle of business logic
where an exception is a real failure path.

**Messages are literals; everything variable is a field.** ``info("appended", events=12)`` groups
across every invocation and can be counted, filtered and alerted on. ``info(f"appended {n}
events")`` mints a distinct message string per run and can do none of those things.

**What may become a field value.** ``logs/`` lives in the admin bucket and is read by
administrators for administrative purposes, and that destination is what makes user-derived
*metadata* the right thing to log rather than the wrong thing — an operator debugging a failed
run needs to reach the object (user decision, 2026-07-23).

* **Permitted, and encouraged where it aids debugging:** file names, S3 keys, prefixes and
  locations; usernames; database, table and column names; space names; counts, sizes, durations,
  booleans, attempt numbers, enum-ish states; ``request_id``, ``service``, ``verb``. Usernames are
  **not** sensitive here — the username already *is* the S3 prefix, the principal tag and the Glue
  database name (SPEC-033), so it is the primary key of every operator-facing record already.
* **Never, and the line is absolute: data from inside a file.** A cell value, a sampled row, a
  parsed record, a decoded byte range, a rendered result set. Any of it can be PII, none of it is
  needed to debug a control plane, and ``logs/`` is retained forever. Column *names* are schema
  and are permitted; column *values* are file contents and are not.
* **Never, regardless of provenance: tokens, credentials, and email addresses.** A bearer
  credential is not metadata — an expired ID token is still a signed assertion about a real person
  (which is why ``dlq_drain._redacted`` scrubs every known token field before its forensic line).
  An email is excluded for a different reason: unlike a username it appears nowhere else in these
  operator records, carries no operational meaning here, and would be the only personal contact
  detail in a prefix retained forever.

**The emitters do not enforce that rule at runtime, deliberately.** It turns on *provenance* — did
this value come from inside a user's file — and no filter over a field name or a value shape can
see provenance. A filter that looked like enforcement would be worse than none, because it would
be trusted. Enforcement is review plus the per-call-site acceptance criteria in SPEC-131/132/133.

**The narrative never reaches the console.** These events go to the logs queue and from there to
the admin bucket (user decision, 2026-07-23). ``log-foundry``'s ``echo=`` writes a synchronous
console line and is prohibited repo-wide; the emitters pass ``echo=False`` unconditionally and
drop-and-warn an ``echo`` passed as a field. The one exposure is named rather than closed — see
``init``'s ``StdoutSink`` fallback.

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
import json
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
        #
        # message_group_id is the SERVICE, overriding log-foundry's default of one group per
        # trace_id. The library's default maximises parallelism (SQS delivers separate groups
        # concurrently); a per-service group deliberately trades some of that for a simpler
        # ordering story — one control plane's events arrive in the order it emitted them, and
        # the sweep is a single consumer anyway, so the parallelism the default buys is not
        # parallelism anything here can use. (User decision, 2026-07-23.)
        #
        # The sink infers FIFO from the `.fifo` queue URL, so nothing here has to declare it,
        # and it mints a UUID MessageDeduplicationId per event — which is why the queue does not
        # (and must not) enable content-based deduplication.
        sink: object = SQSSink(
            LOGS_QUEUE_URL, client=clients.sqs(), message_group_id=service
        )
    else:
        from log_foundry.sinks.stdout import StdoutSink

        # The one named exposure to SPEC-130 FR-006's "the narrative never reaches the console":
        # with no queue URL the events go to stdout, and stdout in Lambda is CloudWatch. The
        # fallback STAYS anyway, because it is the cold-start safety property this whole module
        # is shaped around — a function missing the variable must log to stdout rather than
        # crash a control plane (PR #196). What bounds it: these same functions' existing
        # logging.getLogger() calls already put the same keys, prefixes and locations in the
        # same log group today, so the fallback exposes nothing CloudWatch does not already hold.
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
        verb: The control-plane verb name. Names the span AND rides as baggage on every event
            in it, children included.
    """

    def decorate(fn):
        span = lf.trace(
            # SPEC-130 FR-002, 2026-07-23. Without `name`, log-foundry falls back to
            # `fn.__qualname__` and EVERY root span in the fleet reads `function: "handler"`,
            # because every Lambda entry point in this repo is named `handler`.
            #
            # This is a DISCONTINUITY in a store retained forever (SPEC-127 FR-009): the day
            # object spanning the cutover holds pre-change spans saying "handler" and
            # post-change spans saying the verb. Accepted, not migrated — the objects are
            # appended NDJSON, and rewriting them to tidy a field boundary would risk a day of
            # logs to save a WHERE clause. `fields.verb` is populated on both sides of the
            # cutover, so a query filtering on the verb spans it either way.
            name=verb
        )(fn)

        # functools.wraps because Lambda resolves the entry point as `module.handler` BY NAME —
        # an unwrapped wrapper would be invisible to the runtime.
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
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
    """Open a **child span** around one named internal step (SPEC-130 FR-004).

    Turns "the verb took 8 seconds and failed" into "the listing took 40ms, the column probe took
    7.9s and raised" — the child gets its own ``function``, ``duration_ms`` and ``status``,
    parented to the handler's span inside the same ``trace_id``.

    A **thin** alias for ``lf.trace(name=...)``, and it stays one on purpose. The library's
    decorator is non-swallowing by design — it records the failure and re-raises the original
    exception unchanged — and that property has to survive contact with this wrapper. A step that
    swallowed would convert a terminal failure into a silent wrong answer, and would do it under
    ``@traced``, which sits outermost above ``@notifies_on_failure``. Nothing to add here is worth
    putting a ``try`` between a raise and its notification.

    Which functions get a step is a per-call-site decision, not one made here: every event is an
    SQS message and a line in a day object the sweep rewrites in full, so a step inside a per-item
    loop is a volume decision. SPEC-131 and SPEC-132 name their own steps and justify the count.

    Args:
        name: The step name, emitted as the child span's ``function``.
    """
    return lf.trace(name=name)


def info(message: str, **fields: object) -> None:
    """Emit an ``INFO`` event on the current span. Never raises.

    ``message`` is a **literal**; everything variable is a field. See the module docstring for
    that rule and for what may become a field value.
    """
    _emit(lf.info, message, fields)


def warning(message: str, **fields: object) -> None:
    """Emit a ``WARNING`` event — a degraded-but-continuing path. Never raises."""
    _emit(lf.warning, message, fields)


def error(message: str, **fields: object) -> None:
    """Emit an ``ERROR`` event — a path that failed. Never raises."""
    _emit(lf.error, message, fields)


def _emit(level_fn, message: str, fields: dict[str, object]) -> None:
    """Route one level event through ``log-foundry``, never failing the caller.

    Two things happen here and nowhere else.

    ``echo`` is **dropped and warned** rather than forwarded (SPEC-130 FR-006). It is an unusually
    quiet mistake: ``**fields`` swallows the keyword, so an author who sets ``echo`` on an emitter
    call gets neither a failure nor a console line — just a silently emitted field named ``echo``,
    which an operator reading the output cannot tell from an intentional one.

    Every exception is swallowed and logged at warning, protecting the invariant :func:`flush`
    protects: *logging must never be the reason a verb fails*. This matters most on the orphan
    path — an emitter called with no span open goes straight to ``sink.emit`` synchronously
    (``log-foundry`` FR-004), so a sink that raises raises **here**, in the middle of business
    logic, rather than on the worker thread where the span path absorbs it.
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
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning(
            "structured logging: event %r dropped (%s: %s)", message, type(exc).__name__, exc
        )


def _reset_baggage() -> None:
    """Clear trace baggage at the start of every invocation.

    Baggage lives in a ``contextvars.ContextVar``, and a warm Lambda container reuses the same
    context across invocations. Without this, a run that sets ``request_id`` leaves it set for
    the NEXT run — and a verb that fails to set one (a malformed event reaching notify-failure)
    would silently emit the previous run's id.

    That is worse than an unjoinable event: a fabricated correlation key merges two unrelated
    runs into one query result, and nothing about the output looks wrong. SPEC-128 FR-002 is
    explicit that a missing ``request_id`` must stay missing rather than be invented, and a
    leaked one is an invented one.

    Uses the library's private ContextVar because there is no public "clear" — ``set_baggage``
    only merges. Guarded so a library refactor degrades to a warning, never a failed verb.
    """
    try:
        from log_foundry import context as lf_context

        lf_context._baggage.set({})
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning(
            "structured logging: could not reset baggage (%s: %s)", type(exc).__name__, exc
        )


def _stamp_verb(verb: str) -> None:
    """Put the verb into baggage, so child spans and mid-span events inherit it.

    Baggage rather than ``lf.trace(defaults=...)`` (SPEC-130 FR-003). A span *default* applies to
    that span's own events and to nothing nested inside it, so the first :func:`step` child would
    carry ``request_id`` (baggage) but not the verb that produced it — joinable to its run, and
    unattributable to the verb.

    Must run **after** :func:`_reset_baggage`, which clears the whole mapping.

    Guarded like :func:`_stamp_request_id`: logging must never be the reason a verb fails.
    """
    try:
        lf.set_baggage(verb=verb)
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning(
            "structured logging: could not stamp verb (%s: %s)", type(exc).__name__, exc
        )


def _extract_request_id(event: object) -> str | None:
    """Pull ``requestId`` out of either event shape a control-plane verb can receive.

    Two shapes, because a control plane has two kinds of entry point:

    * **The Step Functions state payload** — a plain dict carrying ``requestId`` at the top
      level. This is every verb from ``inspect-source`` onward.
    * **The EventBridge Pipe envelope** — the raw SQS batch, a LIST whose single record's
      ``body`` is a JSON *string*. This is what every ``validate-authorize`` verb receives, and
      missing it is what made the verb that ESTABLISHES the request the one verb that could not
      be joined to its own run (found in live traffic, 2026-07-23; the synthetic ``{}`` probe
      could not distinguish "absent" from "not extracted").

    Never raises and never parses beyond what it needs. Deliberately does not call
    ``events.parse_sqs_request``, which raises ``TerminalError`` on a malformed envelope: a
    logging helper that can raise a domain terminal is a logging helper that can fail a verb.
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
    """Put the run's ``requestId`` into baggage, from the handler's own event.

    Done here rather than as a hand-written ``set_baggage`` line in each verb, for the reason
    SPEC-128 FR-001 gives about partial instrumentation: a run that shows eight of nine verbs
    looks like a run that *stopped* at eight, and a correlation key added by hand in nine places
    is one a tenth verb will be added without. Stamping it at the single point that already
    wraps every handler makes it structural instead of remembered.

    A verb invoked with no usable id (a malformed event reaching notify-failure) emits its span
    with ``request_id`` **absent** rather than defaulted — a fabricated correlation key silently
    merges unrelated runs, which is worse than an unjoinable event.
    """
    request_id = None
    try:
        request_id = _extract_request_id(event)
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning(
            "structured logging: could not read request_id (%s: %s)", type(exc).__name__, exc
        )
    if not request_id:
        return
    try:
        lf.set_baggage(request_id=request_id)
    except Exception as exc:  # noqa: BLE001 — logging must never fail a verb
        logger.warning(
            "structured logging: could not stamp request_id (%s: %s)", type(exc).__name__, exc
        )
