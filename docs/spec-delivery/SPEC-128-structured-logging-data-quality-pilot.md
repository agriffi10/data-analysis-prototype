# Completed Spec — SPEC-128: Instrument the Data-Quality Control Plane

## What shipped

- `@observability.traced("<verb>")` + `init(service="data-quality")` on **all nine** verbs.
- `LOGS_QUEUE_URL` + `ENV_NAME` on the nine functions; **one** new IAM statement
  (`EmitStructuredLogEvents` — `sqs:SendMessage` on the logs queue ARN) on the shared execution
  role.
- `lambdas/data-quality-common/test_instrumentation_coverage.py` — enumerates the verb
  directories rather than listing them, so a tenth verb cannot be added without instrumenting it.
  It asserts the count **first**, so a glob that matched nothing could not make the file vacuous.

## Deviation from FR-002 (decided in-session)

`request_id` is stamped by `traced()` from the handler's own event, **not** by nine hand-written
`set_baggage` lines. FR-002's goal is that one run is one query and that the set cannot silently
shrink — and a correlation key added by hand in nine places is exactly what a tenth verb gets
added without. Stamping it at the single point that already wraps every handler makes it
structural. A verb with no usable id emits `request_id` **absent** rather than defaulted, which is
what FR-002 requires.

## Decorator order

`@traced` is **outermost**, above `@notifies_on_failure`. That decorator catches on its way out,
so if it were outermost the span would close `status="ok"` on an invocation that actually failed
and notified. Pinned by a parametrised test **and** confirmed live (below).

## What changed from earlier specs

Nothing behavioural. No state machine, no report shape, no notification contract, no runs index,
and no IAM beyond the one statement. The plan was **0 to add, 10 to change, 0 to destroy** — the
nine functions' env blocks and the one role policy, all in-place.

## Verification

Local: `pytest lambdas/` 1133 passed, `ruff` clean. Mutations: un-tracing one verb fails 2
coverage tests; swapping the decorator order fails the order test for that verb alone.

**Live, against the deployed plane (2026-07-23):** all nine invoked; **zero import errors**, so
the cpcommon + `log-foundry` import is safe at cold start on every one (FR-004 — the failure mode
no unit test reaches). The spans reached S3 within one sweep:

```
verb=validate-authorize   status=error  TerminalError
verb=inspect-source       status=error  TerminalError
verb=create-temp-tables   status=error  TerminalError
verb=start-profile-query  status=error  TerminalError
verb=byte-scan            status=error  TerminalError
verb=assemble-report      status=error  TerminalError
verb=check-query          status=ok
verb=drop-temp-tables     status=ok
verb=notify-failure       status=ok
```

All nine distinct verbs, `service=data-quality` throughout. The six `status=error` rows are the
**live proof of the decorator order**: those verbs rejected the probe payload and the span saw the
real exception. With `@traced` inner they would have read `status=ok` — traces reporting a healthy
pipeline while users receive failure notifications.

FR-003 redaction: the only field key emitted across every event was `verb`. Zero JWT-shaped
strings, no credential-shaped content.

**Live end-to-end (2026-07-23):** two real checks were run from the UI. Both completed all seven
executed verbs with `status=ok`, and both are recoverable as one query on `fields.request_id` —
FR-002's join key, proven live:

```
request_id=bb00a730…   inspect-source → create-temp-tables → start-profile-query →
                       check-query → byte-scan → assemble-report → drop-temp-tables   (~45s)
request_id=c2b433c2…   the same seven                                                  (~37s)
```

**That run also found a bug this spec shipped.** `validate-authorize` logged `request_id=None` in
both runs: `traced()` read `event["requestId"]`, but a validate verb's event is the **raw SQS
array** the EventBridge Pipe forwards, whose single record's `body` is a JSON *string*. So the one
verb that ESTABLISHES the request was the one verb that could not be joined to its own run.

The synthetic `{}` probe could not have caught it — with no id anywhere, "absent because there was
none" and "absent because we failed to extract it" look identical. Fixed by teaching
`_extract_request_id` both entry-point shapes, with tests built on a realistic Pipe envelope
rather than `{}`.

**Still not done:** the token grep against a real token.

**SPEC-074 help sweep: no-op** — nothing user-facing changed.

## Follow-up (FR-005)

One run is still **nine traces**, correlated on `fields.request_id`. Real stitching needs
`lf.continue_trace()` — which upstream now ships as of log-foundry 0.3.0 (log-forge SPEC-014), so
the remaining cost is threading a `traceparent` through the Step Functions state payload on every
state, as `reportKey` is threaded today. Deliberately sequenced after the pipe was proven live;
it now has been.
