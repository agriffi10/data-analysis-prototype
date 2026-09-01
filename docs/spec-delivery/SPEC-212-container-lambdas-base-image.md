# Completed Spec — SPEC-212: Container Lambdas — the Base Image, ECR and the Build Pipeline

## What was completed?

One container image for the whole Lambda fleet, proven and pushed to a registry, **deployed
nowhere**. No `aws_lambda_function` changed and no import statement under `lambdas/` moved; the
fleet still ships as zips with layers. This is the half of the arc that cannot break production.

- `lambdas/Dockerfile` on `public.ecr.aws/lambda/python:3.12`, pinned by digest, built
  `--platform linux/amd64`, declaring no `CMD`. Its build context is the repository root with
  `lambdas/Dockerfile.dockerignore` as its ignore file — BuildKit reads a Dockerfile-specific
  ignore file in preference to the context root's, which is what lets the root `.dockerignore`
  keep excluding `lambdas` for the SPA's build.
- `lambdas/docker/assemble.py` — the single definition of the image's layout. The Dockerfile runs
  it and deletes it in the same layer; `test_image_layout.py` imports it. It is Python because the
  AWS base image ships no `find` and no `xargs`.
- `.github/scripts/lambda-image-matrix.sh` + `lambda-image-sweep.py` — the behaviour matrix, whose
  centrepiece imports **all 86 handler modules inside the built image, through the real runtime
  bootstrap**, each in its own subprocess, in about sixteen seconds.
- `lambdas/test_image_layout.py`, `lambdas/test_flat_layer_imports.py`,
  `lambdas/test_lambda_image_lifecycle.py`.
- `infra/modules/lambda-image/` — the ECR repository, `IMMUTABLE`, scan-on-push, with a retention
  bound a test computes.
- `.github/workflows/lambda-image.yml` (PR gate, path-filtered) and
  `.github/workflows/deploy-lambda-image.yml` (push to main, deliberately not filtered).
- Deploy-role ECR grants, and Checkov's dockerfile framework joining the existing scan.

### Deliberate deviations

- **Dependencies are installed into the interpreter's site-packages, not onto `/opt/python`.** A
  layer today mixes its package with its pip-installed dependencies in one directory, so
  reproducing that would make FR-002's set-equality criterion false by construction and decay the
  guard into a hand-maintained dependency list. Recorded as a spec correction, with a third guard
  covering the resolution order it changes.
- **Two guards the spec did not name** were added under FR-002: cross-function path collisions in
  the task root, and task-root names shadowing `/opt/python`. Both are consequences of one shared
  task root that no zip had, both measured empty today, both invisible to everything else.
- **Checkov's dockerfile scan covers `lambdas/Dockerfile` only.** Extending it to
  `apps/portal/Dockerfile` would have forced a shared enforce list to drop `CKV_DOCKER_3`, which
  the SPA image passes and this one cannot. Recorded in `security-baseline.md` rather than
  half-closed.
- **The image carries no `BUILD_VERSION` stamp.** `cpcommon.observability` falls back to
  `UNSTAMPED_VERSION` without raising, and the stamp belongs to the cutover, where a function's
  identity is decided. Named here so SPEC-213 does not discover it.

## What changed from earlier specs?

Nothing an earlier spec delivered was retired. Three things were **corrected**:

- The fleet is **86** functions, not 82, and `shared-space-common` publishes **ten** flat modules,
  not nine — `membership_index` landed after the spec was drafted. Both counts were wrong in
  SPEC-212 and in `ARCS.md`; both are now read from the tables rather than written down.
- IAM's 6,144-character managed-policy ceiling was asserted by nothing — `MANAGED_LIMIT` sat in
  `lambdas/test_deploy_platform_policies.py` referenced by no test. This arc's review found it and
  a concurrent change landed the wider fix first, measuring **every** managed policy rather than
  the two this arc touches; the grants PR rebased onto that and kept only what was its own.
- The deploy role's registry statements' `Resource` became a list, which exposed a latent hole:
  both wildcard tests decided "is this a wildcard statement" with `== "*"`, reading a list holding
  `"*"` as scoped.

## Verification

Locally, all at exit 0: `ruff check lambdas/ scripts/ .github/scripts/`, `mypy`,
`pytest lambdas/`, `scripts/validate_docs.py`, `tofu validate`, `tofu fmt -check -recursive`,
`npm run lint`/`format:check`/`build`, and the image built and its matrix run green. Counts are
deliberately not quoted — they move with every merge, and the exit codes are the claim.

**Three mutations were planted, run and reverted.** An unresolvable import reddened the matrix
naming the module and the missing package. A renamed `handler` attribute **survived the first
version** — the expected count was derived the same way as the observed one, so both fell to 85 and
agreed; the expectation now comes from the deploy table and the mutation fails. A `handler` that is
not callable is refused by the build. Separately, a policy 82 characters over IAM's ceiling passed
the whole suite and `tofu validate` before the budget assertion existed, and fails now.

Review found four things worth recording, all fixed: the Checkov numerator re-introduced the
numeric default the gate's own sentinel exists to refuse, so a hard-erroring narrowing step would
have reported clean; `assemble.py` was outside the mypy ratchet and did not pass it; the
constraint check read a requirement's trailing comment or environment marker as a constraint
(`polars  # pinned to ==1.12.0 elsewhere` was accepted); and the matrix could not recover from a
stale container of its own holding the port, failing with a message that named the image instead.

Deferred to deploy: that the deploy role's grant works against the real registry, and that the push
workflow's first run lands an image — both settle on the green run of their own PRs. Nothing here
is checkable from a signed-in browser session, so `docs/testing/e2e.md` gains no steps; the one
thing owed is recorded in `docs/testing/owed.md`.
