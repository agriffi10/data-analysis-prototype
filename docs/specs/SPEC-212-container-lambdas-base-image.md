# Spec: Container Lambdas — the Base Image, ECR and the Build Pipeline

**ID:** SPEC-212
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-107/125/156 (`cpcommon` and the domain layers this image absorbs), SPEC-137 (the cold-start `ModuleNotFoundError` that broke sign-up for nine days — the failure this arc's smoke test is aimed at), SPEC-193/194 (the ECR repository, immutable commit-sha tags and the image behaviour-matrix pattern), SPEC-138/139 (the scanners the image joins)

**Arc:** Container Lambdas (212 → 213 → 214). Narrative in `ARCS.md`.

## Overview

Eighty-two Lambda functions are deployed as zip archives with ten shared layers attached in a
specific order. The arrangement works, and everything that is hard about it is hard for the same
reason: **what a function can import is decided at deploy time, by a table, and is not observable
anywhere else.** `.github/lambda-functions.json` says which layers a function gets,
`.github/lambda-layers.json` says what each layer holds, `deploy-lambda.sh` attaches them in a
literal order because a later layer shadows an earlier one, and `lambdas/test_deploy_matrix.py`
joins all of it against what each function actually imports — because without that join, a missing
layer is a `ModuleNotFoundError` at the next cold start, in production, with a green suite behind it.
That has already happened once, and it lasted nine days.

This arc replaces the whole arrangement with one container image. Dependencies are installed once,
the shared code is copied in once, and every function runs the same image with a different command.
What a function can import stops being a deploy-time join and becomes a property of an artifact that
can be pulled and run.

**This spec builds the image and the pipeline that produces it, and changes no function.** Nothing
is cut over here; at the end of it an image exists in ECR, is proven, and is deployed nowhere. That
is deliberate — it is the half of the arc with no way to break production, and it de-risks the half
that has one.

## Scope

### In Scope

- `lambdas/Dockerfile` on the AWS Python 3.12 base image, installing every dependency and copying
  every function and every shared module.
- An ECR repository for it, with immutable tags and a lifecycle policy.
- Deploy-role IAM for ECR, landing in its own PR ahead of the repository.
- A build-and-push workflow keyed on the commit sha, and a pull-request gate that builds the image
  and asserts its behaviour.
- The behaviour matrix, whose centrepiece is an **import smoke test over every function**.
- The image joining the existing scanners.

### Out of Scope

- **Changing any function's packaging.** No `aws_lambda_function` is touched. That is SPEC-213.
- **Deleting the layers, the deploy tables or their tests.** They keep working, unchanged, through
  this spec and the next. That is SPEC-214.
- **One image per function.** A single image with a per-function command is the shape, and it is
  what makes the module in SPEC-213 a single module.
- **Converting `shared-space-common` into a package.** Its flat modules are copied as flat modules;
  the import consequence is named in FR-004 and guarded, not refactored away.
- **Changing the Python version.** Every function is `python3.12` today and the base image is 3.12.
- **`arm64`.** The image is `linux/amd64`, matching every function's current architecture.

---

## Functional Requirements

### FR-001: The image

#### Description:

One Dockerfile at `lambdas/Dockerfile`, built from `public.ecr.aws/lambda/python:3.12`.

#### Acceptance Criteria:

- [ ] It installs the union of every layer's `requirements.txt` — `cpcommon`'s `PyJWT[crypto]` and
      `log-foundry`, the table-builder polars pin and the data-quality polars pin — plus
      `lambdas/requirements.txt`.
- [ ] Every dependency carries an **explicit version constraint**, and the build fails on one that
      carries none. Not "is pinned to an exact version": `cpcommon` declares `PyJWT[crypto]>=2.8,<3`
      deliberately while `log-foundry==0.6.0` is exact, and a criterion demanding exactness would
      fail against this spec's own declared inputs and would drag a dependency-policy change into a
      packaging spec.
- [ ] It builds `--platform linux/amd64`, stated explicitly rather than inherited from the runner.
- [ ] The build is reproducible from a clean checkout with no network access beyond the package
      index and the base image.
- [ ] The image declares no `CMD`. Every function supplies its own command, and an image with a
      default handler would let a function that forgot to declare one start and do the wrong thing.

### FR-002: The layout reproduces today's import paths exactly

#### Description:

Shared code lands on `/opt/python` and function code lands in `${LAMBDA_TASK_ROOT}` — the same two
places a layer and a zip put them today. No import statement anywhere in `lambdas/` changes.

#### Acceptance Criteria:

- [ ] Every layer package (`cpcommon`, `tbcommon`, `tscommon`, `dqcommon`, `fscommon`, `focommon`,
      `arcommon`) is present at `/opt/python/<package>/`.
- [ ] `shared-space-common`'s flat modules are present as top-level modules at `/opt/python/`.
- [ ] Every function directory's `.py` modules are present at `${LAMBDA_TASK_ROOT}/`, flat, exactly
      as a zip deploys them today.
- [ ] No test module, no `conftest.py`, no `__pycache__` and no `requirements*.txt` is present in the
      image; a test asserts each absence by pattern rather than by naming files.
- [ ] A test asserts the set of packages under `/opt/python` equals the set the layer table declares,
      and the set of flat modules there equals `shared-space-common`'s declared `modules` list — the
      same set-equality guard the layer build already carries, moved onto the artifact.
- [ ] `git diff` over `lambdas/**/*.py` for this spec is empty apart from new test files: the
      packaging changes, the code does not.

### FR-003: Every function's handler imports — proven by running it

#### Description:

The behaviour matrix imports every function's handler module inside the built image. This is the
whole reason the arc is worth doing, and it is the check that would have caught SPEC-137.

#### Acceptance Criteria:

- [ ] For every function, the matrix runs the image and imports its handler module, asserting the
      declared handler attribute exists and is callable.
- [ ] The function list is **derived**, not hand-written: it comes from the directories under
      `lambdas/` that contain a handler module, and a directory whose handler cannot be located
      fails the matrix rather than being skipped.
- [ ] A deliberately broken import — a module referencing a package the image does not carry — is
      asserted to fail the matrix. This is the arc's one planted mutation, because a smoke test that
      imports nothing and reports success is indistinguishable from one that works.
- [ ] The matrix reports **how many** functions it imported, and a test asserts that count equals the
      number of function directories, so a silently shrinking sweep is visible.
- [ ] The matrix asserts the interpreter in the image is 3.12.

### FR-004: The widened import surface is guarded

#### Description:

Today a function can import only the layers attached to it. In one image every function can import
everything — including `shared-space-common`'s nine flat top-level modules (`config`, `auth`,
`registry`, `cache`, `notify`, `messages`, `membership`, `casio`, `teardown`), which are generic
enough to be imported by accident from another plane and would resolve.

