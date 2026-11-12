---
type: Spec
id: SPEC-252
title: "The Control Planes Are One Module, Composed From the Root"
description: "Replaces the eight copy-built control-plane modules with one control-plane building block that the root calls eight times, so the next reader maintains one machine instead of eight, with a CI plan proving nothing deployed changed."
spec_status: Draft
depends_on: [SPEC-213]
arc: infra-building-blocks
arc_order: 1
---

**Dependency notes:** SPEC-213 (every verb is a `docker-lambda` call, and the 172 `moved` blocks it
left behind — 156 of them in the plane modules — are applied history this spec deletes). The arc's reasoning, its
measurements and why this spec leads are in `ARCS.md` → *Infra building-blocks arc*.

## Overview

Data Quarry's infrastructure has eight control planes — shared spaces, table builder, table share,
data quality, file send, archive, file ops and results conversion — and each is its own Terraform
module holding its own copy of the same machine: a FIFO request queue with its DLQ, an EventBridge
Pipe and its role, a Standard state machine with its log group and role, an execution role, and
the verb functions. `infra/info/control-plane-shape.md` already says they are "the same machine
with different verbs"; the code says it eight times. A fix to the machine is eight edits, a new
plane starts as a copy, and the traps the shape page lists (the explicit function map, the ceiling
that needs its `TIMED_OUT` rule) are rules a copier must remember rather than things the code
enforces. This spec follows HashiCorp's module guidance — one module per architectural concept,
composed flat from the root, dependencies passed in rather than created — so the machine is
written once and each plane is a call to it carrying only what is distinct about that plane. It
changes nothing that is deployed, and the proof is the pull request's plan.

## Scope

### In Scope

- A building-block module, `infra/modules/control-plane/`, owning the machine every plane shares.
- The eight planes as root calls to it, at their **current module addresses**, with each plane's
  distinct configuration in a root file `infra/plane-<slug>.tf` and its templates and README in
  `infra/planes/<slug>/`.
- Homes for what is not the machine: `infra/modules/shared-space-storage/` (Bucket 2, its Lake
  Formation registration and the portal role's grant on it), `infra/modules/archive-vault/`
  (Bucket 5 and its policy), and `infra/modules/scheduled-function/` (a role, one function and its
  EventBridge schedule), whose first and only caller here is shared spaces' transfer reader.
- Shared spaces' state machine gets its own role, the one deliberate change to deployed IAM (FR-003).
- `moved` blocks in `infra/moved.tf` for every object whose address changes, and deletion of the
  plane modules' own `moved.tf` files, which record moves already applied.
- `lambdas/fleet.py` and every test, script and doc that reads a plane module's path, re-pointed.
- The IaC decision rewritten in place; `control-plane-shape.md` becomes the module's README.

### Out of Scope

- **The deploy role's per-plane grants** in `modules/base/` (1,170 lines across eight near-identical
  templates) — SPEC-253, because the deploy role is its own privilege boundary and changes on its
  own gate.
