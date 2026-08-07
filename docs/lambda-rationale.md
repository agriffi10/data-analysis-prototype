# Lambda Rationale

Long-form reasoning that used to live as narrative module docstrings and inline comments in
`lambdas/`. Moved here when the Lambda tree adopted the Google-style docstring standard
(`docs/best-practices/python/python.md` §14): a docstring states the interface and the
short *why*, and anything longer than a paragraph belongs in a doc.

Read the entry for an area before changing it. Where a claim is already a settled project
decision, the authority is `docs/decisions.md` — this file records the working detail and
the evidence behind it, not the decision itself.

---

## `cpcommon/__init__.py` — the layer's import-free root

`cpcommon/__init__.py` must not import anything, and this is load-bearing rather than
tidiness (SPEC-137 FR-001).

Anything imported from the package root runs for every function that attaches the layer,
whether or not that function uses it. Three functions — `pre-signup`, `post-confirmation`
and `notifications-writer` — attach the layer for one or two modules and set almost none of
`cpcommon.config`'s environment.

**The original reason was a fail-fast, and it expired.** `cpcommon.config` used to call
`_require()` on six variables **at import time**, so a single import added to the root broke
all three at cold start — on `pre-signup` a Cognito trigger, so it broke sign-up itself. That
is not hypothetical: it shipped, and it broke sign-up for nine days. SPEC-156 FR-004 moved
that resolution to **first access**, because the eager version was also the reason
`notifications-writer` could not import `cpcommon.auth` and carried a second copy of the
fleet's JWKS verifier.

**The rule survives its original reason, on cold-start cost.** The root is imported by every
control-plane verb, so a submodule imported there is paid for fifteen times over —
`type_mapping` alone would pull polars, ~100 MB, onto functions that never read a Parquet
footer.

Pinned by `test_layer_import_safety.py`, which holds the property with **two** mechanisms
because neither covers the other: an AST scan of each singleton's whole file against a
per-function allowlist (it sees a `cpcommon` import in a **function body**, which runs on a
later branch rather than at cold start), and a **subprocess** import of each singleton with
the six variables withheld (it sees what a module actually *touches*, including through a
module it never names). An in-process test can do neither, because `conftest.py` stamps the
six variables before collection.

The package is a package (`python/cpcommon/`) rather than flat modules so its module names
(`config`, `auth`, …) cannot collide with the domain layers' or `shared-space-common`'s
under one pytest run.

## `cpcommon/ddl.py` — why the storage clause is injectable

Identifier quoting, the column body, `PARTITIONED BY`, the projection `TBLPROPERTIES` and
the statement assembly are shared across the arcs. The **storage clause** is deliberately
not (SPEC-111 FR-001/FR-002), because the two arcs disagree on purpose:

- table-builder writes JSON with the **OpenX** SerDe — its shipped behaviour, unchanged.
- data-quality writes it with the **Hive** SerDe, because AWS documents OpenX as
  potentially non-deterministic around nulls, and the whole data-quality JSON story is
  "a null means the key was missing".
- data-quality also builds a single-column raw-line table with `LazySimpleSerDe` that has
  no analogue in table-builder at all.

So `storage` is injectable: pass nothing and you get the table-builder defaults; pass a
`Storage` and you get exactly your clause plus your properties. A domain's SerDe choice
belongs in that domain's layer, next to the reason for it — not in a shared `if fmt ==`
ladder that reads as if one of the two arcs is wrong.

The consolidation itself (from `table-builder-infer-schema/ddl.py`, SPEC-069) was the same
move as `cpcommon.type_mapping`: the projection-props logic is fiddly, easy to get subtly
wrong, and must not exist twice.

## `cpcommon/type_mapping.py` — polars in a layer every verb attaches

This module imports **polars**, and `cpcommon` is attached to **every** control-plane verb.
Importing it from a verb that does not also attach a polars layer is an `ImportError` at
**cold start**. Only two functions carry polars today:

- `table-builder-infer-schema` (the `table-builder-polars` layer)
- `data-quality-inspect-source` (the `data-quality-polars` layer)

Every other verb — 15+ of them — attaches `cpcommon` without polars.

Living here is safe **only** because `cpcommon/__init__.py` imports no submodules, so this
file is loaded if and only if something explicitly imports it. Do **not** add
`from . import type_mapping` to that `__init__`: it would break every polars-free verb the
instant it deployed, which is the shape of the PR #196 outage — a shared layer's import-time
requirement that only some functions can satisfy.

Adding a polars-carrying verb? Give it `cpcommon: true` **and** a polars layer in
`deploy-lambdas.yml`'s matrix, and check the combined per-function size guard.

## `cpcommon/observability.py` — the field rule's edges

The field rule itself is a **Key Decision** and lives in `docs/decisions.md` (SPEC-130) —
read it before instrumenting any call site. Recorded here are the three things about it that
are working detail rather than decision.

