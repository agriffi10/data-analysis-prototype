# Spec: Results Conversion — The Plane, the Request Contract & validate-authorize

**ID:** SPEC-221
**Status:** Draft
**Last Updated:** 2026-09-05
**Depends On:** SPEC-187/189 (the file-ops plane as the pattern, and its destination rules), SPEC-200 (the enqueue paths and the `identity` block), SPEC-152 (`NotifyFailure` on every plane), SPEC-126 (DLQ drain), SPEC-218 (one builder per app-managed path — the results prefix this plane checks ownership against)

## Overview

A user can save a query's result set as a CSV today, because Athena already wrote one. Saving it as
Parquet, JSON or Excel means producing a new file, and that work belongs on a control plane: it
reads a result object of unbounded size, it needs polars, and it must never run inside a request.
This arc adds an eighth plane, **results conversion**, which takes a finished Athena execution and
writes its result set into a space the user may write to, in the format they chose.

This spec builds the plane and its front door and nothing that converts: the queue, the pipe, the
state machine, the execution role, the `rccommon` domain layer, the API route that enqueues a
request, and the two verbs that decide whether a request may proceed — **validate-authorize**, which
proves the actor may write the destination and owns the execution, and **describe-results**, which
reads the result set's columns, types and size and refuses one the converter cannot hold. The
machine ends in a placeholder terminal; SPEC-222 adds the converter and the success notification,
and SPEC-223 the browser surface.

Two properties are settled here because everything downstream rests on them. **The input is the
execution's result object, never the source table.** Most tables are Parquet, some are CSV or JSON,
and none of that matters: Athena writes every result set as one CSV object under the actor's own
results prefix, so the converter reads one shape whatever it was queried from, and no second query
is started and nothing is billed. And **ownership is a question about a path**: an execution is the
actor's if Athena wrote its output under the actor's own results prefix, built by the one builder
the API writes with, so a guessed execution id names nothing the actor cannot already read.

## Scope

### In Scope

- `infra/modules/results-conversion/`: a **FIFO** request queue + DLQ, an EventBridge Pipe, a
  **Standard** state machine, one execution role, and the `rccommon` domain layer beside `cpcommon`.
- The **results-conversion request contract** the API enqueues, declared in Python with the
  TypeScript generated, and its FIFO `MessageGroupId` / dedup rules.
- The `resultsConversion.enqueue` route on the API.
- **validate-authorize**: read the `identity` block, authorize the destination space, contain the
  destination inside it, refuse the app-managed prefixes, and prove the execution is the actor's and
  finished with a result set.
- **describe-results**: the result set's columns and types from Athena's metadata, its size from
  S3, and the size cap that refuses what SPEC-222's converter cannot hold.
- A skeleton machine — `ValidateAuthorize → DescribeResults → Placeholder → Succeed` — carrying
  its `NotifyFailure` state before `Fail` on every failure path from day one, a top-level
  `TimeoutSeconds` and its `TIMED_OUT` rule.
- The plane's wiring into the fleet: the DLQ drain's queue list, the notifications writer's
  sender allowlist, the container image's requirements, and the deploy role's grants in their own
  PR before the module that needs them.

### Out of Scope

- Reading rows, writing any file, or any notification of success — SPEC-222.
- The browser: the format choice, the pre-flight collision probe, the enqueue service, Help —
  SPEC-223. Nothing a user can reach ships in this spec.
- Converting a **file** in a space (a CSV the user uploaded) rather than a query's result. The
  cancelled file-converter arc (SPEC-115 → 122) was that feature; this plane has no source other
  than an execution and grows none.
- Re-running the query in another format (Athena `UNLOAD`). It bills a second scan, writes several
  files under names Athena chooses, and cannot produce Excel.
- CSV as an output format. The CSV Athena wrote is copied by the existing synchronous path and this
  plane never re-serialises it.
- A per-destination lock. The write itself is conditional (SPEC-222 FR-005), which is the whole
  serialisation this plane needs.

---

## Functional Requirements

### FR-001: The plane

#### Description:

The infrastructure, following the shared control-plane pattern, plus every fleet-wide list a new
plane has to join.

#### Acceptance Criteria:

- [ ] A FIFO request queue and FIFO DLQ exist, with content-based dedup **off** (the request supplies
      an explicit `MessageDeduplicationId`), and a redrive policy onto the DLQ. The DLQ is this
      plane's own — it shares none.