#### Acceptance Criteria:

- [ ] An AST sweep over `lambdas/` asserts that no function outside the shared-space plane imports
      any of those nine names as a top-level module.
- [ ] The sweep counts attribute-style usage too — `import x` followed by `x.y()` — not only
      `from x import y`, since a submodule-path scan alone undercounts consumers.
- [ ] The exemption list is by **exact directory path**, and a test asserts every exempted path
      exists.
- [ ] The spec states the widening plainly rather than claiming parity: this image gives every
      function a strictly larger import surface than its zip has today, and the sweep — not the
      packaging — is what keeps that from mattering.

### FR-005: ECR

#### Acceptance Criteria:

- [ ] A repository dedicated to the Lambda image, separate from the SPA's; the two have different
      lifecycles and a shared repository would make one's lifecycle policy the other's problem.
- [ ] `IMMUTABLE` tags. The tag is the commit sha; there is no `:latest`.
- [ ] Image scanning on push is enabled.
- [ ] A lifecycle policy retains a bounded number of images, and the bound is **computed** in a test
      from the merge rate and the rollback window it is meant to cover, naming that budget.
- [ ] The deploy role's ECR grants land in their own PR **before** the repository, and the actions
      that cannot be scoped to a repository ARN sit alone in a wildcard statement, measured with
      `simulate-custom-policy` rather than assumed.

### FR-006: The pipeline

#### Acceptance Criteria:

- [ ] A pull-request workflow builds the image and runs the behaviour matrix, path-filtered on
      `lambdas/**`, the Dockerfile, the requirements files and the workflow itself — mirroring
      `spa-image.yml`, which exists because a gate that only runs after merge can only redden main.
- [ ] A push-to-main workflow builds and pushes the image tagged with the commit sha, **not**
      path-filtered — the image has to track main exactly, or "which commit is deployed" stops
      having an answer.
- [ ] The push workflow runs the same matrix script against the same image before it pushes.
- [ ] A build failure fails the job. A matrix step that cannot run fails the job too: "did not run"
      is never "clean".
- [ ] Concurrency is grouped per ref, and the main build is not `cancel-in-progress`.

### FR-007: The scanners see it

#### Acceptance Criteria:

- [ ] The image's Dockerfile is covered by the existing IaC/container scanning in `security.yml`, at
      the mode the repo's `GATE_*` block declares, with any new finding given a written disposition
      in `docs/security-baseline.md` rather than a suppression.
- [ ] No scanner is added, removed or re-pinned by this spec.

---

## Data Model

Not applicable — this spec produces an artifact, not a type. The image's contract is its layout:

```
/opt/python/                 # what a layer provides today
  cpcommon/  tbcommon/  tscommon/  dqcommon/  fscommon/  focommon/  arcommon/
  config.py auth.py registry.py cache.py notify.py messages.py membership.py casio.py teardown.py
/var/task/                   # ${LAMBDA_TASK_ROOT} — what a zip provides today
  pre_signup.py  post_confirmation.py  … one flat module per function
```

## File & Folder Structure

```
lambdas/
├── Dockerfile
├── .dockerignore                      # or an addition to the root one
├── test_image_layout.py               # the /opt/python and task-root set-equality guards
└── test_flat_layer_imports.py         # the FR-004 AST sweep

.github/
├── scripts/lambda-image-matrix.sh     # build-independent: takes an image tag, asserts behaviour
├── workflows/lambda-image.yml         # PR gate
└── workflows/deploy-lambda-image.yml  # main build + push

infra/modules/lambda-image/            # the ECR repository, its lifecycle policy and outputs
infra/modules/base/policies/           # the deploy role's ECR grants (separate, earlier PR)
```

## Implementation Phases

### Phase 1: Deploy-role IAM

- The ECR grants for the deploy role, measured with `simulate-custom-policy`, in their own PR,
  merged and applied before anything below.

### Phase 2: The Dockerfile and its layout guards

- The image, the pinned dependency install, the two copy layouts.
- `test_image_layout.py`, `test_flat_layer_imports.py`.

### Phase 3: The behaviour matrix

- `lambda-image-matrix.sh`: the derived function list, the per-function import, the count assertion,
  the interpreter check.
- The planted broken import, verified to fail, then reverted.

### Phase 4: The repository and the pipeline

- The `lambda-image` Terraform module, the lifecycle bound and its computed test.
- The PR gate and the main build-and-push.
- The scanner pass and any disposition it needs.