**The stack-trace exemption, decided rather than overlooked (user decision, 2026-07-23).**
`log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span, and
that walks the `__cause__` chain — so an exception whose cause quotes a cell (a polars parse
error naming the value it could not convert) carries that text into `error.stack` no matter
what a call site does. Accepted, not stripped: `logs/` is admin-only, and a stack is
diagnostic metadata an admin debugging a failed run needs. The rule binds what a verb
*chooses to put in a field*; it does not bind an automatic traceback. **Do not read a stack
trace as licence to relax the field rule.** Pinned by
`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`.

**The email hazard is mechanical, not hypothetical (SPEC-137 FR-005).** A Cognito trigger
event carries `request.userAttributes.email`, so a single `info("signup", event=event)` — the
most natural line anyone writes while debugging a trigger — publishes it. **Never log a raw
trigger event, an attributes map, or any dict you did not build field by field**: the leak
arrives nested, where a field-name check cannot see it. Usernames are a different case and
are *not* sensitive here — the username already is the S3 prefix, the principal tag and the
Glue database name (SPEC-033), so it is the primary key of every operator-facing record
already.

**One run is nine traces, not one.** A data-quality run is nine Lambda invocations and
`log-foundry`'s trace context is per-process, so `trace_id` never crosses a Lambda boundary
and `parent_span_id` is always null at a handler's root span. Correlate on
`fields.request_id` instead (SPEC-128 FR-002). The fix, when it is worth the cost, is
`lf.continue_trace(traceparent)` — shipped as of log-foundry 0.3.0 — plus threading the
traceparent through the Step Functions state payload on every state, exactly as `reportKey`
is threaded today. Deliberately sequenced after the pipe is proven live.

## `cpcommon/config.py` — sizing `REFRESH_MAX_DEFINITION_BYTES`

The refresh path's definition cap is **40 KiB**, and it is deliberately not tscommon's
`SHARE_MAX_DEFINITION_BYTES`. That 32 KiB was measured for table-share's 50-recipient Map,
where the definition is copied into every item; table-builder has no Map.

What rides on a refresh state instead is one definition plus what `infer-schema` then adds
to the **same** state — its own inferred columns and the generated DDL. **Columns therefore
ride three times** while table properties ride once, so the worst case is a definition spent
entirely on columns (an ordinary flat Parquet table), not a mixed one. Measured at that
composition by `test_load_table_definition.py`:

| cap | columns | whole state | % of 256 KB |
|---|---|---|---|
| 32 KiB | 713 | 92,331 | 35% |
| **40 KiB** | **891** | **115,293** | **44%** ← chosen |
| 48 KiB | 1,069 | 138,255 | 53% ← over half; rejected |

Breaching the 256 KB state-payload limit raises `States.DataLimitExceeded`, thrown **outside
every Catch** — no recorded outcome and no notification, on a request that already did all
its work. So an oversized table is refused up front as a whole-request terminal.

## `table-builder-apply-refresh` — what the in-place update does *not* retire

Stated rather than implied, because SPEC-144 FR-006 AC1 claimed a serialization guarantee
that did not exist.

The Pipe still invokes `StartExecution` as `FIRE_AND_FORGET`
(`infra/modules/table-builder/pipe.tf`), so two refreshes on one database still overlap, and
**Glue offers no compare-and-set to close it**: `UpdateTable`'s `VersionId` is documented only
as "the version ID at which to update the table contents", alongside `TransactionId` and
`ViewUpdateAction`, with no precondition-failure error.

What changes is the **severity**. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions, and `ConcurrentModificationException` — which Glue
raises on genuine simultaneity — is retried. SPEC-157 owns closing the rest.

## `user-directory-build` — why the source is S3, not Cognito

Settled 2026-08-03, after reading `docs/transition_plan.md`.

**Today** Cognito is the complete record and S3 is not: the personal prefix is created *by the
browser* on the first visit to `/files` (`ensurePrefixMarker`, SPEC-014 — a deliberate
no-backend decision), so a confirmed user who never opened the file browser has no prefix.

**The transition reverses it.** `transition_plan.md` §2 item 7 settles that sign-in provisions
nothing — the sync pre-creates every space and `ensurePrefixMarker` is deleted outright (§6.3)
— while federated login makes `cognito:username` a synthetic `identitycenter_<subject>` value
(§6.1) and users appear in the pool only after their first sign-in. So S3 becomes complete and
Cognito becomes both incomplete *and* wrong-keyed.

**Do not "fix" this back to `ListUsers`, and do not add it as a union "to be safe":** a second
source with different completeness properties is a second thing to reason about every time the
directory looks wrong. A test asserts the module never imports or clientises Cognito.

**The document is advisory. A name's presence in it grants nothing.** No control plane reads
it, no membership check consults it, and no browser field refuses a name missing from it.
Existence is still decided where it always was — `admin_get_user` against the user pool — and
an unknown name is still reported back to the user as a notification. The residual gap (a
confirmed user who has never opened the file browser is absent until the transition lands) is
bounded: they can still be added, just without a suggestion.

## `dqcommon/config.py` — sizing the byte-scan budget

**Why the budget is per REQUEST, never per file.** An earlier version bounded it per file:
256 MiB × up to 1000 files ≈ 276 GB through one 1024 MB Lambda in 300 s ≈ **920 MB/s
sustained**, against a real-world ~60–100 MB/s. It would have passed on a three-file fixture and
timed out in production — the exact error class this arc's re-architecture exists to eliminate.

**`DQ_SCAN_MIN_SAMPLE_BYTES` — the second disaster, which the byte budget does not prevent.**
Bytes are not the only cost; **requests** are. A flat 1 head + 20 ranged reads per file is
**21,000 sequential GetObjects** on a 1000-file manifest. At ~30 ms round-trip each that is
~630 s against the function's 300 s ceiling, while reading only the 2 GiB the byte budget
permits. It would have timed out on exactly the large folders the budget rewrite was meant to
save, for a completely different reason.

So a file's share only buys a ranged read when that read is worth a round trip. Measured across
the range (share = 2 GiB / fileCount, head = half of it):

| files | samples | GETs | time |
|---|---|---|---|
| 1 | 20 | 21 | ~36 s |
| 12 | 20 | 252 | ~43 s |
| 100 | 2 | 300 | ~44 s |
| 1000 | 0 | 1000 | ~65 s — 21,000 GETs / ~630 s without the floor |

Both costs are now bounded: never more than `DQ_SCAN_TOTAL_BYTES`, and never more than ~1000
requests. At 1000 files no sample clears the floor, so a file's 2 MiB share buys only its head
window — `head = int(share * DQ_SCAN_HEAD_FRACTION)` = **1 MiB**, and the 1 MiB remainder is
under `DQ_SCAN_MIN_SAMPLE_BYTES`, so it buys no ranged read at all. That is the right trade: one
contiguous 1 MiB read beats 21 scattered 100 KiB ones for finding a corrupt export, and the
report says the coverage is sampled either way.

## `shared-space-common/registry.py` — why a membership write is a delta

`save_members` takes **deltas** (`add=`, `remove=`, `acknowledge=`) and derives the new roster
inside its own compare-and-swap. It used to take the roster the caller had computed from
`event["registry"]` — a snapshot read before the request began — and assign it over the
freshly-read record. So the CAS re-read the record and then overwrote the one field it exists to
protect with a stale value: two overlapping requests on one space were **last-write-wins on the
roster**, and a concurrent remove reinstated a just-added member (SPEC-151 FR-004).

Nothing serializes those requests. `shared-spaces/pipe.tf` is `FIRE_AND_FORGET` and the FIFO
group id is one global constant, which `casio`'s own module docstring says outright.

**Four callers, not three.** `acknowledge-membership` is one too, and it is the only one that
*adds* to `acknowledged`. Left out of the conversion, it would have kept passing a whole computed
list and kept the defect.

**`status` is no longer written by this path.** It used to be forced to `"active"`
unconditionally, which let a membership write racing a delete return a `deleting` space to
`active` — the cascade would then run against a record claiming to be healthy. Only a
`setdefault` remains, to heal a record written before the field existed.

## `tscommon/config.py` — sizing the three share caps

**`SHARE_MAX_RECIPIENTS = 50`.** The disaster this prevents is not the fan-out — it is the
Map's **result**. Each item contributes a summary entry to `$.recipientResults`, and a failed
entry carries the raw Step Functions `{Error, Cause}` (PR #252 — the ASL decode that used to
shrink it raised an uncatchable `States.Runtime`, so the raw object is what makes the reason
recoverable at all). Measured against a real Cause from execution history: **~570 bytes per
failed recipient, ~1.2 KB with a verbose Athena `StateChangeReason`**. Step Functions caps a
state payload at 256 KB, and breaching it raises `States.DataLimitExceeded` **on the Map** —
which routes to the whole-request failure state and destroys every per-recipient outcome the
Map exists to preserve, turning a partial success into a total failure.

Measured, not guessed: at the bounded worst case (a maximum-length detail plus a deep stack)
100 recipients reach ~154 KB — under the limit, but the request object rides in the *same*
payload, so that margin is thinner than it looks. 50 lands at ~68 KB, 26% of the limit.
`test_the_whole_map_state_stays_under_the_payload_limit`
(`lambdas/control-plane-common/test_state_machines_cpcommon.py`) computes this from the
constants, so changing either without re-checking the other fails the build. The other half of the bound is
`cpcommon.athena` truncating the raw Athena reason: a cap on **count** alone cannot bound a
32 KB Cause, which breaches at **seven** recipients. It is also a sane product limit in its own
right — 1000 objects × 50 recipients is 50,000 `CopyObject` calls, and there was previously no
cap at all.

**`SHARE_MAX_DEFINITION_BYTES = 32 KiB`.** The last unbounded term on the Map's state. Moving
the object list to a pointer removed the big one, but `tableDefinition` still rides inline —
and it is **user-controlled**: it clones the source's columns (name/type/comment) and its Glue
table properties verbatim, and a user can set both from the query workspace. Measured with the
plan already by pointer, 50 recipients all failing:

| definition | state | % of 256 KB |
|---|---|---|
| 300 columns, no comments | 89 KB | 34% |
| 1,000 columns, no comments | 123 KB | 47% |
| 1,000 columns, 255-char comments | 393 KB | **150% — breach, after the pointer** |

32 KiB is generous — roughly 600 plain columns — and lands the worst case near 41%.

**`SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES`.** Sized so a recipient Map item's parallel
server-side copy finishes comfortably inside copy-objects' 900s timeout (architecture §12).

## `cpcommon/bounded_read.py` — why polars' cloud reader is not used

Every control plane that infers a schema wants the same thing: the first few bytes of an
object, never the whole object (a source file can be hundreds of GB and a Lambda has no disk
for it). The obvious way — point polars at an `s3://` URI and let its `object_store` cloud
reader fetch only the byte ranges the scan needs — **does not work in Lambda**. It fails
with `failed to allocate {filesize} bytes to download uri = s3://…`: object_store gives up
on ranged access and tries to download the entire object, even when the role's credentials
are handed to it explicitly via `storage_options`. boto3 in the very same invocation
authenticates and reads fine.

