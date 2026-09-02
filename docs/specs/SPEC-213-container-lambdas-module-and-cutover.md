# Spec: Container Lambdas — the `docker-lambda` Module and the Cutover

**ID:** SPEC-213
**Status:** In Progress
**Last Updated:** 2026-08-28
**Depends On:** SPEC-212 (the image and the repository this spec deploys), SPEC-193/194 (the ECS precedent: `ignore_changes` on the artifact reference means **CI must point the resource**, and a pipeline that publishes without pointing leaves a failure indistinguishable from the one the platform is tested for), the seven control-plane modules and the standalone functions

**Arc:** Container Lambdas (212 → 213 → 214). Narrative in `ARCS.md`.

## Overview

SPEC-212 built an image and proved it. This spec puts every function on it.

One Terraform module — `infra/modules/docker-lambda` — declares a container-packaged function, and
every function in the repo becomes a call to it. The module takes the things that actually differ
between functions (name, command, environment, timeout, memory, role) and outputs the function's
**name and ARN**, so a module that needs to grant, trigger or reference a function consumes an
output rather than reconstructing a name from a string template.

The cutover is where the risk in this arc lives, and it has a specific shape. Terraform will own the
function and CI will keep owning the code, exactly as today — which means `image_uri` carries
`ignore_changes`, which means **CI has to point each function at the new image on every deploy**. A
pipeline that builds and pushes an image and never calls `update-function-code` leaves all 82
functions on the previous image, and every one of them keeps working, so nothing goes red. That is
the same trap the SPA container hit, recorded once already, and it is the one this spec is written
around.

## Scope

### In Scope

- `infra/modules/docker-lambda`: one module, `package_type = "Image"`, a per-function
  `image_config.command`, and `function_name` / `function_arn` outputs.
- Every existing `aws_lambda_function` replaced by a call to it, with its environment, timeout,
  memory, concurrency, VPC configuration and log group preserved.
- Every consumer of a function name or ARN rewired onto the module's outputs.
- `deploy-lambdas.yml` rewritten to point every function at the image, sharded, and to fail if it
  pointed fewer functions than exist.
- A completeness guard: no zip-packaged function survives.

### Out of Scope

- **Deleting the layers or the deploy tables.** They stay attached and correct through this spec; a
  container function simply ignores them. SPEC-214 removes them, after this has settled.
- **Changing any function's behaviour, environment, timeout, memory or role.** This is a packaging
  change, and a test asserts that claim rather than the spec merely making it.
- **Adding or removing a function.**
- **Moving the API function into the VPC**, or moving any function out of one. The API function is
  deliberately not in the VPC and stays that way.
- **Changing the image**, with ONE carve-out. SPEC-212's artifact is consumed as built, except
  that it gains a `BUILD_VERSION` stamp. SPEC-212's delivery doc handed that forward in terms —
  *"the stamp belongs to the cutover, where a function's identity is decided. Named here so
  SPEC-213 does not discover it"* — and this bullet as first written contradicted it. Without the
  stamp every record all 86 functions emit carries the `0.0.0` sentinel from the moment they move,
  and correlating a record with a deploy is the field's only purpose. The env-borne alternative is
  closed: Tofu owns the environment map and a test already forbids Terraform setting the variable.
  So the Dockerfile takes a build argument and writes the file to the task root, which
  `cpcommon.observability` already reads — no code change, and the zip and container fleets answer
  identically. Amended mid-build under §3's rule that a scope change updates the spec rather than
  diverging from it silently.

---

## Functional Requirements

### FR-001: The module

#### Description:

`infra/modules/docker-lambda` declares one container-packaged function.

#### Acceptance Criteria:

- [ ] Its inputs are: function name, the image repository URL, the image tag, the command
      (`["<module>.<handler>"]`), the execution role ARN, environment variables, timeout, memory,
      optional reserved/provisioned concurrency, optional VPC configuration, and log-retention days.
- [ ] Its outputs are `function_name` and `function_arn`, and a test asserts both exist.
- [ ] It creates the function's CloudWatch log group, so a function and its log group cannot be
      declared in different places.
- [ ] `package_type = "Image"`, `image_uri` set from the repository and tag, `image_config.command`
      set from the input.
- [ ] `lifecycle { ignore_changes = [image_uri] }`, and **`layers` is not declared at all** — a
      container function has none, and leaving a stale `ignore_changes = [layers]` would be a fossil
      that reads as meaningful.
- [ ] The module has a `README.md` beside its `.tf`, carrying its reasoning, per the repo's module
      convention.
- [ ] A test asserts every module call supplies a command, and that no command is the empty list.

### FR-002: Every function moves

#### Acceptance Criteria:

