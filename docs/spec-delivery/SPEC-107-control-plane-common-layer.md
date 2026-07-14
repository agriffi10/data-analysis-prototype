# Completed Spec — SPEC-107: Shared `control-plane-common` Lambda Layer

A prerequisite refactor (no user-visible change): the JWT-verification path and the rest of the
surface duplicated across `tbcommon` and `tscommon` now live in ONE `cpcommon` layer that every
control-plane verb attaches, so the data-quality (108→114) and file-converter (115→121) arcs add a
domain layer each instead of a third and fourth copy of security-critical code. Shipped in two PRs:
deploy-role IAM (#222) then the extraction (#223).

## What was completed?

- **New `cpcommon` layer** (`lambdas/control-plane-common/cpcommon/`) — `config` (shared core +
  `_require`), `clients` (memoized boto3 union incl. `cognito()` + the memoized `PyJWKClient`),
  `errors`, `auth` (ID-token → actor), `registry` (`load` + `is_active` + `is_active_member`),
  `s3_listing`, `notify` (the `emit_notification` + `notifies_on_failure` skeleton), `messages`
  (SPEC-106 base table + domain hook), `events`. Built + published like the other layers in
  `deploy-lambdas.yml`; `PyJWT[crypto]` declared **once** in its `requirements.txt`.
- **`tbcommon`/`tscommon` reduced to domain-only** — the six duplicated modules **deleted** from
  each; verbs import the shared surface from `cpcommon` and domain helpers from their own layer.
  `tbcommon` keeps `config` (`PARTITION_TYPES`), `messages`, `notify` emitters + its DDL/Hive
  helpers; `tscommon` keeps `config` (`SHARE_MAX_*`/`RECIPIENT_KINDS`), `messages`, `notify`
  emitters, `athena`/`copy`/`ddl`/`glue`/`cognito`. Both domain `messages` register their reason
  codes with `cpcommon` for raise-time validation; the `auth` "no token" string is parameterized
  (`missing_token_detail`) so each domain keeps its exact wording (`missing idToken` /
  `missing actor token`). All ten verbs attach `cpcommon` + their domain layer (infer-schema also
  attaches polars = 3 of 5).
- **FR-003 — segment-level hidden-path rule + yield semantics.** `cpcommon.s3_listing` excludes an
  object if **any** path segment starts with `_`/`.` (not just the basename — so this arc's own
  `_data-quality-reports/` folder is never ingested as source data), plus a `user_settings/`
  exclusion. `list_data_objects` yields **absolute** keys by default with an opt-in `relative=True`
  (table-share passes it); a test pins inspect-source's `sampleObjectKey` stays absolute.
- **FR-004 — combined per-function size guard.** `deploy-lambdas.yml` now sums each function's
  package + every attached layer (unzipped) and fails above 240 MB, naming the function, its layers,
  and the total — before publish/attach. The per-layer polars check carries a note on why it was
  insufficient (Lambda's 250 MB ceiling is per-function across all layers + code).
- **FR-005 — raise-time reason validation + domain-extensible messages.** `TerminalError` raises
  `ValueError` at the raise site for a reason code not registered with `cpcommon.messages`; the
  data-quality/file-converter arcs rely on this. `register(domain_table)` returns a domain-scoped
  resolver (base + one domain table; re-defining a base code is a hard error, cross-domain
  duplicates are fine); substitution is `str.replace` on named tokens (never `str.format`).
- **Tests** — the entire existing Lambda suite passes with only import-path / patch-target changes
  plus new FR-003/FR-005 assertions; a fixture-based `cpcommon.auth` test pins the accept/reject
  outcome for each token shape and **both** domains' "no token" strings. An autouse conftest fixture
  snapshots/restores the now-shared `cpcommon` modules between tests (the config/`s3_listing` global
  patches used to be per-domain and could not leak; now they can).

## What changed from earlier specs?

- The `tbcommon`/`tscommon` layers no longer bundle `PyJWT` — it comes from `cpcommon`. The
  `config.py` fail-fast test moved to `control-plane-common/test_config_cpcommon.py` (the shared
  core it tests moved). No behaviour change to any verb path except the two named FR-003 fixes.
- **Not folded in:** `shared-space-common` (predates the convention, has its own CAS registry
  semantics) — a deliberate follow-up, not this spec.

## Follow-ups / notes

- A post-deploy live smoke of the table-builder + table-share control planes (FR-002) is a manual
  step, not a CI gate.