The working pattern, proven live for data-quality (PR #242) and ported after the identical
failure hit table-builder on a real user's 31 MiB CSV: fetch a **bounded head** with boto3
and hand polars an in-memory buffer, which polars reads without touching object_store. The
no-full-download property is kept — reading stops after `max_lines` newlines or `max_bytes`,
whichever comes first, and the rest of the body is abandoned.

That covers formats whose schema lives at the **start** of the file: a CSV header is line 1,
and JSON type inference samples the first N lines. **Parquet keeps its schema in a footer at
the end**, which a head read cannot reach — so it gets `S3RangeReader`, a file-like object
serving `read`/`seek` from boto3 ranged GETs. Handed to `polars.read_parquet_schema`, that
fetches only the footer region: measured at **64 KiB and 4 GETs** for both a 0.3 MB and a
25 MB file, i.e. bounded by metadata size, not object size.

It must be `read_parquet_schema`. Over a Python file object, `scan_parquet` slurps the
**whole** object in a single `read()` (measured on polars 1.12.0), so a lazy reader buys
nothing there.

**Nothing in this codebase uses object_store any more**, which is the point: the one reader
that does not work here is no longer on any path, and no call site depends on credentials
being threaded into it.

## `cpcommon/errors.py` — why `failure_reason` exists in Python

No ASL state may decode an error `Cause`, and trying anyway killed executions outright.
The three control planes used to decode it in a `Pass` state:

```
"cause.$": "States.StringToJson($.error.Cause)"
```

A `Pass` state cannot `Catch`, and `States.StringToJson` raises `States.Runtime` on anything
that is not a JSON string. Verified against the live service with TestState:

| Error shape | Result |
|---|---|
| Lambda `TerminalError` (JSON Cause) | SUCCEEDED |
| `States.Timeout` (no Cause key) | `States.Runtime` — "JsonPath … could not be found" |
| `States.DataLimitExceeded` (prose) | `States.Runtime` — "Cannot convert String to Json" |
| `Lambda.Unknown` (prose) | `States.Runtime` — "Cannot convert String to Json" |

Three of four realistic shapes killed the execution **before** the recorded-failure and
notify states — so on precisely the failures a user most needs to hear about (a timeout, an
oversized payload, a Lambda that died without a handled error) they were told nothing at
all. Python can do this safely, so the decode moved to `cpcommon.errors.failure_reason` and
the machines pass `$.error` through untouched. See the `decisions.md` entry (#252).

**Why the reason split is gated on `errorType`.** `TerminalError` composes its message as
`f"{reason}: {detail}"` from a registered, colon-free code, so splitting on the first colon
reverses exactly what the raise site did. Every other exception's message is prose, and
splitting it yields prose dressed up as a reason code. Both of these are routine:

```
ClientError    -> "An error occurred (AccessDeniedException) when calling the CreateTable operation"
TransientError -> "listing objects"
```

Neither is a registered code, so a resolver falls back to the generic anyway — but the value
is logged, recorded and handed onward, and raw engine prose must never travel as if it were
a code (SPEC-106 FR-008).