- [ ] Every `aws_lambda_function` resource in `infra/` is replaced by a `docker-lambda` module call.
- [ ] A test over the rendered plan asserts **every** Lambda function has `package_type = "Image"`
      and an `image_uri` pointing at the one repository — the guard is derived from the plan, not
      from a list somebody maintains, so a function left behind fails rather than being missed.
- [ ] A test asserts no `archive_file` placeholder data source remains for any function.
- [ ] For each function, its environment map, timeout, memory, architecture, role ARN, reserved
      concurrency and VPC configuration are unchanged. The comparison is made against values
      captured from the pre-cutover plan and committed as a fixture, so "unchanged" is checked
      rather than asserted.
- [ ] The command for each function is `<module>.<handler>`, matching the `handler` value it has
      today; a test derives the expected command from the existing handler strings and compares.

### FR-003: Names and ARNs come from outputs

#### Description:

The module exists partly so that other modules stop rebuilding function names from templates.

#### Acceptance Criteria:

- [ ] Every place that grants a permission on a function, wires a trigger to it, references it in a
      state machine, or names it in an event source mapping consumes `function_arn` or
      `function_name` from the module.
- [ ] A test asserts no `.tf` file constructs a Lambda function ARN by string interpolation, with
      **one named exemption**: `shared-spaces` keeps `local.shared_space_function_arns`. That plane
      has ONE `orchestrator` role serving both the state machine and the verbs, so the policy that
      consumes the ARN list is the same policy the functions depend on — reading the module output
      there is a genuine cycle, reproduced before it was accepted. The exemption is a **named local
      in a named module**, never a class of location: "inside a `templatefile()` input" was tried and
      admits every ASL definition in the repo. Consequence worth knowing: that grant is the one
      Lambda grant that plans no diff across the replacement, which is safe only because the ARN it
      builds is stable. Amended mid-build under §3's rule.
- [ ] The root module's per-function outputs that CI consumes are produced from the module outputs.

### FR-004: The image tag, and the bootstrap order

#### Description:

`image_uri` is ignored after creation, but it must be valid **at** creation — a container function
cannot be created pointing at a tag that does not exist.

#### Acceptance Criteria:

- [ ] The tag is supplied as `TF_VAR_lambda_image_tag` from `${{ github.sha }}` — a genuine input,
      not a repository variable, and not a Terraform output.
- [ ] The variable has **no default** and a `validation` block refusing an empty string, because an
      empty `TF_VAR_` satisfies a required variable and overrides a default, and an unset repository
      variable renders as exactly that.
- [ ] The ordering constraint is stated in `lambdas/info/deployment.md`: the image build must have
      pushed the current sha before an apply creates a function from it, exactly as the first
      `deploy-infra` apply must precede the first `deploy-lambdas` run today.
- [ ] An apply for a sha whose image is absent fails at plan or apply time with a legible error, not
      at the function's first invocation.

### FR-005: CI points every function, and proves it did

#### Description:

The trap. `ignore_changes` means Terraform will never move a function onto a new image; only
`update-function-code --image-uri` does.

#### Acceptance Criteria:

- [ ] `deploy-lambdas.yml` calls `update-function-code --image-uri <repo>:<sha>` for every function,
      sharded as it is today.
- [ ] The workflow **counts** the functions it pointed and fails if that count is less than the
      number of functions Terraform declares — a partial deploy is a red job, not a quiet one.
- [ ] The workflow waits for each update to reach `Successful` before reporting success; a container
      function's update is asynchronous and a job that returns on the API call alone reports a
      deploy that has not happened.
