# Completed Spec — SPEC-062: Decompose Shared-Space Control Plane into Single-Task Lambdas

Structural refactor — **no observable behavior change**. The single 711-line
`shared-space-provisioner` (an `action`-switch monolith) is replaced by a Step Function that runs a
**validate-authorize** Lambda then a **`Choice`** routing by `action` to one of five verb Lambdas. The
request contract (SPEC-056), membership-tag model, and registry/cache shapes are unchanged.

## What was completed?

- **Common Lambda layer** `lambdas/shared-space-common/` (published as `dat-prod-shared-space-common`):
  `config`, `clients` (boto3 + JWKS factories), `auth` (`verified_username` + `authorize`), `registry`
  (load/reserve/finalize/save_members/set_status/delete), `membership` (Cognito slot assign/clear),
  `cache` (per-user cache + owner projection), `notify` (`emit_notification` — **SPEC-061 seam, no-op
  until that spec wires the queue URL + grant**). `fakes.py` = shared test doubles (not shipped).
- **Six Lambdas**, each a thin handler over the layer: `shared-space-validate` (`validate.py`) +
  `shared-space-{create,add-members,remove-members,leave,delete}`. Verbs consume the validator's
  output context `{action,actor,space,payload,registry,requestId}`; create stays **creator-only**
  (FR-006). Co-located `test_*.py` per function (48 tests total; happy/terminal/authz/idempotency).
- **Step Function** `state-machine.asl.json.tftpl` rewritten to `Validate → Choice(action) → <verb> →
  Succeed|Fail` with per-task Retry (Lambda service errors) + Catch → Fail.
- **Infra** (`infra/modules/shared-spaces/`): `lambda.tf` `for_each` over the six functions (placeholder
  + `ignore_changes=[filename,source_code_hash,layers]`, Cognito env on all); orchestrator policy
  `InvokeVerbLambdas` widened to the six function ARNs + Lambda log-groups widened to `…-shared-space-*`.
- **Deploy** `deploy-lambdas.yml`: new `layer` job builds+publishes the layer; six shared-space matrix
  rows attach it (deps come from the layer, not the zip); provisioner row dropped. Deploy-role IAM was
  widened in a prior PR (lambda-manage `…-shared-space-*`, log-groups, `PublishLayerVersion`).
- **Removed:** `lambdas/shared-space-provisioner/` (function + tests); TF destroys the function on apply.

## Deliberate deviations

- **FR-005 (per-verb least-privilege roles) descoped — user decision.** The Step Function + all six
  Lambdas keep the **single shared `orchestrator` role** (policy = union of all verbs' permissions +
  `lambda:InvokeFunction`). Per-verb roles remain a possible future hardening step.
- **Layer is CI-owned, not a TF resource** (mirrors how CI owns function code): TF sets
  `ignore_changes=[layers]`; `deploy-lambdas.yml` publishes the version and attaches it. This is the
  repo's first Lambda layer; the mechanism is reusable for a future external-libraries layer.

## What changed from earlier specs?

- The control-plane code (SPEC-051/053/054 logic) moved out of the monolith into the layer + verb
  Lambdas verbatim (same functions/semantics). Anything that referenced the `shared-space-provisioner`
  function name (deploy matrix, deploy-role ARN, orchestrator invoke target, log groups) now targets the
  six `shared-space-*` functions.

## Verification

`tofu -chdir=infra validate` clean; rendered IAM/state-machine JSON parse-checked; deploy-lambdas YAML
parsed; all 48 Python unit tests pass locally (`python3 test_*.py` per function — JS CI does not run
Python; **that per-function runner is retired — pytest is now the only one**, and on this plane's files
it could not see tests defined below its own block). End-to-end parity (a real create/add/remove/leave/delete via the live pipeline) is deferred to
deploy and tracked in `docs/testing/e2e.md`.