- **The standalone functions** (`notifications`, `feedback`, `user-directory`,
  `control-plane-dlq-drain`, `observability`'s sweep) — SPEC-254, which moves three of them onto
  the `scheduled-function` module this spec introduces.
- **A shared private-bucket module.** Rejected, not deferred: the seven buckets share four short
  baseline resources and differ in everything else (versioning, CORS, policy, lifecycle), and a
  module named for the one resource type it wraps is the thin wrapper HashiCorp's guidance tells
  you not to write. Bucket 2 and Bucket 5 move only because their plane modules are deleted.
- **Retiring `lambda-artifacts`.** A deletion, not a restructure; it is a session of its own.
- **Any change to a deployed name, an IAM document, a rendered state-machine definition, a queue
  setting or a function setting**, beyond FR-003's enumerated role split. No root output, no
  `.github/config-outputs.json` key and no root module address is renamed.
- **An apply** in this or any environment. Deploys are manual-only; the plan is the proof.

---

## Functional Requirements

### FR-001: One module owns the control-plane machine

#### Description:

`infra/modules/control-plane/` creates, for one plane: the FIFO request queue and its DLQ, the
Pipe and its role, the state machine with its log group and role, the execution role with the
policy the caller renders, and one `docker-lambda` call per verb. It derives every name from the
plane's slug by the rule the planes use today, receives every cross-plane ARN as an input, and
reads no data source. Two traps the shape page carries as prose become structure: every verb's
ARN reaches the definition template by verb key, so there is no hand-kept function map to forget
an entry in, and a plane that declares a ceiling gets its `TIMED_OUT` notifier because it declared
the ceiling.

#### Acceptance Criteria:

- [ ] **Every argument that differs between today's callers is an input, and nothing else is.**
      The build plan carries an attribute diff: for every resource and module call the eight plane
      modules declare, each argument's value per plane, so an argument that varies is found by
      enumeration rather than by memory. Each varying argument is either an input of this module
      or one of FR-003's enumerated changes; an argument that does not vary is a literal in the
      module. The inputs that diff found while this spec was written are in *Interface Contract*;
      the plan reviewer holds the build's diff against that list.
- [ ] Every input has a description, and every name the module creates equals `"${project}-${environment}-${name}-<role>"` with
      the suffixes the planes use today (`-requests.fifo`, `-requests-dlq.fifo`, `-pipe`,
      `-pipe-role`, `-orchestrator`, `-sfn-role`, `-execution-role`, `-<verb>`), except where
      `execution_role_name` is given.
- [ ] The definition template is rendered with `function_arns`, a map from verb key to that
      function's ARN covering **every** key of `functions`, merged with `definition_vars`; a
      template naming a verb that does not exist fails at `tofu validate` or plan, not at apply.
- [ ] The `TIMED_OUT` rule, its target and its permission exist **if and only if** `ceiling` is
      non-null; they target `ceiling.notifier_verb`, the rule carries `ceiling.rule_description`,
      and `ceiling.seconds` reaches the template as `state_machine_timeout_seconds`. A ceiling whose
      notifier verb is not a key of `functions` is refused at plan by a `precondition` naming the
      verb, and a test drives that refusal through `tofu` (a `tofu test` with a mock AWS provider,
      which OpenTofu 1.8 supports) and asserts the error text.
- [ ] The Step Functions role's policy grants the distributed-map statements (start and describe
      child executions, read and write the manifest prefix in the admin bucket, and `StopExecution`
      where asked) **only** when `distributed_map` is non-null, and renders byte-for-byte the
      document each plane has today — the five shapes measured under *Interface Contract*.
- [ ] The module contains no `data` block, no `provider` block and no `time_sleep`. Its `functions`
      call keeps `depends_on = [aws_iam_role_policy.execution]`, the ordering every plane has today,
      which defers nothing because `docker-lambda` reads no data source;
      `lambdas/test_depends_on_defers_no_data_source.py` covers the new module.
- [ ] `tofu validate` passes for the root and for the module on its own (the CI step *Validate every
      module the root does not reach* stops visiting it once the root calls it).

### FR-002: Seven planes are calls to the module, and their plan moves nothing

#### Description:

Table builder, table share, data quality, file send, archive, file ops and results conversion are
each a root `module` block whose `source` is `./modules/control-plane`, under the same address it
has today (`module.table_builder`, …). What is distinct about each plane — its verbs with their
handlers, timeouts, memory and per-verb environment, its queue's deduplication and receive count,
its ceiling and caps, its definition and execution-policy templates — lives in `infra/plane-<slug>.tf`
and `infra/planes/<slug>/`. Their old module directories are deleted.

#### Acceptance Criteria:

- [ ] `infra/modules/` no longer contains `table-builder`, `table-share`, `data-quality`,
      `file-send`, `archive`, `file-ops` or `results-conversion`.
