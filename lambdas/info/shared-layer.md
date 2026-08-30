# The shared layer — `control-plane-common/cpcommon/`

Every control-plane verb attaches this layer, and the API attaches it too. `cpcommon` owns the
**algorithm**; a domain layer owns its **wording**. The rule that keeps it that way, and the reason a
domain layer must never import another, are in
[`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md).

This page is the long-form *why* behind the modules whose reasoning outgrew a docstring — sizing
evidence, rejected designs, and the traps. Read the entry for the module you are changing; you will
not need the rest. Where a claim is a settled project decision, the authority is `docs/decisions/control-planes.md`
— this records the working detail and the evidence, not the decision.

| Module | Holds |
|---|---|
| `actor` | the trusted actor a message carries — and it may not verify one |
| `athena` | the bounded query runner and the DDL poll |
| `auth` | token verification and the principal it yields — **the API's only, now** |
| `bounded_read` | reading a bounded head of an object without polars' cloud reader |
| `cas` | the ETag compare-and-swap retry loop |
| `clients` | lazy, cached boto3 and JWKS client factories |
| `cognito` | user pool lookups |
| `columns` | the column-name rule |
| `config` | env-derived configuration, resolved on first access |
| `ddl` | `CREATE EXTERNAL TABLE` generation, with the storage clause injected |
| `errors` | the error vocabulary, and the one decoder of a Step Functions `Cause` |
| `events` | the SQS envelope parse |
| `glue` | Glue catalog reads shared by the planes that read a live table |
| `jwks` | the cooldown JWKS client |
| `lock` | the object-lock protocol: conditional acquire, staleness steal, release by overwrite |
| `messages` | the failure-message resolver a domain layer extends |
| `notify` | the FIFO notifications send and its dedup id |
| `observability` | structured logging — the one door to `log-foundry` |
| `paths` | key containment: is this key inside the root I authorized? |
| `registry` | shared-space registry reads |
| `results` | where a plane's Athena statements write their output |
| `s3_listing` | listing past the 1,000-key pagination boundary |
| `transfer` | the bulk-copy engine: manifest writer, batch copier, Map Run result reader |
| `type_mapping` | the one polars→Hive type mapping |

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

## `cpcommon/actor.py` — why the reader may not verify

`trusted_actor` takes the `identity` block the API stamped onto a queue message and returns the
actor it names. It makes no network call, reads no environment variable, and imports neither `jwt`
nor `cpcommon.auth` — asserted by an import sweep over the module, not by a docstring asking
nicely.

**The prohibition is the interesting part, because the obvious instinct is the wrong one.** A
reader that could fall back to verifying a token looks like defence in depth and is the opposite:
it is a second answer to a question already answered, in a module whose whole premise is that the
question was answered elsewhere. The fleet had five of those and they had drifted; the cost of the
fifth was not that any one was wrong, it was that nobody could say which one a request had used.

What the trust actually rests on is **who may write the queue**, not on a signature. The API's
execution role holds `sqs:SendMessage` on the eight request queues and the browser's role does not
— SPEC-200 FR-008, enforced by a `.tftpl` sweep derived from the modules on disk rather than from a
list. If that grant is ever widened, no amount of verification here would help, because a principal
that can write the queue can write the block.

**Two rules earn their keep against fixtures that all look alike.**

The flat top-level `actor` field is never consulted. On four planes that field held the raw ID
token during the cutover, and a raw JWT and a username are both non-empty strings — so a reader
shaped "take the block, fall back to the field" passes every well-formed fixture ever written and
builds an S3 prefix, a Glue database name and a notification recipient out of a 900-character
token on the first message from before the flip. The block goes into a local and nothing else is
read at all.

And the actor is checked against `config.CATALOG_IDENTIFIER_RE` rather than for presence, which is
what makes the JWT case *fail* rather than merely be odd. Mutating that check to a truthiness test
reddens the reader's own suite in seven places — and leaves every plane's suite green, which is the
measurement that says the shape rule is the guard and the call sites cannot be.

`assurance` fails closed on anything outside `ACCEPTED_ASSURANCE`, **including an absent value**.
Nothing mints anything but `interactive` today, so the refusal is unreachable in production, and
that is its purpose: when a later arc mints a machine principal, every plane refuses it until that
plane is deliberately widened, rather than silently treating it as a person at a keyboard. The set
is defined once, here, and a sweep fails if a second module declares its own.

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

The field rule itself is a **Key Decision** and lives in `docs/decisions/control-planes.md` (SPEC-130) —
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
the machines pass `$.error` through untouched. See the `docs/decisions/control-planes.md` entry.

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

## `cpcommon/transfer/config.py` — sizing the Distributed Map

**`MAX_ITEMS_PER_BATCH` (50 until SPEC-161, now 8).** A batch IS a child execution's input, and Step Functions caps that
at **256 KB**. The bound is taken against S3's worst case rather than a typical key, because a key
is user-controlled and the failure it prevents is a whole batch refused at start time: a source key
and a destination key can each be 1024 bytes, and a bucket name 63, which puts one manifest item
near **2.3 KB**. At 50 items that was ~112 KB — under half the limit — and at 8 it is ~18.9 KB.
`test_a_worst_case_batch_stays_under_the_input_limit`
(`lambdas/control-plane-common/test_transfer_cpcommon.py`) **computes** that rather than asserting
the number, so raising the constant without re-checking it fails the build.

**The second bound is time, and SPEC-161 is where it stopped being slack** — it is now the binding
one, and it is why this constant is **8**. The sentence that used to sit here read "50 server-side
copies on the bounded pool finish far inside copy-objects' 900-second timeout even when several go
multipart", and that was true only because table-share's TOTAL cap was 20 GiB, so a batch could
never exceed a whole table. Raising the total to 1 TiB removed that implicit bound.

**The bound is a MAKESPAN, and `items x object-size` is NOT it** — that product was the first
replacement tried and it is wrong for the same reason the sentence before it was. `copy_batch`
hands one WHOLE object to each of `COPY_CONCURRENCY` workers and `copy_one` part-copies serially,
so a batch costs `ceil(items / COPY_CONCURRENCY)` **rounds of its slowest object**, not its total
bytes over an aggregate rate. **8 = `COPY_CONCURRENCY` makes that ceiling one**, so a batch costs
one object's time — 429 s at `SHARE_MAX_OBJECT_BYTES` 10 GiB, inside two thirds of the 900 s
timeout. At 10 items it was two rounds and 859 s; the product reading of the same configuration
said 537 s and stayed green. `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the
makespan and `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality.
**These constants can no longer be changed independently of each other or of table-share's
per-object cap.**

**`MAP_MAX_CONCURRENCY = 20`.** Deliberately not the **10,000** default. Each child execution
invokes a Lambda that opens up to `COPY_CONCURRENCY` (8) S3 connections, so the default would put
the account's entire Lambda concurrency and a very large S3 request rate behind one user's share —
and the throttles that follows would be attributed to whatever else was running. 20 gives up to 160
in-flight copies, which is throughput without a self-inflicted `SlowDown`.

**Both numbers exist twice** — here for the verb, and in `infra/modules/table-share/locals.tf` for
the rendered ASL, because Terraform cannot import Python. `test_the_maps_sizing_matches_the_constants_the_verb_reads`
(`lambdas/table-share-common/test_state_machine_table_share.py`) asserts the pair still agree. Two
homes for one number is how a batch grows past the limit it was sized against while its own test
still passes.
