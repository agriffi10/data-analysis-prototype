# Completed Spec — SPEC-143: Refresh Table — Request Contract, Mode Branch & Table Eligibility

## What was completed?

The front half of the refresh pipeline: how a refresh is requested, how it is routed, and how the
system decides a table is a legitimate refresh target. The diff and the apply are SPEC-144; the
browser surface is SPEC-145. **Nothing user-visible shipped** — the only way to exercise this today
is a hand-crafted SQS message.

- **`mode` on the table-builder envelope** — `"create" | "refresh"`, optional, absent ⇒ create.
  `validate_authorize._validate_mode` normalises it to a literal and emits it; `invalid_mode` and
  `partition_keys_not_refreshable` are its two new terminals. `_authorize_space`,
  `_normalize_prefix` and `_validate_partition_keys` are untouched and run identically for both.
- **Two `Choice` states** in `state-machine.asl.json.tftpl` — `RouteByMode` after validate,
  `RouteTailByMode` after infer-schema — with `InspectSource` and `InferSchema` **shared by both
  branches**, and `RefreshNotImplemented`, a stub SPEC-144 deletes.
- **`table-builder-load-table-definition`** — the refresh branch's entry verb. Reads the live Glue
  table, decides refreshability, rewrites `space.bucket`/`space.prefix`/`location` from the
  catalog, reconstructs the declared partition keys, and emits `existingColumns`, `storage` and
  `tableProperties`.
- **`cpcommon.glue`** — `clone_definition` moved from `tscommon.glue`, re-exported there.
- **`cpcommon.ddl`** gains `projection_properties`, `partition_hive_type`, `SERDE_FORMATS` /
  `format_of_serde`, `PORTAL_MANAGED`, and a `mark` argument; `cpcommon.config` gains
  `REFRESH_MAX_DEFINITION_BYTES`.
- **`format_changed`** in `infer_schema.py`, gated on the presence of `storage`.
- Four PRs: #345 (the move), #346 (contract + routing), #347 (the verb), #349 (`portal.managed`).

### Decisions worth carrying forward

- **Eligibility turns on SHAPE, never on the marker.** Full entry in `docs/decisions/`.
- **The reconstruction needs TWO guards and neither suffices alone.** The round-trip re-renders each
  key through the create path's own renderer and demands exact equality, catching dropped, rewritten
  and extra `projection.*` properties. It cannot see the **column type**, and Athena permits a
  projection over a wider set than this builder writes — an `integer` projection on a `string`
  column is exactly how a zero-padded partition is declared. That table round-trips *perfectly* and
  would be rebuilt as `int`, retyping the column while reporting success. Also refused:
  `storage.location.template`, which is table-level and outside the namespace the round-trip
  compares.
- **A Choice rule whose `Variable` path is absent raises an uncatchable `States.Runtime`** — it does
  **not** fall to `Default`, which covers only a value that is present and matches no rule. Both
  rules are `And` + `IsPresent`. The same hazard on the success side (`RecordSuccess` reads
  `$.mode`) is closed by `execute-ddl` defaulting the field, since only a create reaches it.
- **Marking is an explicit `mark` argument, not inferred from `storage is None`.** The inference
  reads correctly against today's two callers and is wrong for the next: SPEC-144's `apply-refresh`
  is a `DROP` + `CREATE` supplying a rebuilt `Storage`, so every refreshed table would come back
  unmarked.
- **`cpcommon.glue` registers its own four reason codes.** `TerminalError` validates at the raise
  site, and those codes were registered solely by `tscommon.messages`' import side effect — which a
  table-builder Lambda never imports. Without it every shape refusal on the refresh path would have
  raised `ValueError` and surfaced as the generic `unexpected_error`. The cost: an **unmapped** code
  no longer explodes, so `load_table_definition._SHAPE_REASONS` is asserted to cover
  `cpcommon.glue._SHAPE_REASONS` exactly.

### Deliberate deviations

- **FR-008's stub is a `Pass` state, not a state that raises.** Only a Task can throw-and-catch, and
  FR-009 adds exactly one function. The `Pass` emits the same `{Error, Cause}` shape a Catch does
  onto `$.error`, so `RecordFailure` needs no special case and `failure_reason` decodes
  `not_implemented`. **The equivalence is to the record, not the notification** — a `Pass` runs no
  Lambda, so nothing notifies; acceptable only because nothing but a hand-crafted message reaches it.
- **FR-005 AC4 struck** (recorded in the spec). The enum round-trip guard is provably vacuous:
  `",".join(s.split(","))` reproduces `s` for every `s`, and `values` is the only record of the
  original. Athena splits that property the same way, so the reconstruction is faithful to what the
  table already does.
- **FR-006's `format_changed` lives in `infer-schema`**, gated on `storage`. The spec said "in
  `load-table-definition`'s successor", but that state is `inspect-source`, which the same FR
  forbids touching, and the refresh tail is a `Pass`. `infer-schema` is the first point where both
  the folder's format and the table's SerDe exist. It reads `storage`, never `mode` (AST-asserted).