- [ ] An EventBridge Pipe delivers to a **Standard** state machine, `FIRE_AND_FORGET`.
- [ ] One execution role serves every verb. An `rccommon` layer holds this plane's wording, reason
      codes and key layout, with `cpcommon` supplying every algorithm; a test asserts `rccommon`
      defines no CAS loop, no SQS parser, no message resolver and no lock.
- [ ] `TimeoutSeconds` is set **top-level** on the machine and ships together with its EventBridge
      `TIMED_OUT` rule into `NotifyFailure` — never `FAILED`. The ceiling is **provisional** here and
      SPEC-222 FR-005 re-derives it with the converter's budget, in the same test that sizes the
      converter.
- [ ] The request is small and bounded by its contract (FR-002 caps every free-text field), so the
      `TIMED_OUT` door reads the request from the event input as table-share's does. A test asserts
      the largest request the contract admits is under 32 KB, so the file-send-shaped
      `states:DescribeExecution` door is provably unnecessary — the number is measured from the
      contract, not stated.
- [ ] The plane's functions are declared through the `docker-lambda` module, so `lambdas/fleet.py`
      reads them from the Terraform sources with no list to be missing from; the image's import
      sweep runs every new handler; `lambdas/info/deployment.md` *Adding a function* is followed
      step for step and nothing is added to `.github/`.
- [ ] The plane's DLQ ARN is added to the DLQ drain's `dlq_arns`, and a test over the Terraform
      sources asserts every plane module's DLQ is in that list — the omission would be a plane whose
      dead letters nobody reads.
- [ ] The execution role is added to the notifications writer's sender allowlist — the runtime
      `create` boundary that compares the role-id half of `SenderId` — and **no queue resource
      policy is added** on the notifications queue.
