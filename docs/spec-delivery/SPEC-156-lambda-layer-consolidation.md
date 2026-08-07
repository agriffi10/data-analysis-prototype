# Completed Spec — SPEC-156: Lambda Layer Consolidation — Folding the Deliberate Twins onto `cpcommon`

Pure consolidation in `lambdas/`. No new infrastructure, no layer-attachment change, and no
user-visible behaviour change (one enumerated exception, below).

## What was completed?

Shipped as four PRs: [#390](https://github.com/agriffi10/data-analysis-prototype/pull/390) (FR-004),
[#391](https://github.com/agriffi10/data-analysis-prototype/pull/391) (FR-001),
[#392](https://github.com/agriffi10/data-analysis-prototype/pull/392) (FR-003/005/006),
[#393](https://github.com/agriffi10/data-analysis-prototype/pull/393) (FR-002 + completion).

- **FR-004 — one JWKS path, and a lazily-resolving config.** `cpcommon.config` resolves on first
  access instead of `_require`-ing six environment variables at import, which is what had made
  `cpcommon.auth` unimportable for `notifications-writer`. That function now uses `cpcommon.auth`
  and `cpcommon.clients`; its local verifier and boto3 factory are gone.
- **FR-001 — one conditional-write CAS.** `cpcommon.cas` replaces the loops in
  `shared-space-common/casio.py`, `dqcommon/index_store.py` and `log-sweep/log_sweep.py`. The three
  retry caps (6/5/5) resolved to **one value, 6**.
- **FR-003 — one results location.** `cpcommon.results.results_location` replaces three builders in
  three shapes, plus two ad-hoc `ddl_output` prefixes.
- **FR-005 — one SQS parser, one Athena runner.** `cpcommon.events.parse_sqs_request` gained an
  `exc=` factory so shared-space can pass its `AuthorizationError`; `cpcommon.athena.bound_runner`
  replaced both per-plane DDL wrappers.
- **FR-002 — one failure-message resolver path.** `cpcommon.messages.Resolver` renders the **whole
  sentence** now, not just its tail: it gained `prefix`, `access_denied` and `fallback` templates,
  an opt-in `blank_unfilled`, a `template()` accessor and a `message()` method. `tbcommon`,
  `tscommon` and `dqcommon` keep only their tables and their trusted context. `tscommon` gained the
  tokens mechanism it lacked — `emit_failure` forwards `err.tokens` rather than discarding them, and
  `too_many_recipients` takes the cap from a **trusted** token filled from `config`, not an
  import-time f-string. `cpcommon.notify.dedup_id` replaced the verbatim copies in `tbcommon.notify`
  and `dqcommon.notify` and the inline third in `tb_notify_failure`.
- **FR-006 — dead code.** `S3RangeReader.readall` deleted; `s3_listing.is_ignored` kept public with
  a note (it is called internally, so deletion would have been wrong).

### Deliberate deviations

- **Phases were re-cut at build time, by explicit decision recorded in the spec.** Five code PRs
  became three; Phase 1 did not land alone. The cost is stated in the spec's Implementation Phases
  amendment.
- **No `component-inventory` row was added** (Phase 6 asked for one). That inventory is entirely
  browser-side — every file under `docs/component-inventory/` maps to `apps/portal/src/`, and the
  router's own rule is that a new row appears only when a whole area does. Inventing a `lambdas/`
  area for one spec is out of proportion; the new `cpcommon` surface is recorded in
  `architecture.md` → *Control Planes* → **Layers** instead, which is where a reader already looks
  for what `cpcommon` provides.
- **`tbcommon`'s marker-blanking is a resolver knob, not the default.** `dqcommon` documents that an
  unfilled marker must survive verbatim so its emitters are forced to pass the right tokens; making
  blanking universal would have silently changed that. Both behaviours are pinned by a test.

## What changed from earlier specs?

- **SPEC-082's `casio` CAS loop and SPEC-123's `dqcommon` index CAS** are gone — one loop in
  `cpcommon.cas`, cap 6. `DQ_INDEX_CAS_RETRIES` no longer exists. The superseded marker is in
  `decisions.md` at the SPEC-123 entry.
- **SPEC-107's `Resolver`** is a superset: the pre-156 constructor and `body()` are unchanged for a
  caller passing no new arguments, which is why `shared-space-common/messages.py` and
  `control-plane-dlq-drain` needed no edit.
- **`cpcommon.messages.register_reasons` has one caller left** (`cpcommon.glue`). Its docstring's
  claim about "domain modules that keep their own bespoke `failure_message` formatter" was corrected
  — no such module remains.
- **One user-visible message changed, and it is unreachable.** `malformed_event` under table-share:
  a shared base code that plane never declared, so it used to fall to `tscommon`'s unknown-code
  fallback (`"something went wrong."`) and now resolves through the base table
  (`"the request was malformed. Please try again."`). Table-share's only `parse_sqs_request` call
  raises `unauthorized` and no other site raises it under a table-share verb, so nobody has seen
  either wording. Pinned by `test_a_base_code_this_plane_never_declared_now_reads_what_it_means`.

## Verification

Local: `pytest lambdas` 2063 passed / 3 skipped, coverage 96.81% (floor 95); `ruff check lambdas/`
clean; mypy report-only **17** findings, below the 21 baseline SPEC-153 left. CI green on every PR.

**Byte-identity was measured rather than argued.** Every reason in all three planes was rendered
under every argument combination against both the pre-move and post-move implementations — 2214
messages per side — and diffed. Exactly one row differed (above). Reading the three implementations
side by side would not have found it; that method is the reusable part.

Nothing was deferred to a live check. No user-facing surface changed, so no Help & guides update was
owed (SPEC-074 sweep: checked, nothing to change).
