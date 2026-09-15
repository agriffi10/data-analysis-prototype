# Spec: Refresh Table — Request Contract, Mode Branch & Table Eligibility

**ID:** SPEC-143
**Status:** Completed
**Last Updated:** 2026-08-04
**Depends On:** SPEC-067 (the table-builder request envelope and `validate-authorize`), SPEC-068 (`check-table-absent`, the verb this one mirrors in the negative), SPEC-069 (the declared-partition-key shape this spec must reconstruct), SPEC-070 (`execute-ddl` and the terminal-state pair), SPEC-090 (`tscommon.glue.clone_definition` — the existing, tested reader of a live Glue table), SPEC-107 (`cpcommon`), SPEC-135 (the table-builder plane's observability)

> **Reference:** `docs/architecture.md` → *Control Planes → Table Builder* (orchestration, authz, DDL + projection, infra). First of the refresh-table arc (143 → 144 → 145).
>
> **This arc adds no new control plane.** It extends the **existing** table-builder plane with a second path through the **same** FIFO queue, the **same** EventBridge Pipe, the **same** Step Function and the **same** shared execution role. That is deliberate and load-bearing: a refresh is a re-run of inspect-source and infer-schema against a table that already exists, and those two verbs — with the **polars layer** attached only to `infer-schema` — are the expensive, hard-won parts. A second module would duplicate them.
>
> **What 143 ships:** the `mode` field on the request envelope, the `Choice` branch in the state machine, a new `load-table-definition` verb that reads the live Glue table and decides whether it is refreshable, and the `portal.managed` table property that table-builder starts writing from now on. The diff and the apply stay stubbed — **143's refresh branch ends at a terminal failure `not_implemented` after `InferSchema`**, so the branch is exercised end to end before it can change anything. SPEC-144 replaces that stub.
>
> **The design constraint that shapes FR-004, discovered while authoring and stated here so it is not re-discovered mid-build:** `inspect-source` and `infer-schema` are *not* generic over their inputs. `inspect-source` lists `space.bucket` + `space.prefix` (not a `location` field), and `infer-schema` hands its `partition_keys` straight to `cpcommon.ddl.build_create_table_ddl`, which requires the **SPEC-069 declared shape** (`type ∈ {integer,date,string}` plus `range` / `values` / `format`) and raises a bare `ValueError` on anything else. So `load-table-definition` must hand the shared spine exactly what a create would have handed it: a rewritten `space.prefix` and **reconstructed declared partition keys**, not raw Glue shapes. FR-004 is written around that.
>
> **Rulebooks:** `lambdas/info/best-practices/lambdas/lambdas.md`, routed via `docs/best-practices/INDEX.md`.
>
> **Transition note (`docs/transition_plan.md` §2 item 9, §7 Phase 4):** analytics is feature-flagged **off** for Phase 1 of the client transition and the table arcs are re-enabled one at a time in Phase 4 against their original acceptance criteria. Nothing in this arc reads the `cognito:username` claim outside `cpcommon.auth`, so it survives the transition unchanged. Do not add a second claim reader.

## Overview

A portal-created table is a **snapshot of a schema, over data that keeps moving.** Table Builder infers columns from a sample file once, writes `CREATE EXTERNAL TABLE`, and never looks again. When a user later drops files with three new columns into the same folder, Athena keeps returning the old columns and the new data is invisible — silently, with no error, which is the worst shape a data bug can take. Today the only remedy is to drop the table and build it again from the Files browser, which means leaving the Query workspace, remembering the exact partition keys that were declared at create time, and retyping them.

**Refresh table** is the remedy in one action: from the table's options menu in the Query schema rail, re-inspect the folder the table already points at, re-derive the columns, and update the table in place. It is not a new capability so much as the missing second half of Table Builder.

This spec builds the front half of the pipeline — how a refresh is requested, how it is routed, and how the system decides a given table is a legitimate refresh target at all. That last question is where the real work is. A refresh reads a table it did not create in this run, and must not proceed on one it cannot faithfully rebuild: a view, a table Athena manages rather than one over external files, a table whose location is outside the space the actor is authorized for, or one partitioned through the Glue catalog rather than through partition projection. Each of those is a terminal refusal with its own reason code, decided in one verb, before anything reads a byte of S3.

## Amends

- **SPEC-067 (request contract).** The envelope gains an optional `mode` field. Absent or `"create"` reproduces today's behaviour byte for byte; `"refresh"` selects the new branch. Existing producers are unchanged and unbroken — this is additive by construction, and a test pins that an envelope with no `mode` still routes to create.
- **SPEC-069 / SPEC-070 (DDL generation).** `cpcommon.ddl.build_create_table_ddl` starts emitting a `portal.managed = 'true'` table property, under a new `mark: bool = True` argument a caller sets `False` for a table that is not a durable user table. This is a marker for the future, **not** the eligibility test — see FR-004 for why eligibility turns on shape rather than on the marker.
- **SPEC-090 (table-share `inspect-source`).** `clone_definition` moves from `tscommon.glue` to `cpcommon.glue` **with its signature and its reason codes unchanged**, and `tscommon.glue` re-exports it. Table-share's behaviour, its tests and its `SHARE_MAX_DEFINITION_BYTES` constant are untouched — see FR-004 AC9 for why the refresh path maps reason codes at its own call site rather than parameterising them.

---

## Scope

### In Scope

- **`mode` on the table-builder SQS envelope** — `"create" | "refresh"`, optional, defaulting to `"create"`.
- **`validate-authorize` accepts both modes** — the actor/space/database authorization is identical for a refresh; only the partition-key validation differs (a refresh declares none).
- **A `Choice` state in the table-builder state machine** branching on `mode`, with `InspectSource` and `InferSchema` **shared by both branches** and reached from either.
- **A new verb `table-builder-load-table-definition`** — reads the live Glue table, decides refreshability, **rewrites `space.prefix` to the table's own location**, and **reconstructs declared partition keys** from the table's projection properties.
- **The location comes from the table, not from the request.** The request still carries a prefix and it is still authorized (FR-004 AC7 explains why both checks are needed and neither is redundant).
- **`portal.managed = 'true'`** written into `TBLPROPERTIES` by `cpcommon.ddl.build_create_table_ddl` for every durable user table it builds (data-quality's temp tables opt out via `mark=False`), and added to `clone_definition`'s excluded-parameters list — which lives in `cpcommon.glue` after this spec's own Phase 1 move, not in table-share.
- **`clone_definition` moved to `cpcommon.glue`**, unchanged, re-exported from `tscommon.glue`.
- **Terminal reason codes** for every refusal, registered with `cpcommon.messages.register_reasons`.
- **A `not_implemented` stub terminal** at the end of the refresh branch, replaced by SPEC-144.
- **The new function's row** in `lambdas/test_deploy_matrix.py`'s matrix and in `infra/modules/table-builder/locals.tf`.
- **Observability** on the new verb per SPEC-135's shape.

### Out of Scope

- **The schema diff and the apply** — SPEC-144. If this spec ends up computing an added/removed/changed column set, or issuing any DDL, it has gone wrong.
- **Any browser surface** — SPEC-145. No menu item, no dialog, no `enqueueTableRefresh`. The only way to exercise 143 is a hand-crafted SQS message, and the acceptance criteria are written that way.
- **Changing a table's partition keys.** A refresh reconstructs the existing keys and re-derives only the data columns. Changing partition keys means dropping the table and building it again through Table Builder, and the reason is not effort: keys were user-declared at create time (SPEC-069) and are recorded **nowhere** but on the table itself, so re-deriving them would mean re-asking a question the user is not being asked here.
- **Refreshing views.** A view has no source files; there is nothing to re-inspect. Terminal refusal.
- **Refreshing catalog-partitioned or non-external tables.** Shape-compatible tables created by hand *are* refreshable — see FR-004.
- **Changing `SHARE_MAX_DEFINITION_BYTES` or table-share's `source_definition_too_large` code.** The 32 KB figure was measured for table-share's **50-recipient `Map` fan-out** and does not transfer to a plane with no `Map`; the refresh path gets its own bound (FR-004 AC8).
- **Propagating a refresh to table-share recipient copies.** A share is a one-time snapshot into the recipient's own prefix with its own data and its own Glue table, and **no provenance link exists in either direction** (`docs/architecture.md` → *Control Planes → Table Share*). Building that linkage is a separate, larger piece of work.
- **Any scheduled or automatic refresh.** User-initiated only.

---

## Functional Requirements

### FR-001: `mode` on the request envelope

#### Description

One field selects the branch. It is optional so that every shipped producer keeps working, and it is validated in `validate-authorize` so an unknown value fails as a typed terminal rather than falling through a `Choice` default into something surprising.

#### Acceptance Criteria:

- [ ] The SQS body accepts an optional `mode` of `"create"` or `"refresh"`.
- [ ] A body with no `mode` is treated as `"create"`, and a test asserts an envelope identical to SPEC-067's produces the identical threaded state through `validate-authorize`.
- [ ] A `mode` that is present but neither literal raises `TerminalError("invalid_mode")` in `validate-authorize`.
- [ ] `validate-authorize` emits `mode` on its output payload, normalised to the literal string (never `None`), so the `Choice` state never evaluates a missing field.
- [ ] `MessageGroupId` remains `space.database` and `MessageDeduplicationId` remains `requestId` for both modes — a refresh and a create against the same database serialize against each other, which is what makes a refresh safe to fire while a build is in flight.

  > **SUPERSEDED 2026-09-15.** They are started in order and then overlap, because the Pipe is `FIRE_AND_FORGET`. A refresh is safe beside a build because it needs the table to exist and refuses otherwise, and refreshes of one table are serialized by their own lock — `docs/decisions/control-planes.md`, *A group id orders the STARTS, not the runs*.

### FR-002: Refresh requests carry no partition keys, and their prefix is still authorized

#### Description

Partition keys are a create-time declaration. A refresh that accepted them would be offering to change them, which FR-006 forbids.

The prefix is a different matter and is easy to get wrong. `_authorize_space` in `validate_authorize.py` requires a prefix and rejects one that does not start with `{actor}/` (personal) or `{database}/` (shared), raising `TerminalError("forbidden")`. That check stays exactly as it is on the refresh path. The producer supplies the prefix it believes the table points at — SPEC-145 parses it from `GlueTableSummary.location` — and `load-table-definition` then confirms it against what the catalog actually says.

#### Acceptance Criteria:

- [ ] When `mode == "refresh"`, a body carrying a non-empty `partitionKeys` raises `TerminalError("partition_keys_not_refreshable")`.
- [ ] When `mode == "refresh"`, an absent or empty `partitionKeys` is accepted and `validate-authorize` emits `partitionKeys: []`.
- [ ] `_authorize_space` and `_normalize_prefix` are **unchanged** and run identically for both modes; a refresh with a prefix outside the actor's space raises the existing `forbidden`.
- [ ] `validate-authorize` continues to emit `location` as it does today; `load-table-definition` overwrites it (FR-004 AC7).
- [ ] When `mode == "create"`, `_validate_partition_keys` behaves exactly as SPEC-067 specified — a test pins that its error messages and reason codes are unchanged.

### FR-003: The state machine branches on mode and shares the inspection verbs

#### Acceptance Criteria:

- [ ] After `ValidateAuthorize`, a `Choice` state routes `$.mode == "refresh"` to `LoadTableDefinition` and everything else to `CheckTableAbsent`.
- [ ] The `Choice` has a `Default` of `CheckTableAbsent`, so an unreachable-but-possible missing field cannot strand an execution.
- [ ] `CheckTableAbsent` and `LoadTableDefinition` both transition to `InspectSource`; `InspectSource` transitions to `InferSchema` on both paths.
- [ ] `InferSchema` is followed by a second `Choice` routing `$.mode == "refresh"` to the refresh tail and everything else to `ExecuteDdl`.
- [ ] `LoadTableDefinition` carries the same uniform `Retry` block as every other Task state — the error names are **`Lambda.ServiceException`, `Lambda.TooManyRequestsException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `TransientError`** (the three middle names are `Lambda.`-prefixed in the shipped ASL; an unprefixed name matches nothing) — 2 s, 3 attempts, backoff 2, plus `Catch: States.ALL → ResultPath $.error → RecordFailure`.
- [ ] **No state decodes `$.error.Cause`.** A test asserts no state **uses** `States.StringToJson` (the repo-wide rule, #252). The assertion must walk the parsed state definitions, **not** grep the raw template — the literal string already appears in `RecordFailure`'s `Comment` prose (`state-machine.asl.json.tftpl:187`), so a string-containment check fails on day one against the shipped file.
- [ ] `RecordFailure` is unchanged. `RecordSuccess` today hard-codes `"status": "created"`; this spec adds `mode` to its Pass result and **leaves `status` alone** — SPEC-144 FR-007 owns making `status` mode-dependent, because nothing before 144 can produce a refresh success.

### FR-004: `load-table-definition` decides refreshability and normalises the state for the shared spine

#### Description

The verb answers one question — *can this table be faithfully rebuilt from its own definition plus a fresh look at its files?* — and it answers it from what Glue reports, not from a marker. A marker would be the obvious design and it is the wrong one: every table created before this spec lacks it, and the property is user-writable through `ALTER TABLE SET TBLPROPERTIES`, so it could be neither trusted as a permission nor relied on as a fact. The shape checks are the same ones `clone_definition` already makes for table-share, for the same reason — a definition it cannot faithfully reproduce is one it must refuse.

Its second job is less obvious and is why this verb exists at all rather than the branch running straight into `inspect-source`: **the shared spine expects a create's inputs.** `inspect_source.py` lists `space.bucket` + `space.prefix` and treats `location` as an output. `infer_schema.py` passes `partition_keys` unmodified to `build_create_table_ddl`, whose `_projection_props` and `_PARTITION_HIVE` require the SPEC-069 declared shape and raise a bare `ValueError` — not a `TerminalError` — on a Glue-shaped key. So this verb normalises: it rewrites the prefix and reconstructs the declared keys from `projection.*`. A reconstruction it cannot perform is a refusal, not a guess.

#### Acceptance Criteria:

- [ ] The verb calls `glue.get_table(DatabaseName=..., Name=...)`; `EntityNotFoundException` raises `TerminalError("table_not_found")`.
- [ ] It delegates the shape checks to `cpcommon.glue.clone_definition`, which returns `(definition, location, partitioned)`, and **maps** its reason codes at the call site so the refresh path speaks its own vocabulary: `source_is_view → cannot_refresh_view`, `source_not_external → cannot_refresh_managed_table`, `source_catalog_partitioned → cannot_refresh_catalog_partitioned`, `source_location_unsupported → cannot_refresh_location_unsupported`. An explicit mapping table, not a string-prefix parameter — the stems differ, so a prefix substitution cannot produce these names.
- [ ] `cannot_refresh_location_unsupported` covers both a missing or unparseable `LOCATION` and a bucket outside the two data buckets — both already raised by `_parse_location`. **There is no separate `table_has_no_location` reason**; the existing check covers it.
- [ ] `clone_definition` is moved to `cpcommon/glue.py` **with its signature, its return tuple, its `_EXCLUDED_PARAMETERS` and its four reason codes unchanged**, and `tscommon/glue.py` becomes a re-export. Table-share's existing tests pass **unmodified**, asserted as an acceptance criterion.
- [ ] **The bucket check is not enough.** `clone_definition` validates the bucket; this verb additionally validates the **prefix**: the parsed location's prefix must begin with the space's authorized root (`{actor}/` personal, `{database}/` shared). A mismatch raises `TerminalError("table_outside_space")`. The catalog is not the authorization boundary, and a table whose location points into another user's prefix must be refused even though its bucket is legitimate.
- [ ] **`space.prefix` and `space.bucket` are rewritten** on the output payload from the parsed location, and `location` is rewritten to match. This is what lets `inspect-source` run unchanged. A test asserts that a request whose prefix disagrees with the table's location proceeds against the **table's** location, and that the rewritten prefix still satisfies the authorized-root check.
- [ ] **A definition-size guard** using a new `cpcommon.config.REFRESH_MAX_DEFINITION_BYTES` raises `TerminalError("definition_too_large")` over the cap. The bound is chosen for this plane against the 256 KB Step Functions state-payload limit; `SHARE_MAX_DEFINITION_BYTES` is **not** reused, not renamed and not moved, because its 32 KB value was measured for table-share's 50-recipient `Map` and table-builder has no `Map`.
- [ ] On success the verb emits onto the threaded state: the rewritten `space` and `location`; `existingColumns` (name + type, in table order); `partitionKeys` **in the SPEC-069 declared shape** (FR-005); `storage` (FR-006); and `tableProperties` with `transient_lastDdlTime` and `EXTERNAL` already stripped by `clone_definition`.
- [ ] Every reason code above is registered via `cpcommon.messages.register_reasons` so `TerminalError` validates at raise time.

### FR-005: Declared partition keys are reconstructed, not passed through

#### Description

The table records its partitioning twice: as Glue `PartitionKeys` (name + Hive type) and as `projection.*` table properties. Only the second carries what `build_create_table_ddl` needs. Reconstruction is therefore mandatory, and a table whose projection properties are incomplete or unrecognisable is refused rather than partially rebuilt.

**Three details in `_projection_props` (`cpcommon/ddl.py`) make this less mechanical than it sounds, and each has already produced a wrong first draft of this FR.** A declared `string` key is written as `projection.{name}.type = "enum"` — never `"string"` — so a switch on the literal `string` refuses every string key. A `date` key writes **four** properties (`range`, `format`, `interval`, `interval.unit`), not two, and the shipped `PartitionKey` type carries `interval` / `intervalUnit` to match. And `values` is rendered `",".join(...)`, so an enum value containing a comma cannot be recovered. The acceptance criteria below are written against the properties as they are actually emitted; **read `_projection_props` before implementing** rather than trusting this prose.

**A recorded pre-existing bug adjacent to this FR, on the create path, not fixed here:**
`_projection_props` reads `key["format"]` **unguarded** (`ddl.py:128`) and
`_validate_partition_keys` never validates `format` or `interval` for a date key
(`validate_authorize.py:79-82`) — so a browser-submitted date key without `format` raises a bare
`KeyError` inside `infer-schema` and surfaces as the generic `unexpected_error`. The refresh path
is protected by this FR's reconstruction rules (a missing companion is
`projection_not_reconstructable`); the create-path gap is out of scope for this arc and should be
filed separately rather than fixed silently in passing.

#### Acceptance Criteria:

- [ ] For each Glue partition key, the verb reads `projection.{name}.type` and builds a SPEC-069 declared key, mapping **`enum → string`**: `integer` takes `range` and `digits` when present; `date` takes `range`, `format`, `interval` and `interval.unit`; `enum` takes `values`, split on `,`.
- [ ] The reconstructed keys are emitted **in the table's `PartitionKeys` order**, which is the granularity order the create declared.
- [ ] A partition key with no `projection.{name}.type`, an unrecognised type, or a missing required companion property raises `TerminalError("projection_not_reconstructable")`, naming the key in the error's operator-only `detail`.
- [ ] ~~**An enum whose reconstructed `values` do not re-render to the source string** — i.e. a value contained a comma — raises `projection_not_reconstructable`.~~ **STRUCK during build (2026-08-04): the guard is provably vacuous and the limit is recorded instead.** `",".join(s.split(","))` reproduces `s` for every `s`, so no round-trip can detect a comma inside a value — the information is not in the property. Nor is it recoverable elsewhere: `values` is the only record. **Athena splits that property the same way**, so the reconstruction is faithful to what the table actually does today, and a value containing a comma was already two partitions to the engine before any refresh ran. Pinned as a recorded limit by `test_an_enum_value_containing_a_comma_is_split_the_way_athena_splits_it`.
- [ ] **The live partition COLUMN type is compared against the type the rebuild would write** (added during build, 2026-08-04). The round-trip below sees only `projection.*`, and Athena permits a projection over a wider set of column types than `build_create_table_ddl` emits — an `integer` projection is legal on a `string` column, which is exactly how a zero-padded partition is declared. Such a table round-trips perfectly and would be rebuilt as `int`, changing the column's type while reporting success. Mismatch raises `projection_not_reconstructable`.
- [ ] **A table-level `storage.location.template` raises `projection_not_reconstructable`** (added during build, 2026-08-04). It sits outside the `projection.{name}.*` namespace the per-key round-trip compares, so that check cannot see it, and it redirects where partitions read from entirely.
- [ ] A test asserts the reconstructed keys round-trip: feeding them to `build_create_table_ddl` reproduces the source table's `projection.*` properties **exactly**, for an integer key with digits, a date key with an interval, and an enum key. Any property the reconstruction drops fails this test, which is the point of writing it as exact equality.
- [ ] **A pre-existing name mismatch is recorded, not silently worked around:** `ddl.py` reads `key["interval.unit"]` while the browser sends `intervalUnit` (`tableBuild.types.ts`). The reconstruction must emit whichever key `_projection_props` actually reads; a comment names the discrepancy so it is fixed deliberately rather than by accident here.
- [ ] An unpartitioned table emits `partitionKeys: []` and is not subject to any of the above.
- [ ] A test asserts `infer-schema` is reached with declared-shape keys and never raises `ValueError` from `_projection_props` on the refresh path.

### FR-006: Storage is captured for SPEC-144, and the format is cross-checked

#### Acceptance Criteria:

- [ ] The verb emits `storage` carrying the SerDe library, the SerDe parameters, and the input and output formats, as read by `clone_definition`. SPEC-144 turns this into the `cpcommon.ddl.Storage` value the regenerated DDL needs; this spec only carries it.
- [ ] `inspect-source`'s reported `format` is compared against the table's SerDe; a disagreement — the folder now holds JSON under a table declared with `OpenCSVSerde`, say — raises `TerminalError("format_changed")`. The comparison runs in `load-table-definition`'s successor, not in `inspect-source`, so that verb stays free of any `mode` branch.
- [ ] `inspect-source`'s partition-layout validation runs against the reconstructed keys, so a folder whose `key=value/` layout has drifted raises the existing `partition_layout_mismatch` rather than silently adopting the drift.
- [ ] A test asserts `inspect_source.py` and `infer_schema.py` contain no reference to `mode`.

### FR-007: Table Builder marks the tables it creates

#### Description

Not the eligibility test (FR-004 is), but worth having: a durable, queryable answer to "did this portal create this table", available from the first table created after this spec ships. Greenfield with no production users is exactly when to start writing it.

**Naming note.** `portal.managed` (a table **TBLPROPERTY**, dotted) is not the same thing as `portal-managed` (the Lake Formation **tag on databases**, hyphenated, `infra/modules/analytics/lakeformation.tf`). They do unrelated jobs. A comment at each site says so, because the two names are one character apart.

#### Acceptance Criteria:

- [ ] `cpcommon.ddl.build_create_table_ddl` emits `'portal.managed' = 'true'` in `TBLPROPERTIES` for every table it builds **with the default storage — i.e. when no `storage=` override is supplied.** *(Narrowed during build, 2026-08-04.)* The builder has exactly two production callers: table-builder, which omits `storage` and creates the durable user tables this marker is a record of, and data-quality, which supplies one for `dq_tmp_*` tables it drops at the end of the same run. Marking those would put a permanent-sounding claim on something ephemeral **and** would change a shipped statement in an arc this spec does not touch.
- [ ] The property is added to `clone_definition`'s `_EXCLUDED_PARAMETERS`, so a shared copy does not inherit the source's marker as though the share had created it. **Correction (2026-08-04): the original rationale — "a copy is marked by its own creating call" — does not hold.** Table-share renders its recipient `CREATE` from `tscommon.ddl`, which never calls `build_create_table_ddl`, so a shared copy carries no marker at all. The exclusion is still required (inheriting one would be a false claim); marking share copies is table-share's to decide, not this arc's.
- [ ] A test asserts the property appears exactly once in generated DDL for each of the three formats (Parquet, CSV, JSON) and does not disturb the `projection.*` or `skip.header.line.count` properties.
- [ ] No verb reads this property to make a decision. A test greps the Lambda tree and fails if `portal.managed` appears outside `ddl.py`, `glue.py`'s exclusion list, and their tests.
- [ ] A comment at both `portal.managed` and `portal-managed` sites distinguishes them.

### FR-008: The refresh branch terminates in a typed stub

#### Acceptance Criteria:

- [ ] The second `Choice`'s refresh target is a state that raises `TerminalError("not_implemented")`, reaching `RecordFailure` through the normal `Catch`.
- [ ] A hand-enqueued refresh request against a real portal-created table runs to `Failed` with `not_implemented`, and CloudWatch plus `logs/service=table-builder/` show `load-table-definition`, `inspect-source` and `infer-schema` all completing `ok` with the expected fields.
- [ ] A second hand-enqueued run against a **partitioned** table confirms FR-005's reconstruction end to end — this is the criterion most likely to fail live, because it is the only one whose input is a table the pipeline did not write in this run.

### FR-009: Infrastructure, IAM and the deploy matrix

#### Acceptance Criteria:

- [ ] `table-builder-load-table-definition` is added to `infra/modules/table-builder/locals.tf`'s `table_builder_functions` map (15 s / 256 MB, mirroring `check-table-absent`). **`lambda.tf` needs no edit** — it is entirely `for_each` over that map, so the function, its log group and its placeholder zip all follow from the map entry.
- [ ] **`stepfunction.tf` DOES need an edit.** Its `templatefile()` call passes an explicit per-function map (`validate_authorize_function_arn`, `check_table_absent_function_arn`, …), not a loop, so a new ASL state referencing a new function needs its `_function_arn` key added there or the template fails at **plan** time. Easy to miss precisely because `lambda.tf` does not.
- [ ] The function joins the **existing shared execution role**; no new role is created.
- [ ] **No IAM change is required.** `infra/modules/table-builder/policies/execution.json.tftpl` already grants `glue:GetTable`; SPEC-144 owns the write actions. A comment records this so the absence is deliberate rather than forgotten.
- [ ] The function's environment carries the full common block; a test asserts every variable `cpcommon.config._require`s is present (the PR #196 / PR #317 cold-start trap).
- [ ] `.github/workflows/deploy-lambdas.yml` gains `{ name: table-builder-load-table-definition, layer: false, polars: false, tbcommon: true, cpcommon: true }`, and `lambdas/test_deploy_matrix.py` passes.
- [ ] `infra/modules/base/policies/github-actions-deploy-table-builder.json.tftpl` already wildcards on `${project_name}-*-table-builder-*`, which covers the new name; a comment confirms it and **no deploy-role change is needed**.

### FR-010: Observability

#### Acceptance Criteria:

- [ ] `@observability.traced("load-table-definition")` is the **outermost** decorator, above `@notifies_on_failure` — the ordering rule, or a failed invocation closes its span `ok`.
- [ ] The root span is named after the verb, and `verb` is baggage (SPEC-130).
- [ ] Messages are literals; every variable is a field. Fields include `database`, `table`, `location`, `column_count`, `partition_key_count`, `mode` and `request_id`.
- [ ] **No column values, sampled rows or file contents** appear in any field — column *names* are schema and are permitted, per the field rule in `decisions/`.
- [ ] The function is picked up automatically by `lambdas/control-plane-common/test_instrumentation_coverage.py`'s handler sweep. `PLANES` there is a **list of `Plane` dataclasses carrying a hard-coded `verb_count`**, with verbs discovered from disk — there is no verb list to append to. The table-builder entry's `verb_count` literal is bumped **5 → 6** or `test_the_enumeration_actually_found_the_verbs` fails.

### FR-011: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run lint` and the Python test suite pass.
- [ ] Tests cover: mode defaulting and rejection; `partition_keys_not_refreshable`; the unchanged `forbidden` behaviour on a refresh with a bad prefix; each of the four mapped refusal reasons with a fixture Glue table; `table_outside_space` for a same-bucket different-prefix location; the prefix rewrite; the FR-005 round-trip for all three key types, `projection_not_reconstructable` for each missing companion, for a mismatched column type and for `storage.location.template`; `definition_too_large`; the `cpcommon.glue` move leaving table-share's suite untouched; the DDL marker across three formats; the ASL `Choice` routing both ways plus its `Default`; the `Lambda.`-prefixed retry names; and the absence of `States.StringToJson`.

---

## Data Model

```jsonc
// SQS body — {project}-{env}-table-builder-requests.fifo
// Extends SPEC-067's envelope. `mode` is the only new field.
// NOTE: neither `idToken` nor `requestId` rides on the TS request type. `requestId`
// is minted inside enqueueTableBuild; the ID token is fetched by the SHARED
// enqueueFifoRequest helper (lib/enqueueFifo.ts:50), which five features use — a
// change there is not table-builder-local.
{
  "idToken": "<Cognito ID token>",
  "mode": "refresh",              // NEW. "create" | "refresh"; absent ⇒ "create"
  "space": {
    "kind": "personal",           // "personal" | "shared"
    "bucket": "dat-prod-user-space",
    "prefix": "alice/sales/2026/",// REQUIRED and AUTHORIZED on both paths. On refresh it
                                  //   is the producer's belief about the table's location;
                                  //   load-table-definition overwrites it from the catalog
                                  //   after re-checking the authorized root.
    "database": "alice"
  },
  "tableName": "sales_2026",
  "partitionKeys": [],            // MUST be empty or absent when mode == "refresh"
  "requestId": "<uuid>"
}
// MessageGroupId        = space.database   (unchanged)
// MessageDeduplicationId = requestId       (unchanged)
```

```python
# Threaded state after table-builder-load-table-definition.
{
    "mode": "refresh",
    "actor": "alice",
    # space.bucket / space.prefix REWRITTEN from the catalog so inspect-source,
    # which lists space.bucket + space.prefix, needs no change at all.
    "space": {"kind": "personal", "bucket": "...", "prefix": "alice/sales/2026/",
              "database": "alice"},
    "tableName": "sales_2026",
    "requestId": "...",
    "location": "s3://dat-prod-user-space/alice/sales/2026/",

    "existingColumns": [{"name": "order_id", "type": "string"}],

    # RECONSTRUCTED into the SPEC-069 DECLARED shape — not Glue's {name, type}.
    # infer-schema hands this straight to build_create_table_ddl, which requires it.
    # NOTE the source property is projection.year.type = "integer" here, but a STRING
    # key's source property is "enum" — see FR-005.
    "partitionKeys": [{"name": "year", "type": "integer", "range": [2000, 2100],
                       "digits": 4}],

    # Carried for SPEC-144, which turns it into a cpcommon.ddl.Storage value.
    "storage": {
        "serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
        "parameters": {"separatorChar": ","},
        "inputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "outputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
    },
    # clone_definition copies ALL Glue Parameters minus transient_lastDdlTime and
    # EXTERNAL — so a partitioned table's tableProperties NECESSARILY also carries
    # every projection.* key. That is not incidental: SPEC-144 regenerates those same
    # keys from the reconstructed partitionKeys, so it MUST strip them from this dict
    # before merging or the statement emits each one twice (SPEC-144 FR-004 AC3).
    "tableProperties": {
        "skip.header.line.count": "1",
        "portal.managed": "true",
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": "2000,2100",
        "projection.year.digits": "4",
    },
}

# Terminal reasons added by this spec:
#   invalid_mode
#   partition_keys_not_refreshable
#   table_not_found
#   cannot_refresh_view                    # mapped from source_is_view
#   cannot_refresh_managed_table           # mapped from source_not_external
#   cannot_refresh_catalog_partitioned     # mapped from source_catalog_partitioned
#   cannot_refresh_location_unsupported    # mapped from source_location_unsupported
#   table_outside_space
#   projection_not_reconstructable
#   definition_too_large
#   format_changed
#   not_implemented                        # removed by SPEC-144
```

---

## API / Interface Contract

```python
# lambdas/control-plane-common/cpcommon/glue.py  — MOVED from tscommon/glue.py,
# signature and reason codes UNCHANGED. tscommon/glue.py becomes:
#     from cpcommon.glue import clone_definition  # noqa: F401

def clone_definition(table: dict) -> tuple[dict, dict, bool]:
    """Read a live Glue table into (definition, location, partitioned).

    Raises TerminalError with source_is_view / source_not_external /
    source_catalog_partitioned / source_location_unsupported.

    The refresh path MAPS these codes at its call site rather than parameterising
    them: the two callers refuse for the same structural reason and must say so in
    their own vocabulary, and the code stems differ, so a prefix substitution cannot
    produce the refresh names. Mapping also leaves table-share byte-for-byte intact.
    """
```

```ts
// apps/portal/src/features/table-builder/tableBuild.types.ts — extended.
// NOTE the actual shipped shape: no idToken, no requestId (both minted inside
// enqueueTableBuild), and `space` is an inline object type. This spec NAMES that
// inline type so SPEC-145 can import it — that extraction is the only TS change here.

export type TableBuildSpace = {
  kind: 'personal' | 'shared';
  bucket: string;
  prefix: string;
  database: string;
};

export type TableBuildMode = 'create' | 'refresh';

export type TableBuildRequest = {
  mode?: TableBuildMode; // absent ⇒ 'create'; existing callers unchanged
  space: TableBuildSpace;
  tableName: string;
  partitionKeys: PartitionKey[]; // [] when mode === 'refresh'
};
```

## Environment Variables

None. The new function reuses the table-builder common environment block.

## File & Folder Structure

```
lambdas/
├── control-plane-common/cpcommon/
│   ├── glue.py                              # NEW — clone_definition moved here, unchanged
│   ├── config.py                            # + REFRESH_MAX_DEFINITION_BYTES
│   ├── ddl.py                               # + portal.managed TBLPROPERTY
│   └── messages.py                          # + the reason codes above
├── table-share-common/tscommon/
│   └── glue.py                              # now a re-export; behaviour unchanged
├── table-builder-load-table-definition/     # NEW
│   ├── load_table_definition.py
│   └── test_load_table_definition.py
├── table-builder-validate-authorize/
│   └── validate_authorize.py                # + mode validation, + refresh partition-key rule
└── test_deploy_matrix.py                    # + the new row

infra/modules/table-builder/
├── locals.tf                                # + load-table-definition in the function map
│                                            #   (lambda.tf is for_each — no edit needed)
├── stepfunction.tf                          # + load_table_definition_function_arn in the
│                                            #   templatefile() map — an EXPLICIT map, not a loop
└── state-machine.asl.json.tftpl             # + two Choice states, + the not_implemented stub

apps/portal/src/features/table-builder/
└── tableBuild.types.ts                      # + TableBuildSpace, TableBuildMode, mode?

.github/workflows/deploy-lambdas.yml         # + matrix row
```

## Implementation Phases

### Phase 1: The `cpcommon.glue` move

- Move `clone_definition` to `cpcommon/glue.py` verbatim; re-export from `tscommon/glue.py`.
- **Tests:** table-share's existing suite passes unmodified — that is the whole criterion for this phase.

### Phase 2: Contract and routing

- Add `mode` to the envelope, to `validate_authorize.py` and to the TS types (extracting `TableBuildSpace`).
- Add both `Choice` states and the `not_implemented` stub to the ASL template.
- **Tests:** mode defaulting, `invalid_mode`, `partition_keys_not_refreshable`, unchanged `forbidden`, ASL routing plus `Default`, the `Lambda.`-prefixed retry names, and the no-`States.StringToJson` assertion.

### Phase 3: `load-table-definition`

- The verb: shape checks with reason mapping, the prefix re-check and rewrite, FR-005's reconstruction, the size guard, `storage` capture, its `locals.tf` entry, matrix row and observability.
- The `format_changed` cross-check on the successor state.
- **Tests:** the whole FR-011 list bar the DDL marker.

### Phase 4: The DDL marker, live check, closing out

- `portal.managed` in `build_create_table_ddl` and in `_EXCLUDED_PARAMETERS`, with the naming comments.
- Run FR-008's two live checks, including the partitioned one.
- Completion ritual: `INDEX.md` status, delivery doc, component-inventory rows, and a `decisions/` entry for the shape-not-marker eligibility rule with one line in `CLAUDE.md`. **No help-content change** — nothing user-visible ships in this spec (SPEC-074 FR-005).
