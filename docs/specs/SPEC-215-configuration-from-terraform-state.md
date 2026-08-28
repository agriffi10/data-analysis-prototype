# Spec: Configuration from Terraform State — Retiring the Repository Variables

**ID:** SPEC-215
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-005 (the deploy workflows), SPEC-192 (the runtime configuration document and its six wiring sites), SPEC-194 (the container entrypoint that renders the document), SPEC-162 (the flag-document publish, which resolves its bucket from a repository variable)

**Interacts with:** SPEC-214 becomes a fourth consumer of `tofu output`; FR-001's derived version
set is written for that, and both specs state the obligation for either landing order.

**Relates to:** SPEC-202 retires CloudFront, which deletes the `/config.json` render step in
`deploy-app.yml` — one of the two consumers this spec fixes. The other, the task definition, is
already Terraform. This spec is written to be correct whether it lands before or after 202, and FR-007
says how.

## Overview

Thirty distinct repository variables reach the deploy workflows, plus one resolved dynamically, and
most of them are not inputs to anything. They are Terraform **outputs** — bucket names, queue URLs, Cognito
identifiers, the Athena workgroup, the API base URL — that a person read out of `tofu output` once
and typed into a settings page. Terraform computes them, and then a human is the transport.

Every failure mode that arrangement has, this repo has already met. An unset repository variable
interpolates to the **empty string**, which satisfies a required Terraform variable *and* overrides
its default; `deploy-config.yml` carries a hand-written guard for exactly that, because the symptom
was an `s3:///_config/...` copy failing far from its cause. And a value that changes in
infrastructure stays wrong in the browser until somebody remembers to re-copy it — the runtime
config document exists precisely so that a repoint is not a rebuild, and a repoint currently means
editing a settings page.

This spec makes the deploy workflows read the outputs. A value Terraform computes is consumed from
Terraform, and the repository variable set shrinks to what it should always have been: the handful
of genuine **inputs** — the region, the domain, the environment name, the policy numbers — that no
resource can tell you.

## Scope

### In Scope

- `deploy-app.yml` and `deploy-config.yml` reading `tofu output -json` from the remote state.
- One declared map from Terraform output name to configuration key, and a test binding it to the
  runtime config's classified key set.
- Deleting every repository variable that mirrors an output, and the workflow references to them.
- Failing the deploy loudly on an absent or empty required output.
- Rewriting `apps/portal/info/runtime-configuration.md`'s "six places" for the sites that changed.

### Out of Scope

- **SSM Parameter Store, or any second copy of the values.** Terraform's state already holds them;
  writing them somewhere else to read them back adds a resource type, its deploy-role IAM, and a
  second thing that can be stale.
- **Changing what the runtime config document contains**, its version, its refusal behaviour or its
  `no-store` header. The values are identical; only their route into the workflow changes.
- **Changing the ECS task definition's configuration.** It is already Terraform-native, already
  reads the same values as resource attributes, and is not touched.
- **The genuine inputs.** `AWS_REGION`, the domain and subdomain variables, `github_repo`, the
  environment name, the upload cap, the desired count, `TF_VAR_spa_image_tag` and the verification
  principal ARNs stay repository variables — an input cannot be read from the thing it configures.
  **Named singly, not as "the image tags":** SPEC-213 introduces `TF_VAR_lambda_image_tag` supplied
  from `${{ github.sha }}` precisely so it is *not* a repository variable, and a plural bullet here
  would instruct a later implementer to reintroduce the empty-`TF_VAR_` hazard that spec guards.
- **Secrets.** `AWS_DEPLOY_ROLE_ARN` is a secret and stays one. No output is read in its place.
- **Retiring CloudFront.** SPEC-202 does that.

---

## Functional Requirements

### FR-001: The workflows read the outputs

#### Description:

`deploy-app.yml` and `deploy-config.yml` initialise the Terraform backend against the same state
`deploy-infra.yml` uses, and read every derived value from `tofu output -json`.

#### Acceptance Criteria:

- [ ] Each workflow runs `tofu init -backend-config=…` with the same backend configuration and the
      same pinned OpenTofu version as `deploy-infra.yml`. A test **derives** the set of workflows and
      asserts they agree on one version — it does not count to three, because SPEC-214 adds a fourth
      consumer and a hard-coded count would keep passing while that one drifted.
- [ ] The predicate is **"declares an OpenTofu version"**, not "runs `tofu init`". Those differ, and
      the difference is load-bearing: SPEC-214 has `deploy-lambdas.yml` read an output through this
      spec's resolver rather than writing its own `tofu init`, so an init-based predicate would
      exclude the very workflow the derivation was widened for. `ci.yml` also pins a version and is
      included for the same reason.
