---
type: Decision
title: "A run is ONE trace on the success path, and the extractor is a security boundary (SPEC-225)"
description: "**A run is ONE trace**, adopted from FIVE event shapes — the state payload, the Pipe envelope, a Distributed Map's `ItemBatcher.BatchInput`, an inline Map's `request`, and the forwarded envelope a failure terminal carries on the state as `raw`, which is the only one of the five reachable when the error REPLACED the state. **The shape list is a security boundary**: the body branch fires for a LIST only, because a bare dict's `body` is an API Gateway caller's own, and nothing overwrites an adopted trace. Adoption comes **after** the per-invocation reset, which clears it; `run_traceparent()` returns the value **verbatim**, since rebuilding it re-emits an inbound `-00` as `-01`. A Map's `BatchInput` pair is **per-plane** — table-share's state has no `requestId`, so demanding one is `States.Runtime` on every share. The failure path is threaded too, since SPEC-227, and the case that could not be threaded is CARRIED instead since SPEC-228."
---

The traceparent is minted at the **API** — the one place a run begins — written into the message
by `enqueue.build_message`, and adopted by `traced` before the span opens, so a verb's root span
parents to the API's. `request_id` **stays**: it is the join key for anything outside the trace — **including the failure path whose error replaced the state, where the seed nulls it and the notifier recovers the caller's own id from the forwarded envelope instead** (the SPEC-127→129 entry above carries the measurement of what that path looked like before),
and table-share carries none at all.

**Five event shapes**: the state payload, the EventBridge Pipe envelope, a Distributed Map's
`ItemBatcher.BatchInput`, an inline Map's `request` block, and the forwarded envelope a failure
terminal carries on the state as `raw`. The Map ones carried no correlation value of any kind
before SPEC-225, which is why nine Map-child verbs could not be joined to their own run; the fifth
is the failure path's, and it is a walk over the SAME envelope the Pipe branch reads rather than a
second parser, so the list-only narrowing below is enforced once.

**The shape list is a security boundary, not a convenience.** The request-id walk
(`request_id_of`) used to fall back to parsing a bare dict's `body`, and for an API Gateway payload-2.0 request that `body` is
**the caller's own HTTP body** — so a caller could name this service's correlation key. Latent for
the request id, because the router overwrites it with the gateway's; **not** latent once a
traceparent travels the same walk, since nothing overwrites an adopted trace. The body branch is
narrowed to a **list**, which closes both.

Three mechanisms that each look like a detail:

- **Adoption comes AFTER the per-invocation reset.** `reset_context` clears an adopted context as
  well as baggage (SPEC-224), so adopting first means the reset erases it. The ordering is the
  whole reason this spec was sequenced behind that one.
- **`run_traceparent()` keeps the adopted value VERBATIM**, in a `ContextVar` of this module's own.
  The library's accessor returns `(trace_id, parent_span_id)` with version and flags discarded, so
  a rebuilt string re-emits an inbound unsampled `-00` as `-01` — a sampling decision silently
  reversed on the way through every verb.
- **A Distributed Map's child cannot see the parent state**, and all six read a JSONL manifest
  through `ItemReader` with no `ItemSelector`. `ItemBatcher.BatchInput` is the only place a
  per-run value can travel; the manifest would repeat it on every line of a dataset holding tens
  of thousands. The pair is **per-plane** — table-share's state has no `requestId`, and an
  unconditional one there is an uncatchable `States.Runtime` on every share.

Rejected: threading it through `ItemSelector` (none of the six has one, and adding one copies the
whole parent state into every item); writing it into the manifest (repeats per line); and reading
it from the traceparent header (the planes are entered by SQS, not HTTP).

**What is owed**: a real run's records carrying one `trace_id`, and — falling out of the same
reading, since archive's Maps carry the block — an execution proving `BatchInput` reaches an
`ItemReader`-fed Map's child. AWS documents that pairing nowhere and `test-state` refuses a Map's
child outright. Partly discharged: the service's own definition validator accepts all eight
templates and refuses a `BatchInputTypo` as unsupported, so the field is real and a red first
apply is ruled out.
Detail: `spec-delivery/SPEC-225`.

## History

### 2026-09-08

- **Settled:** SPEC-225.