- [ ] The execution role holds `athena:GetQueryExecution` and `athena:GetQueryResults` on the
      app's workgroup, `s3:GetObject` on the results prefixes only (`{user_space_bucket}/*/{results
      prefix}/*`, from the one builder), `s3:GetObject` on `{admin_bucket}/shared-spaces/*` plus the
      `s3:prefix`-conditioned `ListBucket` the registry read needs, and **no** `s3:PutObject` — the
      write grant arrives with SPEC-222, beside the verb that uses it. It holds no
      `athena:StartQueryExecution` anywhere, asserted by a test over the rendered policy.
- [ ] The deploy role's grants for the module land in **their own PR, applied before** the module,
      following `infra/info/deploy-role-iam.md`.

### FR-002: The request contract and the enqueue route

#### Description:

What the browser sends, declared once in Python.

#### Acceptance Criteria:

- [ ] `ResultsConversionEnqueueRequest` is a `TypedDict` in `apicommon.contract` with exactly:
      `requestId` (UUID v4 string), `queryExecutionId` (Athena's UUID form), `format`
      (`Literal["parquet", "json", "xlsx"]`), `destination` (`{space: SpaceRef, prefix: str,
      filename: str}`), `onConflict` (`Literal["refuse", "overwrite"]`) and `submittedAt`
      (ISO-8601). Every key is required; an unknown key is refused by the route's validator.
- [ ] `format` is a **closed** vocabulary: `csv` is refused at the route with the same validation
      code as any other unknown value, because CSV is the synchronous copy and never this plane's.
- [ ] Caps: `filename` is 1–255 bytes, contains no `/` and no control character, and is not `.` or
      `..`; `prefix` ends in `/` or is empty and is at most 1024 bytes; each cap is asserted by a
      test that submits one byte over it and reads the validation code.
- [ ] An `EnqueueRoute` with `id="resultsConversion.enqueue"`, `POST /v1/enqueue/results-conversion`,
      `plane="api"`, `idempotent=False`, `queue="results-conversion"`, `stamped=frozenset()`, and
      `EnqueueAccepted` as its response. The TypeScript type is generated, never hand-written, and
      `test_contract_generation.py` covers it.
- [ ] The handler is built from the enqueue factory in `lambdas/api/routes/enqueue.py` and makes no
      AWS call of its own beyond the send; the `identity` block is stamped by the shared sender
      exactly as it is for the other planes.
- [ ] `MessageGroupId` is the actor's username, so one user's requests are delivered in order;
      `MessageDeduplicationId` is `requestId`, so a browser retry of one submit is one execution.
- [ ] The API's environment carries the queue URL from Terraform, through the same map every other
      enqueue route's queue reaches it by; a missing or empty value fails the API at cold start,
      not on the first request.

### FR-003: Actor identity and destination authorization

#### Description:

validate-authorize decides, from the stamped identity and the registry, whether this actor may
write this destination.

#### Acceptance Criteria:

- [ ] The actor is read from the `identity` block through `cpcommon.actor` and nowhere else; the flat
      `actor` field is never consulted, and `assurance` fails closed on an unknown or absent value,
      each asserted by a fixture that carries the wrong thing.
- [ ] A personal destination space is authorized iff its name equals the verified username. A shared
      destination is authorized iff the registry record names the actor as a **usable** member,
      through the same `cpcommon.registry` read file-ops uses; a `deleting`, `failed` or emptied
      space refuses. A record that cannot be read because of a real `AccessDenied` **raises** and is
      not read as absence.
- [ ] The destination key `{space root}{prefix}{filename}` is proved inside the space root by
      `cpcommon.paths.assert_inside_root`; a `..` segment, an absolute key or a key escaping the root
      refuses with `invalid_request`.
- [ ] The app-managed prefixes are refused as destinations with `protected_location`, and the list
      comes from the **one builder per app-managed path** SPEC-218 establishes — never a second list
      in `rccommon`. A test asserts the refused set equals the set that builder enumerates.
- [ ] The execution role carries an explicit IAM **Deny** on `s3:PutObject` under every app-managed
      prefix in both space buckets, mirroring the portal role's, so a validator defect cannot write
      into a receipt folder. The rendered policy is asserted to name every prefix the builder
      enumerates.
- [ ] Refusals are **return values** carrying a reason code from `rccommon`; only an unpredicted
      fault raises. `forbidden` is one sentence for a space the actor is not in and for a space that
      does not exist, so the refusal is not a directory of space names.

### FR-004: The execution is the actor's, and it finished with a result set

#### Description:

The second half of validate-authorize: the execution id is a claim, and the path Athena wrote to is
the proof.

#### Acceptance Criteria:

- [ ] `GetQueryExecution` is called once. An id Athena does not know (`InvalidRequestException`)
      refuses with `execution_not_found`.
- [ ] The execution's `ResultConfiguration.OutputLocation` must begin with the actor's own results
      prefix, built by the one builder the API's `output_location` uses (SPEC-218); any other
      location refuses with `execution_not_found` — the same code as an unknown id, so the refusal
      cannot say whether another user's execution exists.
- [ ] `QUEUED` and `RUNNING` refuse with `execution_not_finished`; `FAILED` and `CANCELLED` with
      `execution_failed`; only `SUCCEEDED` proceeds. The state is read from the same call.
- [ ] A `StatementType` other than `DML` refuses with `no_result_set`: a DDL or utility statement
      writes no rows and there is nothing to convert. A `DML` execution with zero data rows is
      **not** refused here — an empty result is a valid file with a header.
- [ ] validate-authorize emits, and only emits, `username`, `destination` (bucket, key, prefix,
      space kind and name), `format`, `onConflict`, `queryExecutionId`, `resultsKey` (the S3 key of
      the result object, derived from `OutputLocation`) and `requestId`. A test asserts the emitted
      key set equals this list, because a downstream state reading a key that is absent raises an
      uncatchable `States.Runtime`.

### FR-005: Describe the result set, and the cap

#### Description:

describe-results reads what the converter needs to know before a byte of data is read.

#### Acceptance Criteria:

- [ ] The column names and Athena types come from one `GetQueryResults` call with `MaxResults=1`,
      reading `ResultSetMetadata.ColumnInfo` and discarding the row. The rows are never paged here
      or anywhere on this plane; a test asserts exactly one `GetQueryResults` call per execution.
- [ ] The result object's size comes from one `HeadObject` on `resultsKey`; a 404 or 403 raises as a
      fault (the object Athena reported cannot be absent from a path the actor owns; a denial is a
      grant defect, not a user error).
- [ ] The size cap `RESULTS_MAX_BYTES` lives in `rccommon` and is **computed by a test** against the
      converter's memory and ephemeral-storage budget as SPEC-222 FR-005 sizes them, with the
      derivation in the test's docstring naming the budget it was sized against. A result above it
      refuses with `results_too_large`, whose wording carries the cap in human units. Until SPEC-222
      lands the constant is provisional and the test says so.
- [ ] The emitted state carries `columns` (`[{name, type}]`), `resultsBytes` and everything FR-004
      emitted, and nothing else; the same key-set assertion as FR-004.
- [ ] Column names are user data: a name that is empty or duplicates another (case-folded) is not
      refused here — the converter writes what Athena named — but the plane never builds a key, a
      message or a log field from a column name. A test asserts no column name reaches the
      notification body or the observability span.

### FR-006: The failure paths

#### Description:

Every way the machine can stop short of its terminal tells the user.

#### Acceptance Criteria:

- [ ] Every catch routes through `NotifyFailure` before `Fail`, including the pre-identity path
      (malformed event, no `identity` block), with the pre-identity seed reading the raw error and
      every post-identity seed carrying `username`, `requestId` and `format`; the ASL is walked by a
      test asserting no `Fail` is reachable except through `NotifyFailure`.
- [ ] No ASL state decodes an error `Cause`; the raw `$.error` is carried and
      `cpcommon.errors.failure_reason` is the only decoder.
- [ ] `rccommon` registers every reason code this plane can return — `forbidden`, `invalid_request`,
      `protected_location`, `execution_not_found`, `execution_not_finished`, `execution_failed`,
      `no_result_set`, `results_too_large`, `malformed_event`, `unexpected` — each with wording that
      names the format and the file name where they are known, and the generic sentence only for
      what a user cannot act on. A test enumerates the codes raised against the codes registered.
- [ ] A refused request produces exactly one notification, from `NotifyFailure`, addressed to the
      actor from `identity.actor`; a request refused before identity produces none and is
      dead-lettered, which the DLQ drain then notifies from the same field.
- [ ] Structured logging goes through `cpcommon.observability` only; no message carries a column
      name, a file name or the SQL (which this plane never reads at all).

---

## Data Model

```py
# lambdas/api/apicommon/contract.py

class ConversionDestination(TypedDict):
    space: SpaceRef
    prefix: str        # "" or ends in "/", at most 1024 bytes
    filename: str      # 1–255 bytes, no "/", no control characters, not "." or ".."

class ResultsConversionEnqueueRequest(TypedDict):
    requestId: str
    queryExecutionId: str
    format: Literal["parquet", "json", "xlsx"]
    destination: ConversionDestination
    onConflict: Literal["refuse", "overwrite"]
    submittedAt: str
```

```ts
// apps/portal/src/types/apiContract.generated.ts — generated, never edited
export type ResultsConversionEnqueueRequest = {
  requestId: string;
  queryExecutionId: string;
  format: 'parquet' | 'json' | 'xlsx';
  destination: {space: SpaceRef; prefix: string; filename: string};
  onConflict: 'refuse' | 'overwrite';
  submittedAt: string;
};
```

```py
# The state after DescribeResults — the whole of what Convert may read.
{
  "requestId": str, "username": str, "format": str, "onConflict": str,
  "queryExecutionId": str, "resultsKey": str, "resultsBytes": int,
  "columns": [{"name": str, "type": str}],
  "destination": {"bucket": str, "key": str, "prefix": str, "spaceKind": str, "spaceName": str}
}
```

## File & Folder Structure

```
infra/modules/results-conversion/
├── iam.tf  lambda.tf  locals.tf  pipe.tf  sqs.tf  stepfunction.tf  outputs.tf  variables.tf
├── policies/execution.json.tftpl
└── state-machine.asl.json.tftpl
lambdas/
├── results-conversion-common/rccommon/   (messages.py, reasons.py, paths.py)
├── results-conversion-validate-authorize/
├── results-conversion-describe-results/
└── results-conversion-notify-failure/
lambdas/info/planes/results-conversion.md
```

## Implementation Phases

### Phase 1: The deploy role's grants

- The `.tftpl` grants for the module's resource names, in their own PR, applied green.

### Phase 2: The plane's infrastructure

- Queue, DLQ, pipe, machine skeleton with `NotifyFailure`, `TimeoutSeconds` + `TIMED_OUT` rule,
  execution role with read-only grants and the Deny mirror, DLQ drain and notifications allowlist
  wiring, `docker-lambda` declaration.

### Phase 3: The contract and the route

- `ResultsConversionEnqueueRequest`, the `EnqueueRoute`, the generated TypeScript, the queue URL
  through the API's environment map.

### Phase 4: validate-authorize and describe-results

- `rccommon`, the two verbs, the key-set assertions, the provisional cap and its test.

### Phase 5: Verification

- The ASL walk, the policy assertions, the fleet and image sweeps; a live request through the API
  reaching the placeholder terminal, and one refused at each of FR-003/FR-004's codes.

### Phase 6: Completion ritual

- Delivery doc, INDEX row, the plane page `lambdas/info/planes/results-conversion.md`, the register
  entry for "results, never the source", and the Key Decisions clause.