- [ ] In the PR's CI plan, every resource under these seven module addresses is either unchanged
      or reported as **moved**, with no create, update, replace or destroy; the only moves are the
      renames `infra/moved.tf` lists (the state machine to its generic name, the `TIMED_OUT` trio
      to its indexed address, Bucket 5's resources into `module.archive_vault`). Every function
      keeps its address, `module.<plane>.module.functions["<verb>"]`.
- [ ] Every root output that reads a plane, and every other module's input that does (the API's
      enqueue list, the DLQ drain's list), resolves to the same value as on `main`: the plan shows
      no change to any of those outputs and no update to `module.api` or
      `module.control_plane_dlq_drain`. Plan changes under the web tier's addresses (`module.network`,
      `module.spa`, `module.static_portal`, the portal certificate) and their outputs belong to the
      web-tier switch, which no file this spec touches reads, and are outside this criterion.
- [ ] A plane's root file holds no resource; it holds that plane's `locals`, its call to
      `control-plane`, and the calls to any module only that plane uses (`archive_vault` in
      `plane-archive.tf`; `shared_space_storage` and `shared_space_transfer_reader` in
      `plane-shared-spaces.tf`). Every local it declares carries the plane's prefix (`table_share_…`), because the root
      is one namespace.

### FR-003: Shared spaces composes too, and its non-machine parts get homes

#### Description:

Shared spaces is the oldest plane and the one that differs: one `orchestrator` role serves both
the state machine and the verbs, its queue's receive count is a literal 3, and it owns Bucket 2,
the bucket's Lake Formation registration, the portal role's grant on it and the hourly transfer
reader that admits operator requests to its queue. It becomes `module.shared_spaces`, a call to
the control-plane module. Its `orchestrator` role stays, under its own name, as the execution
role; its state machine gets the Step Functions role every other plane has. Bucket 2 and its
grants move to `module.shared_space_storage`; the transfer reader, its role and its schedule to
`module.shared_space_transfer_reader`, a call to `scheduled-function`; the deploy-policy wait to
`module.shared_space_storage`.

#### Acceptance Criteria:

