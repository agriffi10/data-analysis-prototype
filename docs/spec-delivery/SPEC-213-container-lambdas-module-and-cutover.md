# Completed Spec — SPEC-213: the `docker-lambda` Module and the Cutover

All 86 Lambdas run one container image. SPEC-212 built and proved that image and deployed it
nowhere; this spec put every function on it and made CI keep them there.

## What was completed?

- **`infra/modules/docker-lambda`** — one container-packaged function, its log group, and outputs
  `function_name` / `function_arn` / `invoke_arn` / `log_group_name` / `log_group_arn`. Every
  function in `infra/` is a call to it; no `aws_lambda_function` is declared anywhere else, and no
  `archive_file` placeholder survives.
- **172 `moved` blocks**, one per function and one per log group, in a `moved.tf` beside each
  plane's `lambda.tf`.
- **Consumers on outputs** — 104 references, six planes' constructed-ARN locals, four module outputs
  and two root outputs. All 11 `aws_lambda_permission` resources and both event-source mappings bind
  to `function_arn`.
- **`Deploy Lambdas` points every function on every run**, reconciles by name, and then **invokes
  one function per plane and each standalone** to prove the deployed artefact starts. An
  `image_tag` dispatch input is the rollback.
- **`Deploy Infrastructure` waits for the commit's image** before applying, on push and dispatch
  alike.
- New guards: `lambdas/test_the_cutover.py`, `lambdas/test_cold_start_probe.py`,
  `lambdas/test_probe_cold_start.py`, the permission rule in `.github/scripts/lambda_plan_guard.py`,
  and `tf_blocks`' packaging-agnostic readers.

### Deliberate deviations

- **FR-005's zip/layer removal and the count landed in the spec's last PR, not the cutover PR.** An
  amendment mid-build said "deferred to SPEC-214" and was wrong; the constraint was real but
  temporary. Editing the deploy pipeline puts it in `plan_deploy.py`'s `HARD_GLOBAL_PATHS`, which
  during the cutover would have forced a full-fleet deploy concurrent with the apply that was
  deleting and recreating those very functions. The apply completed; the constraint expired.
- **FR-003 has one named exemption.** `shared-spaces` keeps `local.shared_space_function_arns`: one
  `orchestrator` role serves both the machine and the verbs there, so consuming the module output
  is a genuine cycle. Splitting a privileged inline policy on the plane that owns the delete cascade,
  during the cutover, to buy a tidier test was refused.
- **Four callers lost the execution-policy half of their `depends_on`.** `api`, `auth` (twice) and
  `observability` render that policy from the function's own log-group ARN, which now lives inside
  the module — a cycle, reproduced before it was accepted. It costs nothing on this apply (the log
  groups moved rather than being replaced) and only a from-scratch apply has a window.
- **`control-plane-dlq-drain` is not probed.** Invoking it deletes DLQ messages and notifies users;
  recorded in `docs/testing/owed.md`, as FR-006's third criterion directs.
- **Two checkov IDs that newly pass are deliberately not enforced.** `CKV_AWS_115` and
  `CKV_AWS_117` pass because the module declares a `dynamic "vpc_config"` that yields nothing and a
  `-1` concurrency sentinel — a structural pass that contradicts two written accepts. Reasoning in
  `docs/security-baseline.md`.

## What changed from earlier specs?

- **SPEC-214 is amended twice.** Its In Scope gains `deploy-lambda.sh` and
  `test_deploy_packaging.py` — that suite extracts and *runs* a script nothing calls any more. Its
  FR-004 clause about keeping a zip rollback possible is marked superseded in place: no pipeline can
  deploy a zip function now, and the rollback that exists is an image tag.
- **A doc sweep, and it took two passes.** The first corrected the sites someone remembered; a
  cross-site review found nineteen more, most of them a *second* stale paragraph in a file whose
  first had already been fixed. The mechanical form is
  `grep -rniE 'placeholder|layer|zip|artifacts bucket'` over `docs/`, `*/info/`, `*/README.md` and
  `.github/` — SPEC-214's FR-005 now carries it as a criterion rather than an intention.
  Corrected here: the Lambda rulebook, `deploy-role-iam.md`, `infra/info/control-plane-shape.md`,
  both workflow READMEs, the root `README.md` bootstrap (which had become *unrunnable* —
  `TF_VAR_lambda_image_tag` is required with no default), `shared-layer.md`'s polars import barrier
  (which the image removed, so the doc asserted a safety property that no longer holds),
  `lambdas/info/INDEX.md`, four module READMEs, `analytics.md`, `docs/process/`, `ecr.tf` and
  `lambdas/info/deployment.md`. `architecture.md`'s ADR rows 31 and 47, and
  `docs/decisions/identity-and-access.md`'s layer sentence, carry superseded markers.
- **The infra rollback was documented and is now documented as not viable.** Reverting recreates 86
  functions from placeholder zips that no pipeline can replace — the code rollback is the one that
  exists, and it is the one that was exercised.

## Help & guides

Nothing user-facing changed. A packaging change is invisible to the browser, and the sweep of
`helpContent.ts` found no deployment content to correct.

## Verification

Local: `ruff`, `mypy`, `pytest lambdas/` (2537), `validate_docs.py`, and `tofu fmt -check` /
`validate` **on the 1.8 line CI pins** rather than the newer local binary. `checkov` 3.3.9 measured
before and after: 955/763 → 1119/585, no enforced ID unevaluated or newly failing.

Deployed: the apply reported `97 added, 0 changed, 97 destroyed` — 86 functions and 11 permissions,
so no log group was created or destroyed and all 172 moves landed clean. The plan showed all 11
permissions as `must be replaced`, which is the outage this spec was written around, visible before
it could happen. `api.dataquarry.app` answered 401 from the handler afterwards.

**FR-006 observed:** the probe's first run reported all 14 reaching their handler — six
`validate-authorize` verbs refusing with `TerminalError`, two writers with `ValidationError`,
pre-signup with `Exception`, and five returning cleanly.

**FR-007 exercised**, and this is what it was exercised against: run
[33667798352](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33667798352) pointed
all 86 at `9d1c8fa1`'s image and run
[33668619737](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33668619737) returned
them to `1028b8b5`. Each function's `Code.ImageUri` was read back and compared by
`point-lambda.sh`, so a green run *is* the confirmation; the probe passed on both.

Still owed, in `docs/testing/owed.md`: no init **failure** has been observed on this account, so the
probe's failure-side discriminator is inferred from AWS's documented output rather than measured
here. It is safe in the false-positive direction.