- [ ] The assertion compares the version **constraints as declared**. Today all three sites read
      `~1.8`, which is a constraint and not a version, so "they agree" means the declarations are one
      string — the property that actually prevents drift. A criterion promising they resolve to one
      *version* would be claiming something the workflow files cannot state.
- [ ] The outputs are read **once** per job into a single JSON document, not by repeated
      `tofu output <name>` calls.
- [ ] The deploy role is the identity used, unchanged; no new AWS grant is required, and a test
      asserts the state-bucket read is already covered by the role's existing policy rather than
      widening it.
- [ ] `deploy-config.yml`'s destination bucket comes from the output rather than
      `vars[matrix.bucket_var]`, and its hand-written empty-variable guard is replaced by FR-003's,
      not kept alongside it.

### FR-002: One declared mapping, bound to the config contract

#### Description:

A map from Terraform output name to configuration key. It is the only place that mapping exists, and
it is checked against the keys the browser actually classifies — otherwise it is simply a new
hand-maintained copy in place of the old one.

#### Acceptance Criteria:

- [ ] The mapping is a single committed file, read by both workflows.
- [ ] A test asserts the mapping's config-key set equals `REQUIRED_CONFIG ∪ OPTIONAL_CONFIG` **minus
      the genuine inputs** (`environment`, `maxUploadBytes`) — eighteen keys, exactly the Data Model
      below. A key in one and not the other fails. It is deliberately **not** `REQUIRED_CONFIG`
      alone: that set is eight keys, and trimming the mapping to satisfy such a criterion would stop
      rendering every queue URL into `/config.json`, silently disabling every enqueue path through
      `enqueueFifo`'s `notConfiguredMessage` — a portal that boots, reports ready, and cannot send
      anything.
- [ ] A test asserts every Terraform output name in the mapping exists in `infra/outputs.tf`. A
      renamed output fails at test time, not at deploy time.
- [ ] A test asserts the mapping references no output declared `sensitive`.
- [ ] The container entrypoint's `KEYS`/`REQUIRED` lists are asserted against the same set, so the
      leg that decides whether the container starts is bound to the mapping too.

### FR-003: An absent or empty value fails the deploy

#### Description:

The failure this replaces was silent. The replacement must not be.

#### Acceptance Criteria:

- [ ] A required config key whose Terraform output is absent fails the job, naming the key and the
      output.
- [ ] A required config key whose output is present but **empty** fails the job the same way. The
      emptiness is the thing checked, because an empty value satisfies every presence test there is.
- [ ] The failure is a job failure with the name in the message — not a warning, not a default, and
      not a value the render step passes through to a document that then boots a portal pointed at
      nothing.
- [ ] A test drives both cases against the resolution step and asserts the failure and its wording.
- [ ] The check runs **before** any AWS write in the job.

### FR-004: The repository variables go

#### Acceptance Criteria:

- [ ] Every `vars.*` reference that mirrors a Terraform output is removed from every workflow; a test
      greps the workflows and fails on a hit against a list of the retired names.
- [ ] The retired variables are deleted from the repository settings, and the PR records which ones,
      so the settings page and the repo agree.
- [ ] The surviving variables are listed in one place with, for each, the reason it is an input
      rather than an output. A variable with no such reason is a variable that should have been
      retired.
- [ ] `apps/portal/.env.example` is unchanged — it documents the dev fallback, which is a different
      mechanism and is not affected.

### FR-005: The dev fallback and the bundle guard are untouched

#### Acceptance Criteria:

- [ ] `npm run check:bundle` still passes: the production bundle carries no `VITE_` names.
- [ ] A local `npm run dev` with a `.env` still boots against `import.meta.env`, unchanged.
- [ ] The production build's `VITE_*` env block is removed from `deploy-app.yml` **only if** SPEC-202
      has already removed the CloudFront path that needs it; otherwise it is populated from the same
      resolved outputs, so both consumers read one source. FR-007 states which.

### FR-006: The documentation says where a key is wired now

#### Acceptance Criteria:

- [ ] `apps/portal/info/runtime-configuration.md`'s "A key is wired in six places" is rewritten: the
      GitHub repository variable is no longer one of them, and the mapping file is.
- [ ] The test that compares the wiring sites is updated to compare the new set, and it still fails
      when a key is added to some of them and not all.
- [ ] `docs/process.md` §6's entry on the six places is corrected in the same pass, since it states
      the same fact and two hand-synced copies of one procedure is how this drifts.

### FR-007: The ordering against SPEC-202 is decided, not left open

#### Description:

Both orders are workable and they produce different work, so the spec picks one.

#### Acceptance Criteria:

- [ ] **This spec ships independently of SPEC-202 and does not wait for it.** The repository
      variables are a live hazard now, and the CloudFront render step is one of two consumers — the
      task definition is the other, and it is unaffected by 202's timing.