- [ ] `infra/modules/shared-spaces/` is deleted, and the plan's changes for everything it held are
      **exactly**: create `module.shared_spaces.aws_iam_role.sfn` and its policy; update in place
      the state machine's `role_arn`; update in place the `orchestrator` role's trust (Lambda only)
      and its policy (without `InvokeVerbLambdas` and `StepFunctionLogDelivery`, and with `WriteLogs`
      no longer naming the state machine's log group). Two to add, three to change, **zero to
      destroy**; every other object is unchanged or moved. The execution policy keeps its inline
      name `orchestrator` through `execution_policy_name`.
- [ ] The PR names, for each statement removed from the `orchestrator` policy, the search showing
      no shared-spaces verb makes that call.
- [ ] The `orchestrator` role keeps its name and ARN, so the Lake Formation admin list, the
      user-space bucket policy's allowlist and every other reference to it plan no change.
- [ ] `infra/modules/scheduled-function/` has the inputs in *Interface Contract* — chosen by the
      same attribute diff over its four eventual callers (the transfer reader here, and SPEC-254's
      user-directory build, DLQ drain and logs sweep), so SPEC-254 needs no change to it — creates
      the role, its inline policies, the function, the rule, the target and a permission bound to
      `function_arn`, and the transfer reader's objects move into it with no change.
- [ ] `module.shared_space_storage` receives, with no change: Bucket 2 and its six bucket
      resources, `aws_iam_role.lf_registration` and its policy, `aws_lakeformation_resource.shared_space`,
      `aws_lakeformation_permissions.portal_shared_location` and `.control_plane_shared_location`,
      `aws_iam_role_policy.portal_shared_space`, and `time_sleep.wait_for_deploy_policy`. Bucket 5's
      objects move into `module.archive_vault` with no change. Each module receives the role ARNs
      its policies name as constructed strings from the root.
- [ ] The wait still precedes the plane in a fresh apply: `module.shared_spaces` carries
      `depends_on = [module.shared_space_storage]`. `module.shared_spaces` and
      `module.shared_space_transfer_reader` carry no `depends_on` on each other — the plane's verbs
      read the reader role's unique id and the reader reads the plane's queue URL, which is a
      resource-level graph with no cycle and a module-level one with a cycle.

### FR-004: The fleet is still derived from the Terraform, and no test is lost

#### Description:

`lambdas/fleet.py` derives the Lambda fleet from the Terraform sources, and CI builds and points
functions from that answer; roughly ninety test files read a plane module's files to hold a cap,
a policy or a definition against the code. All of them read the new layout, and the move is
proved not to have dropped a function or a test.

#### Acceptance Criteria:

- [ ] `python3 lambdas/fleet.py` prints the same list on the branch as on `main`, compared as
      sorted JSON, and still raises when the sweep resolves fewer than its floor.
- [ ] `fleet.py` resolves a function declared through a root call to `control-plane` or
      `scheduled-function` (the call's literal `name`, the keys of its `functions` argument, and the
      module's own naming local) without a second copy of the naming rule, and refuses a `name` that
      is not a literal; tests plant both refusals and assert the `FleetError` text.
- [ ] **No glob goes quiet.** Every test or script that globs Terraform (`infra/modules/*/…` and
      the like — `test_request_size_chain.py`, `test_queue_writers.py`, `test_feedback_module.py`,
      `test_transfer_cpcommon.py`, `test_fleet_environment.py`, `test_lambda_plan_guard.py`,
      `policyTemplates.guard.test.ts` and any the build's sweep finds) matches, on the branch, the
      same templates and declarations it matched on `main` at their new paths — compared as file
      lists printed from each glob on both refs, not by the test passing.
- [ ] **Every workflow that fires on a fleet change still fires.** Each `paths:` filter naming
      `infra/modules/**` because a verb is declared there (`lambda-image.yml`, `deploy-lambdas.yml`
      and any other the sweep finds) also names `infra/plane-*.tf` and `infra/planes/**`, and the
      comments saying the root cannot change the fleet are corrected.
- [ ] Test IDs collected from the runners (pytest's JSON report and Vitest's JSON reporter) on
      `main` and on the branch differ only by file path where a test file moved; no ID is lost.
- [ ] `git grep` for `infra/modules/` followed by any deleted directory name returns nothing
      outside a dated History entry or a Completed spec's body.

### FR-005: The register and the docs describe the structure that exists

#### Description:

The IaC decision says `infra/modules/` are bounded-context modules, which this spec reverses for
the planes: it is rewritten in place with a dated History entry. The shape page becomes the
module's own README, and every page that routes to a plane module routes to its new home.

#### Acceptance Criteria:

- [ ] `docs/decisions/infrastructure/iac.md` states the rule — a module is one architectural
      concept; a concept built more than once is a building block the root calls once per
      instance; the root passes every dependency in; plane configuration lives with its call — with
      a History entry for 2026-11-12, and `sh scripts/gen-index.sh` regenerates its fence.
- [ ] `infra/info/control-plane-shape.md` is gone, its content lives in
      `infra/modules/control-plane/README.md`, and each plane's README lives in
      `infra/planes/<slug>/README.md` carrying only what is distinct about it.
- [ ] `infra/info/INDEX.md` lists the building blocks and the planes' new homes, and
      `python3 scripts/validate_docs.py` passes.

---

## Interface Contract

The module's inputs, as HCL. Every input is required unless a default is shown.

```hcl
# infra/modules/control-plane/variables.tf
variable "name" { type = string }                 # the plane's slug: "table-share"
variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "account_id" { type = string }

variable "functions" {
  type = map(object({
    handler              = string
    timeout              = number
    memory               = number
    ephemeral_storage_mb = optional(number, 512)
    environment          = optional(map(string), {})
  }))
}
variable "environment_variables" { type = map(string) }  # common to every verb
variable "lambda_image_repository_url" { type = string }
variable "lambda_image_tag" { type = string }

variable "content_based_deduplication" { type = bool }      # the request queue
variable "dlq_content_based_deduplication" { type = bool }  # data quality differs from its queue
variable "dlq_max_receive_count" { type = number }

variable "definition_template" { type = string }   # path to the plane's ASL .tftpl
variable "definition_vars" {
  type    = map(any)
  default = {}
}
variable "ceiling" {
  type = object({
    seconds          = number                     # the ASL's top-level TimeoutSeconds
    notifier_verb    = string                     # "notify-failure" on all six planes today
    rule_description = string                     # worded per plane today; a rewording is an update
  })
  default = null                                  # null: no ceiling, no TIMED_OUT notifier
}

variable "execution_policy" { type = string }      # rendered by the caller from its template
variable "execution_policy_name" {
  type    = string
  default = "permissions"                         # shared spaces: "orchestrator"
}
variable "execution_role_name" {
  type    = string
  default = null                                  # null: "<prefix>-<name>-execution-role"
}

variable "distributed_map" {
  type = object({
    manifest_prefix = string                      # under the admin bucket
    can_stop        = bool
  })
  default = null
}
variable "admin_bucket_arn" { type = string }

# outputs.tf: queue_url, queue_arn, dlq_arn, state_machine_arn, execution_role_arn, function_names
```

`scheduled-function`, sized for all four callers (the attribute diff found the statement ids,
policy names, rule names and the sweep's role name each differ, and that observability's role
carries two inline policies, one naming the function's own log group):

```hcl
# infra/modules/scheduled-function/variables.tf
variable "function_name" { type = string }        # full name, as declared today
variable "role_name" { type = string }            # the sweep's has no "-role" suffix
variable "role_policies" { type = map(string) }   # inline policy name => rendered document
variable "handler" { type = string }
variable "timeout_seconds" { type = number }
variable "memory_mb" { type = number }
variable "environment_variables" { type = map(string) }
variable "lambda_image_repository_url" { type = string }
variable "lambda_image_tag" { type = string }
variable "rule_name" { type = string }
variable "rule_description" { type = string }
variable "schedule_expression" { type = string }
variable "permission_statement_id" { type = string }
# outputs.tf: function_name, function_arn, role_arn, role_unique_id
```

A policy naming the function's own log group takes that ARN as a constructed string, so no policy
waits on the function it permits.

The Step Functions policy as it stands: seven files, five distinct by
`md5 -q infra/modules/*/policies/sfn-permissions.json.tftpl | sort | uniq -c` (shared spaces has
none, its one role carrying those statements). Read side by side they are three shapes: no
distributed map (table-builder, data-quality, results-conversion); a distributed map whose
manifest prefix is the plane's slug (table-share, file-send) or a caller-given prefix (file-ops);
and that map with `StopExecution` added (archive, file-ops). `manifest_prefix` and `can_stop`
cover all three; shared spaces takes the first.

## File & Folder Structure

```
infra/
├── plane-shared-spaces.tf … plane-results-conversion.tf   # one per plane: locals + one module call
├── moved.tf                                                # every address this spec changes
├── planes/<slug>/
│   ├── state-machine.asl.json.tftpl
│   ├── execution.json.tftpl
│   └── README.md
└── modules/
    ├── control-plane/        (main.tf, iam.tf, variables.tf, outputs.tf, policies/, README.md)
    ├── scheduled-function/
    ├── shared-space-storage/
    └── archive-vault/
```

## Implementation Phases

### Phase 1: The module and the first plane

- Write `modules/control-plane` and move table-builder onto it (no distributed map, a ceiling).
- Teach `fleet.py` the root-call resolution; capture `main`'s fleet list and test IDs first.
- Write the plane's `moved` blocks and validate locally (`tofu validate`; local `plan` is not
  trusted here, the CI plan is).

### Phase 2: The six other uniform planes

- Table share, data quality, file send, archive (with `archive-vault`), file ops, results conversion.

### Phase 3: Shared spaces

- `scheduled-function`, `shared-space-storage`, the role split, and its moves.

### Phase 4: Re-point and document

- Every test, script and doc reading a deleted path; the IaC decision; the module and plane READMEs;
  `INDEX.md`; delete the old directories and their `moved.tf` files.
