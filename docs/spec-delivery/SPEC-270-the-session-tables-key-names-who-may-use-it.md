# Completed Spec — SPEC-270: The Session Table's Key Names Who May Use It

Two merges on 2026-11-17: #1038 (`81fb468`) narrowed the deployed key and moved dev servers onto a
store of their own, and applied in Deploy Infrastructure run 44145223255 (3 added, 2 changed, 0
destroyed), and `main` was green on that merge; the completion PR removed the task role's KMS
statements.

## What was completed?

- **The deployed key names its principals** (`infra/modules/session-store/policies/key-named.json.tftpl`):
  the deploy role administers it and uses it through DynamoDB, the web task role uses it through
  DynamoDB for the session table's name alone (matched by `aws:PrincipalArn` on a `"*"` principal),
  and the account root reads four metadata actions. No `Deny`. Root builds the task role's ARN in
  `local.web_task_role_arn`; the module picks the template on `named_principals`.
- **Local dev servers have their own store**, `module.dev_session_store` (`<prefix>-dev-sessions`,
  `alias/<prefix>-dev-session`), whose key still delegates. The dev SSM parameter's
  `SESSION_TABLE_NAME` points at it; developers re-run `npm run dev:session-env` once.
- **The task role carries no KMS statement**; its session policy is the one DynamoDB item statement.
- **Tests:** `lambdas/test_session_infrastructure.py` holds the rendered key policy whole (statement
  list, principal set, every condition, no duplicate JSON keys), root's two module calls, the
  constructed role ARN against the `spa` module's role, the dev parameter's override, that no
  `spa` policy names a KMS action, and that the task role holds one inline policy and nothing attached. `lambdas/test_only_the_deploy_role_can_become_another_role.py`
  refuses any policy outside the deploy role's templates that could create, re-trust or pass a
  role, with a fixture corpus of plants and silences.
- **Decision:** `docs/decisions/identity-and-access/the-session-key-names-who-may-use-it-and-the-dev-store-delegates.md`.

### Mutation runs (FR-001)

Each planted in `key-named.json.tftpl`, run, and reverted; each reddened:

| Plant | Failure |
|---|---|
| a `kms:*` statement for the account root | `X allows every KMS action` |
| the API's role added to the task statement's `aws:PrincipalArn` | `principals that can use the key: {…api-role…}` |
| the table-name encryption context dropped | the task statement's `Condition` inequality |
| `kms:Decrypt` added to the root's statement | `principals that can use the key: {…:root…}` |
| `kms:CreateGrant` added to the administration statement | `differs from the listed actions by ['kms:CreateGrant']` |
| a `Deny` statement | `the key's policy carries a Deny` |

The two diff reviews added four plants that first passed (a sixth statement giving another principal
`PutKeyPolicy`, a service principal, an unconditioned deploy-role `Decrypt`, a duplicate Sid); all
four now fail on the statement list. A planted `kms:Decrypt` in the task role's policy reddens the
FR-003 test.

### Deliberate deviations

- **FR-003 landed before FR-005's sign-in half ran.** The spec orders the removal after FR-005's
  checks. The sign-in, idle and sign-out checks were owed then (the web tier was off, and Andrew
  chose not to switch it on for them), and ran on 2026-11-18. The removed statements had granted
  nothing since #1038 applied, because the key's policy no longer delegates, so removing them changed no effective access, and restoring them
  could not have repaired a faulty key policy.
- **The module gained `aws_region` and lost `project_name` and `environment`.** A module behind
  `depends_on` reads no data source, and `names.tf` and the `Name` tag were the two variables' only
  readers. The spec's Data Model was updated.
- **The spec's premise for setting aside a table resource policy was narrowed.** The security review
  found that the key closes item reads, but whether DynamoDB's control plane (`UpdateTable` to an
  AWS-owned key, or a restore with an encryption override) can move the tokens without the caller
  holding the key is undocumented and unmeasured. The spec, the module README and the decision say
  so; a separate session was proposed to measure it on a throwaway table.

## What changed from earlier specs?

- **SPEC-257:** its criterion that the key's only principal is the account root is reversed, marked in
  place. The task role's two KMS identity statements are gone.
- **SPEC-262:** a local dev server's sessions no longer share the deployed table (root `README.md`).
- **`docs/transition_plan.md` §4.7:** the sentence contrasting the sealing key with the session key,
  and the claim that the task role's KMS statement holds the server's half of the seal, are marked
  superseded in place.

## Verification

Local gates green by exit code on both PRs, Checkov's enforced list at zero with `CKV_AWS_7` and
`CKV_AWS_119` passing on both keys and tables. FR-005: an administrator's projected `Scan` of
`dat-prod-sessions` printed `1` before the apply (17:26Z) and failed with KMS `AccessDeniedException`
after it (18:20Z); the live policy carries exactly the five statements. No infrastructure plan ran
between the apply and the completion PR, so that PR's own plan is FR-005's first plan after the apply,
and its result is recorded in the PR's body. Two rows were owed in `docs/testing/owed.md`: the deployed
sign-in, six-minute idle request and sign-out, and the dev server's sign-in into its own table. Both
ran on 2026-11-18 on `b8840ea7` and passed (`docs/testing/sessions.md`).