- [ ] While CloudFront is still the front door, both consumers — the `VITE_*` build env and the
      `/config.json` render step — read the same resolved outputs, so they cannot disagree.
- [ ] When SPEC-202 removes the CloudFront path it deletes both of those consumers, and **the
      `appUrl` row repoints from `cloudfront_domain` to `spa_origin`** in the same change. This is
      not optional and is not "no further change": `appUrl` is in `REQUIRED_CONFIG` and the container
      path needs it too, `cloudfront_domain` is deleted with the distribution, and FR-002's
      output-existence criterion goes red the moment it is. `spa_origin` already exists in
      `infra/outputs.tf` and is the value it becomes.
- [ ] This spec's delivery doc carries that instruction explicitly, so SPEC-202 inherits it rather
      than rediscovering it as a red gate.

---

## Data Model

```jsonc
// .github/config-outputs.json — the one declared mapping.
// Left: the Terraform output name. Right: the runtime configuration key.
{
  "api_origin":                     "apiBaseUrl",
  "cloudfront_domain":              "appUrl",
  "aws_region":                     "awsRegion",
  "cognito_user_pool_id":           "cognitoUserPoolId",
  "cognito_user_pool_client_id":    "cognitoUserPoolClientId",
  "cognito_domain":                 "cognitoDomain",
  "cognito_identity_pool_id":       "cognitoIdentityPoolId",
  "s3_user_space_bucket_name":      "userSpaceBucket",
  "shared_space_bucket_name":       "sharedSpaceBucket",
  "athena_workgroup_name":          "athenaWorkgroup",
  "shared_space_request_queue_url": "sharedSpaceQueueUrl",
  "notifications_queue_url":        "notificationsQueueUrl",
  "table_build_queue_url":          "tableBuildQueueUrl",
  "table_share_queue_url":          "tableShareQueueUrl",
  "data_quality_queue_url":         "dataQualityQueueUrl",
  "file_send_queue_url":            "fileSendQueueUrl",
  "archive_queue_url":              "archiveQueueUrl",
  "file_ops_queue_url":             "fileOpsQueueUrl"
}
```

> **The left column is checked against `infra/outputs.tf`, one name at a time.** **Twelve** of these
> eighteen outputs exist today under exactly these names — including `notifications_queue_url` and
> `shared_space_request_queue_url`, which is why the missing set is smaller than a first pass
> assumed. `cloudfront_domain` is among the twelve and is repointed to `spa_origin` by SPEC-202
> (FR-007). **Six** are missing and are added in Phase 1: `table_build_queue_url`,
> `table_share_queue_url`, `data_quality_queue_url`, `file_send_queue_url`, `archive_queue_url`,
> `file_ops_queue_url`. Three
> names that a first draft got wrong are worth recording, because FR-002's existence test would have
> been satisfied by adding duplicates under the wrong names rather than by correcting the mapping:
> it is `shared_space_bucket_name` not `s3_shared_space_bucket_name`,
> `shared_space_request_queue_url` not `shared_space_queue_url`, and `api_origin` not
> `api_base_url`. `environment` and `maxUploadBytes` are **not** here: they are inputs, and they
> stay repository variables.

## File & Folder Structure

```
.github/
├── config-outputs.json                 # the mapping
├── scripts/resolve-config.sh           # tofu output -json → CONFIG_* env, with FR-003's checks
└── workflows/
    ├── deploy-app.yml                  # reads outputs instead of vars
    └── deploy-config.yml               # resolves its bucket from an output

lambdas/test_config_outputs.py          # FR-002's three set assertions
apps/portal/info/runtime-configuration.md   # the wiring sites rewritten
docs/process.md                             # §6's copy of the same fact
```

## Implementation Phases

### Phase 1: The mapping and its tests

- `config-outputs.json`, and the three assertions binding it to `runtimeConfig.types.ts`,
  `infra/outputs.tf` and the container entrypoint's key lists.
- Add the six missing per-plane queue-URL outputs named in the Data Model note. Adding an output whose name merely duplicates
  an existing one under a different spelling fails FR-002's existence test by design — the fix is
  always the mapping, never a second output.

### Phase 2: The resolver

- `resolve-config.sh`: one `tofu output -json`, the absent and empty checks, the named failures.
- Its unit tests, driven against fixture output documents.

### Phase 3: The workflows

- `deploy-app.yml` and `deploy-config.yml` onto the resolver.
- Remove the retired `vars.*` references; the grep test.

### Phase 4: The cleanup

- Delete the retired repository variables; record which.
- Rewrite `runtime-configuration.md` and `process.md` §6; update the wiring-site test.
- One full deploy watched to green, confirming the rendered document is byte-identical to the one
  the repository variables produced.
