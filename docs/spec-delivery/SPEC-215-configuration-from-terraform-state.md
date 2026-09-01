# Completed Spec — SPEC-215: Configuration from Terraform State

## What was completed?

- **The deploy workflows read Terraform outputs instead of repository variables.** `deploy-app.yml`
  and `deploy-config.yml` now set up OpenTofu, assume the deploy role, init the same backend
  `deploy-infra.yml` uses, and run **one** `tofu output -json` per job.
- `.github/config-outputs.json` — the one map from Terraform output name to configuration key,
  eight entries, read by both workflows and by `validate_feature_flags.py`.
- `.github/scripts/resolve-config.sh` — one read, one step output per key, refusing an **absent or
  empty** output by name and reporting every fault at once. `--mapping` is a parameter so a later
  consumer can point it at its own map.
- `deploy-app.yml`'s build env and render step now name the **same** resolved output per key, so the
  bundle's dev fallback and the served document cannot disagree about where a value came from.
- `deploy-config.yml`'s matrix names a configuration **key** (`bucket_key: userSpaceBucket`) rather
  than a repository variable, and its hand-written empty-bucket guard was replaced by the resolver's.
- Tests: `lambdas/test_config_outputs.py` (the map against the classification, `infra/outputs.tf`,
  `sensitive`, the container entrypoint's `KEYS`, and the deploy role's existing state-bucket grant),
  `lambdas/test_resolve_config.py` (the real script against fixture output documents),
  `lambdas/test_config_workflows.py` (the derived version and backend agreements, the retired-name
  sweep with a positive control, and the resolve-before-any-AWS-write ordering).

### Deliberate deviations

- **The map is eight keys, not the spec's eighteen, and no Terraform outputs were added.** The spec
  was authored 2026-08-28 believing the runtime document carried the eight control-plane queue URLs,
  `cognitoIdentityPoolId` and `athenaWorkgroup`. Arc B had already removed those: the browser writes
  no queue, so the URLs are the API function's configuration and go module-to-module in Terraform.
  Verified three ways — the classification is ten keys, the container entrypoint's `KEYS` is the same
  ten, and the live `/config.json` carries those ten and `version`. FR-002's **rule** (`REQUIRED ∪
  OPTIONAL` minus the genuine inputs) was implemented as written; only its stale enumeration changed,
  and the spec was corrected in the same PR.
- **`deploy-app.yml` gained an `appUrl` agreement check** that the spec does not ask for. Resolving
  `appUrl` from `cloudfront_domain` while `TF_VAR_app_url` stays a repository variable makes them two
  independent statements of one origin, where before they could not disagree; the divergence is a
  broken sign-in with nothing red. Rejected doing it as a Terraform `precondition` on the output:
  being wrong there fails every infrastructure apply, where failing in the app deploy leaves the live
  document untouched.
- **The resolver treats every mapped output as required**, which is stricter than the document's own
  `REQUIRED` list. Every mapped value is one Terraform always computes, so an empty one means the
  state is not what the deploy assumes. The document's `REQUIRED` guard is unchanged and still
  decides what may be published.
- **No repository variable was deleted by this change.** That is an outward-facing edit to the
  repository's settings; the list is below, for a human to apply.

## What changed from earlier specs?

- **SPEC-192's third wiring site changed.** "The GitHub repository variable" is now
  `.github/config-outputs.json` for every derived key; only a genuine input is still a variable.
  `apps/portal/info/runtime-configuration.md`, `docs/process.md` §6, the SPEC-192 register entry and
  CLAUDE.md's digest clause were all updated, and `.github/workflows/README.md`'s operator tables
  were rewritten — that file *was* the manual `tofu output` → settings-page transport.
- **SPEC-162's publish workflow** lost its hand-written empty-variable guard and gained a
  mapping cross-check in `scripts/validate_feature_flags.py` (`bucket_var` → `bucket_key`). Without
  it nothing checked that the matrix named a resolvable key — measured: a bogus `bucket_var` left the
  validator and its suite entirely green.
- **A false claim in `runtime-configuration.md` was corrected**: it credited
  `lambdas/test_feature_flags_config.py` with CORS, CSP, bucket-policy and deploy-role reachability
  assertions that had been removed. The deploy-role half is asserted again, in
  `lambdas/test_config_outputs.py`.

## What SPEC-202 inherits — not optional

When SPEC-202 removes the CloudFront path it deletes both consumers of the resolved values in
`deploy-app.yml`, and **the `appUrl` row must repoint from `cloudfront_domain` to `spa_origin` in
the same change**. `appUrl` is in `REQUIRED_CONFIG` and the container path needs it;
`cloudfront_domain` is deleted with the distribution, so `test_config_outputs.py`'s
output-existence assertion goes red the moment it is. `spa_origin` already exists and is the value
it becomes. SPEC-202 should also delete `deploy-app.yml`'s `appUrl` agreement check, which exists
only because `cloudfront_domain` and `var.app_url` are two statements of one origin.

## Repository variables to delete (a human action, not done here)

Retired by this change (6): `API_BASE_URL`, `VITE_COGNITO_USER_POOL_ID`,
`VITE_COGNITO_USER_POOL_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_S3_USER_SPACE_BUCKET`,
`VITE_S3_SHARED_SPACE_BUCKET`.

Already dead before this change — they mirror an output and no workflow reads them (10):
`VITE_ARCHIVE_QUEUE_URL`, `VITE_ATHENA_WORKGROUP`, `VITE_COGNITO_IDENTITY_POOL_ID`,
`VITE_DATA_QUALITY_QUEUE_URL`, `VITE_FILE_OPS_QUEUE_URL`, `VITE_FILE_SEND_QUEUE_URL`,
`VITE_NOTIFICATIONS_QUEUE_URL`, `VITE_SHARED_SPACE_QUEUE_URL`, `VITE_TABLE_BUILD_QUEUE_URL`,
`VITE_TABLE_SHARE_QUEUE_URL`.

**Delete only after the post-merge Deploy App and Publish Config runs are green** — deleting them
first would break the deploy they precede. The eleven survivors and the reason each is an input
rather than an output are tabled in `.github/workflows/README.md`.

## Verification

Local: `npm run format:check`, `lint`, `test`, `build`, the full `pytest` suite, `ruff` over all
three trees, `tofu fmt -check` and `validate`, and `scripts/validate_docs.py`. Three guards were
mutation-tested and reverted — a `sensitive` output, an unresolvable `bucket_key`, and a build/render
source divergence sharing a trailing token — each reddening only the guard that owns it.

Deferred to deploy: the real `tofu init` + `tofu output -json` against remote state, which needs the
deploy role and cannot run locally. The byte-identity of the rendered document was checked against a
capture of the live `/config.json` taken before the merge.