- **FR-007 AC1 narrowed to the durable user tables** — data-quality's `dq_tmp_*` opt out. AC2's
  rationale was **wrong** and is corrected in the spec: table-share renders its own DDL in
  `tscommon.ddl` and never calls this builder, so a shared copy is unmarked either way; the
  exclusion is still required, but not because "a copy is marked by its own creating call".
- **`REFRESH_MAX_DEFINITION_BYTES` is 40 KiB, not the first-drafted 48.** See Verification.

## What changed from earlier specs?

- **SPEC-090:** `clone_definition` now lives in `cpcommon.glue`; `tscommon.glue` re-exports it.
  Table-share's suite passes **unmodified**. Its operator-facing `detail` strings no longer say
  "can't be shared" — two arcs read them now, and a refresh failure in `logs/service=table-builder/`
  explaining that a table can't be *shared* sends its reader to the wrong control plane. The
  user-facing wording in `tscommon.messages` is unchanged.
- **SPEC-069/070:** `build_create_table_ddl` emits `portal.managed`; the four table-builder
  golden strings changed. `_tblproperties` takes `mark`.
- **SPEC-111:** `dqcommon.sql` passes `mark=False` at both call sites. Data-quality's generated DDL
  is **byte-identical** — verified old vs new across three formats, flat and partitioned, plus the
  raw-line table (which still emits no `TBLPROPERTIES` at all, SPEC-111 FR-002).
- **SPEC-067:** the envelope gained `mode`; an envelope without it produces a payload identical to
  an explicit `mode: "create"` one, pinned as a whole-dict comparison plus a key-set assertion.
- **SPEC-144 was corrected in place** — its FR-004 AC expected `portal.managed` among the properties
  reproduced from the captured definition, which `clone_definition` now strips. It is re-emitted by
  the builder instead, and a new AC pins that a refreshed table stays marked.

## Verification

`ruff check lambdas/` clean; **1631 tests pass, 2 skipped**; `tofu fmt -check -recursive` and
`tofu validate` clean; `tsc`, prettier, eslint and 1216 portal tests clean. Every PR merged on green
and `main` confirmed green after each.

New harnesses worth knowing about:

- **`test_glue_cpcommon.py`** runs the shape refusals **in a subprocess with only the cpcommon layer
  on `PYTHONPATH`** — `pytest lambdas/` imports `tscommon.messages` in the same process, so an
  in-process assertion would pass whether or not the registration exists. Verified non-vacuous by
  deleting the call.
- **The `portal.managed` guard scans the parsed AST, not the file text.** Two earlier versions were
  wrong in opposite directions: a literal grep waves through `from cpcommon.ddl import
  PORTAL_MANAGED` (a public name containing no matching literal), and a text scan flags every
  *comment* naming the property — including the ones warning against the `portal.managed` /
  `portal-managed` confusion. Verified against both offender shapes.
- **`test_table_builder_env.py`** joins `lambda.tf`'s environment block against every variable the
  two config modules `_require` at import — the PR #196 / #317 cold-start trap, which had no test
  anywhere in the repo. `update-function-code` succeeds against a function that cannot import, and
  `conftest.py` stamps the variables before collection, so nothing else could see it.
- **The size cap was re-derived after the review.** The first modelling test split the cap between
  columns and table properties and reported 30% of the state limit. That composition was doing the
  work: **columns ride the state three times** (`existingColumns`, infer-schema's `columns`, and
  again inside the DDL) while properties ride once. Measured at the maximising composition —
  32 KiB → 35%, 40 KiB → 44%, 48 KiB → 53% — the original 48 KiB **failed its own assertion**. This
  is the same defect `test_state_machines_cpcommon.py` documents: measuring a part of the state and
  certifying a bound that does not exist.

**Deferred to a live run (FR-008, still owed).** Two hand-enqueued refresh requests — one against a
flat portal-created table, one against a **partitioned** one — each expected to run to `Failed` with
`not_implemented`, with `load-table-definition`, `inspect-source` and `infer-schema` all completing
`ok` in CloudWatch and `logs/service=table-builder/`. The partitioned run is the criterion most
likely to fail, because it is the only one whose input is a table the pipeline did not write in this
run: FR-005's reconstruction is asserted against fixtures that were *built from the same renderer it
re-renders through*, so a live table is the only thing that tests the assumption rather than the
arithmetic. This arc has the precedent that makes it worth insisting on — SPEC-137 shipped
instrumented code whose layer attachment was missing, and every gate was blind to it.

No Help & guides change: nothing user-visible ships in this spec (SPEC-074 FR-005). One
component-inventory row updated (the table-builder types); the Lambda-side additions live in layers,
which the inventory does not cover.