- [ ] A function whose update fails fails the job, naming the function.
- [ ] The workflow no longer builds or uploads a zip for any function, and no longer publishes or
      attaches a layer version. **Held back from the cutover PR, not from this spec**, and the
      distinction matters because an earlier amendment said "deferred to SPEC-214" and was wrong:
      editing `deploy-lambdas.yml`, `plan_deploy.py` or `point-lambda.sh` puts them in the planner's
      `HARD_GLOBAL_PATHS`, which during the cutover would have forced a **full-fleet deploy
      concurrent with the apply that was deleting and recreating those very functions** — different
      `concurrency` groups, so a genuine race, measured with the planner. That apply completed, so
      the constraint expired and the work lands in this spec's final PR, where the forced full-fleet
      deploy is exactly what the criterion above asks for. (The layer *tables*, `build-layer.sh` and
      `deploy-lambda.sh` are SPEC-214's, and stay.)
- [ ] The count is against **what Terraform declares**, and the chain is stated rather than implied:
      the `pointed` job holds deployed == the deploy table, and `deploy-infra.yml`'s plan guard holds
      that table == the planned fleet. `.github/lambda-functions.json` is in **that** workflow's
      `paths:` filter, so the table cannot diverge from Terraform without an edit that runs the
      guard. The chain closes on the edit, not on every push.
- [ ] `Deploy Infrastructure` and `Deploy Lambdas` still run in parallel on a push, and the
      `ResourceConflictException` window that already exists between an env-block apply and a
      concurrent function update is documented as unchanged rather than silently inherited.

### FR-006: The first invocation is exercised, not assumed

#### Description:

Every gate in this repo has at some point been blind to a cold start. This one is not allowed to be.

#### Acceptance Criteria:

- [ ] After the cutover, one function per plane plus each standalone function is invoked once
      against the deployed environment, and the invocation is asserted to have reached its handler.
      **The assertion is what is unambiguous in production**, not the list of three error types this
      criterion first named — amended under §3's rule after THREE designs, each of which looked
      right until it was driven. The list is the failure mode rather than the fix: an exception
      raised at import reports its own class (`RuntimeError`), which no list of runtime error names
      contains, and this fleet runs `observability.init` at module scope. `START RequestId` is
      written *before* init and regardless of its outcome. An `errorType` namespace rule
      (`Runtime.*`) passes that same case. `REPORT RequestId` is present on an init failure in
      production, whatever the runtime interface emulator shows — and the emulator is known to
      diverge on that path, answering 502 where production answers 200.
      What the probe fails on is an `errorType` under `Runtime.`, a `Status: error` in the log — a
      field Lambda writes only when a phase failed, so it cannot redden a healthy deploy — or no
      `^REPORT RequestId` line at all. A handler that ran and raised is a **pass**: the subject is
      the cold start. The residual, and the command that settles it, is in `docs/testing/owed.md`.
- [ ] The check runs against **the deployed artifact**, not a local image; SPEC-137's failure passed
      review, unit tests and `update-function-code`, and only the deployed function knew.
- [ ] Whatever cannot be invoked safely from a live environment — anything with a side effect on user
      data — is listed as owed in `docs/testing/owed.md` with the reason, rather than counted as
      covered.

### FR-007: Rollback

#### Acceptance Criteria:

- [ ] The rollback is stated: point the functions at the previous sha's image, which is still in the
      repository under the lifecycle bound SPEC-212 computed.
- [ ] The rollback is a workflow input or a documented one-line command, not a code change.
- [ ] It is **exercised once** during this spec, and what it was exercised against is recorded.

---

## Data Model

```hcl
# infra/modules/docker-lambda/variables.tf  (shape, not the full declaration)
variable "function_name"  { type = string }
variable "image_repository_url" { type = string }
variable "image_tag"      { type = string }
variable "command"        { type = list(string) }   # ["module.handler"]
variable "role_arn"       { type = string }
variable "environment"    { type = map(string), default = {} }
variable "timeout_seconds"{ type = number }
variable "memory_mb"      { type = number }
variable "vpc_config"     { type = object({ subnet_ids = list(string), security_group_ids = list(string) }), default = null }

# infra/modules/docker-lambda/outputs.tf
output "function_name" { value = aws_lambda_function.this.function_name }
output "function_arn"  { value = aws_lambda_function.this.arn }
```

## File & Folder Structure

```
infra/modules/docker-lambda/
├── main.tf
├── variables.tf
├── outputs.tf
└── README.md

infra/modules/*/                 # every module's lambda*.tf rewritten as module calls
lambdas/
├── test_docker_lambda_module.py # every function is Image-packaged; no interpolated ARNs
└── fixtures/pre_cutover_plan.json  # the captured parity fixture for FR-002

.github/workflows/deploy-lambdas.yml   # points functions at the image, counts, waits
lambdas/info/deployment.md             # rewritten split + the new ordering constraint
```

## Implementation Phases

### Phase 1: The module

- `infra/modules/docker-lambda`, its README, its outputs and its tests.
- The `lambda_image_tag` variable with its no-default validation.

### Phase 2: The parity fixture and the cutover

- Capture the pre-cutover plan values for all 82 functions as the FR-002 fixture.
- Rewrite each module's function declarations as module calls, plane by plane, standalone functions
  last.
- Rewire every name/ARN consumer onto the outputs; the no-interpolated-ARN test.

### Phase 3: The pipeline

- `deploy-lambdas.yml`: point, count, wait, fail loudly.
- Remove the zip build and every layer attach call.
- Update `lambdas/info/deployment.md`.

### Phase 4: Proving it on the deployed environment

- The per-plane and standalone cold-start invocations.
- The rollback, exercised and recorded.
- The `owed.md` rows for anything that could not be invoked.
