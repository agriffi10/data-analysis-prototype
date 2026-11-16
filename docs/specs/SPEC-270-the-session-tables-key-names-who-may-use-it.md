---
type: Spec
id: SPEC-270
title: "The Session Table's Key Names Who May Use It"
description: "Narrows the deployed session table's customer-managed key from a policy that delegates to the account's IAM to one that names the web task role and the deploy role, so an account principal that IAM allows to read the table can no longer read the refresh tokens in it, and moves local dev servers onto a session table and key of their own."
spec_status: Draft
depends_on: [SPEC-257]
---

**Dependency notes:** SPEC-257 built the session store: one DynamoDB table outside the web tier's
switch, under a customer-managed key whose policy delegates to the account's IAM and names no other
principal (its FR acceptance criterion, *"its key policy's only principal is the account root"*). This
spec reverses that criterion. The reason SPEC-257 gave, that naming the task role would make a
resource outside the switch depend on a role inside it, is answered the way the identity-context
sealing key answers it (`docs/transition_plan.md` §4.7): the task role is matched by an
`aws:PrincipalArn` condition on `Principal: "*"`, which KMS does not validate, so the key does not
need the role to exist. The Phase 5 server exchange stores the Identity Center refresh token in the
same item, so this narrowing covers that token too.

## Overview

The portal's server keeps each browser's session in a DynamoDB table, and each item holds the user's
Cognito refresh token, which mints that user's bearer for 30 days. The table is encrypted with a
customer-managed key, but the key's policy hands every decision to the account's IAM, so any principal
that IAM allows to read the table and use KMS (an administrator, a broad operations role) can read
every user's refresh token. `docs/transition_plan.md` §4.7 requires the table to have "tightly scoped
access" before the client's security review. After this spec the key's own policy decides: only the
web tier's task role may use it to read and write sessions, only the deploy role may administer it,
and no identity policy can widen that. Local dev servers, which today share the deployed table under
the developer's own credentials, get a table and key of their own, so the narrowing does not have to
name a developer.

## Scope

### In Scope

- The deployed session key's policy names its principals and no longer delegates to the account.
- A second session store for local dev servers, and the dev environment parameter pointing at it.
- The task role's identity policy stops granting the key, once the key policy grants it.
- Tests over the HCL and the rendered policies, and the live checks after the apply.

### Out of Scope

- **A DynamoDB resource policy on the table.** It would need new deploy-role grants
  (`PutResourcePolicy`, `GetResourcePolicy`, `DeleteResourcePolicy`) in a PR of their own, and it would
  leave the key delegated, which is what a security review reads first. The key policy alone closes
  the exposure, because DynamoDB cannot return an item to a caller that cannot decrypt it.
- **A `Deny` statement in the key policy.** The sealing key carries one; this key does not. DynamoDB
  holds grants on the key, whose grantee is its regional service principal, and uses them for
  background maintenance. The IAM documentation does not say `aws:PrincipalArn` is present on a
  service principal's call, and a negated operator on an absent key evaluates true, so a
  `Deny … unless aws:PrincipalArn` could deny DynamoDB itself, and AWS says that without its grant
  DynamoDB cannot protect and maintain the table. A policy that does not delegate to the account
  already refuses every principal it does not name, so the Deny would add risk and no narrowing.
- **The account root, for anything that uses or changes the key.** Root may read the key's metadata
  (FR-001) and nothing else, so no IAM administrator can rewrite the policy or decrypt through it.
- Re-keying the existing table or replacing the key. The policy changes in place, and existing
  sessions keep working.
- How developers reach the dev store in the client's environment. There the dev store's delegated
  key works for whatever role a developer signs in with; whether the client allows local dev servers
  at all is the client's call.
- Point-in-time recovery, TTL and deletion protection, which are unchanged on both stores.

---

## Functional Requirements

### FR-001: The deployed session key's policy names its principals

#### Description:

The deployed store's key (`module.session_store`) carries a policy rendered from a template, with
these statements and no others:

- **Administration, for the deploy role alone,** named as the statement's `Principal` (the role
  always exists, and a named principal is the form KMS's lock-out safety check reads): `DescribeKey`,
  `GetKeyPolicy`, `PutKeyPolicy`, `GetKeyRotationStatus`, `EnableKeyRotation`, `DisableKeyRotation`,
  `EnableKey`, `DisableKey`, `UpdateKeyDescription`, `ListResourceTags`, `TagResource`,
  `UntagResource`, `ScheduleKeyDeletion`, `CancelKeyDeletion`, `CreateAlias`, `DeleteAlias`,
  `UpdateAlias`. No cryptographic action.
- **Use through DynamoDB, for the deploy role,** named as `Principal`, conditioned on
  `kms:ViaService` = `dynamodb.<region>.amazonaws.com`: `CreateGrant`, `DescribeKey`, `Encrypt`,
  `Decrypt`, `GenerateDataKey*`, `ReEncrypt*`. This is AWS's documented minimum for the principal
  that puts a table under a customer-managed key: the deploy role's `SessionKeyUseByTable` identity
  statement today, under which it created the table, plus `DescribeKey`, which its identity policy
  grants unconditioned. A key policy that names a same-account role directly needs no identity grant
  beside it, so `CancelKeyDeletion` in the administration list works although no identity statement
  grants it. The deploy role has no item-level DynamoDB grant on the table, so it cannot read a token
  through this.
- **Use through DynamoDB, for the web task role,** with `Principal: "*"` conditioned on
  `aws:PrincipalArn` equal to the task role's ARN, `kms:CallerAccount` equal to the account,
  `kms:ViaService` = `dynamodb.<region>.amazonaws.com`, and
  `kms:EncryptionContext:aws:dynamodb:tableName` equal to the session table's name: `Encrypt`,
  `Decrypt`, `GenerateDataKey*`, `ReEncrypt*`. A second statement grants the task role `DescribeKey`
  with the same conditions less the encryption context, which `DescribeKey` does not carry. These are
  exactly the task role's two identity statements today, which a live write and read measured
  (SPEC-257).
- **Metadata reads, for the account root:** `DescribeKey`, `GetKeyPolicy`, `GetKeyRotationStatus`,
  `ListResourceTags`. A security reviewer, AWS Config and a local plan read these, and none of them
  uses or changes the key.

The task role's ARN is a constructed string in root `locals`, built from the same name the `spa`
module gives the role, so `session-store` still reads no `network` or `spa` output and the plan knows
the value. The deploy role's ARN is root's existing `local.deploy_role_arn`.

**What the binding rests on, stated rather than glossed.** The deploy role is the trust root: its
`PutKeyPolicy` lets it grant itself anything, so whoever can run the deploy role controls the key,
as for the sealing key. `aws:PrincipalArn` matches the task role by name, so while the web tier is
switched off and the role does not exist, a principal able to create a role under that name and
attach a table grant to it could read sessions. Among the principals the IaC builds, creating roles
is the deploy role's alone (FR-004 holds it). Outside the IaC, an account administrator can create
roles, but can also rewrite the deploy role's trust policy, so that principal already controls the key.

**Losing the deploy role loses administration of the key, and that is accepted.** KMS stores a named
role as its unique id, so a deploy role deleted and recreated under the same name is a different
principal, and no principal could then rewrite the policy short of AWS Support. The account root is
not given `PutKeyPolicy` as a break-glass, because that would hand the key to every principal an
identity policy allows `kms:PutKeyPolicy` on `*`, a wider set than those who can rewrite the deploy
role's trust. The recovery is a new store: a new table and key under new names, which costs every
user one sign-in, since a session holds nothing that outlives it. The deploy role's name is already
ForceNew-guarded in `infra/modules/base/iam.tf`, and the sealing key accepts the same risk.

#### Acceptance Criteria:

- [ ] A test renders the deployed key's policy from its template with root's values and asserts, each
  as a set-equality: the principals allowed any cryptographic action are exactly the deploy role and
  the task role; the account root is allowed exactly the four metadata actions; the deploy role's
  administration statement holds exactly the actions listed above; no statement allows `kms:*`; no
  statement's effect is `Deny`. (Checkov cannot read a `templatefile()` policy, so this test is the
  only check on the policy's principals.)
- [ ] The test asserts the task role's conditions exactly, including the table-name encryption
  context on the cryptographic statement and its absence on the `DescribeKey` statement.
- [ ] A test asserts root's constructed task-role ARN names the role the `spa` module creates, so a
  rename on either side fails here rather than as a session outage.
- [ ] `session-store` still takes no input from `network` or `spa` (the existing test, unchanged).
- [ ] Each of the first test's assertions is mutation-tested once (add a `kms:*` root statement; add
  the API's role to the task role's statement; drop the table-name condition; add `kms:Decrypt` to the
  root's statement; add `kms:CreateGrant` to the administration statement; add a `Deny` statement),
  and the delivery doc lists the six reddened runs and their failure messages.
- [ ] Checkov `CKV_AWS_7` and `CKV_AWS_119` still pass on both keys and tables; each reads an
  attribute written outside the template.

### FR-002: Local dev servers keep their sessions in a store of their own

#### Description:

Root calls the same `session-store` module a second time, as `module.dev_session_store`, outside the
web tier's switch, with the table `<project>-<env>-dev-sessions` and the alias
`alias/<project>-<env>-dev-session`. Its key's policy is the one every store has today: it delegates
to the account's IAM and names no other principal, because a dev server signs in with the
developer's own credentials, whatever they are. Root builds both names once in `locals`, beside the
deployed store's.

The dev environment parameter (`/<project>-<env>/portal/dev-session-env`) carries the dev table's
name as `SESSION_TABLE_NAME`, and the task definition keeps the deployed table's. A session already
serves only the client that created it, so a dev server never used a deployed session, and nothing is
lost by the move. Developers re-run `npm run dev:session-env` once and sign in again.

Both names fall inside the deploy role's existing grants (`table/<project>-*-sessions` and
`alias/<project>-*-session`), so no IAM change is needed and none is made.

#### Acceptance Criteria:

- [ ] A test asserts, over root's two module calls, that the deployed store's call sets
  `named_principals` from root's deploy-role and task-role ARNs and the dev store's call does not set
  it, and that the module picks `key-named.json.tftpl` exactly when `named_principals` is set. Rendering
  the two templates alone would pass with the calls swapped.
- [ ] The existing dev-parameter test asserts that `SESSION_TABLE_NAME` is the dev table's name in
  the dev parameter and the deployed table's in the task environment, and that every other key still
  matches.
- [ ] The existing test that root's names are the names the deploy grant admits covers both stores'
  table and alias names.
- [ ] The dev store sits outside the switch and reads nothing inside it (the existing test, extended
  to the second call).
- [ ] The two keys carry different descriptions and `Name` tags, each built from its alias.

The existing tests that read the module's `main.tf` and `names.tf` (the key-policy test and the
names-the-deploy-grant-admits test) are rewritten for the templates and root's names, not extended.

### FR-003: The task role's identity policy stops naming the key

#### Description:

Once the narrowed key policy has applied, the task role's two KMS statements
(`UseTheSessionTablesKeyThroughDynamoDB` and `DescribeTheSessionTablesKeyThroughDynamoDB`) are
removed. A key policy that does not delegate ignores identity policies, so they grant nothing, and
two places naming one grant drift. They are removed in a later PR than FR-001, because one apply
would change the key policy and the role policy in parallel, and a role policy that lost its
statement first would leave the server unable to read sessions until the key policy landed.

#### Acceptance Criteria:

- [ ] No identity policy template under `infra/modules/spa/` names `kms:`, asserted.
- [ ] The task role's DynamoDB statement is unchanged, asserted as it is today.

### FR-004: Only the deploy role can become the task role

#### Description:

FR-001 rests on no IaC principal but the deploy role being able to obtain the task role's identity:
by creating a role under its name (`iam:CreateRole`), by rewriting its trust
(`iam:UpdateAssumeRolePolicy`), or by passing it to something that runs as it (`iam:PassRole`). A
test holds it: no policy under `infra/` outside the deploy role's own templates, whether a `.tftpl`
template or an inline `jsonencode` in a `.tf` file, names an action that matches any of the three,
wildcards included (`iam:*`, `iam:Create*`, `iam:Pass*`, `*`). A grep on this spec's base finds none.
If the sealing key's spec has landed a narrower `iam:CreateRole` test first, this spec widens that
one rather than adding a second.

#### Acceptance Criteria:

- [ ] The test fails naming the file when a policy outside the deploy role's templates names
  `iam:CreateRole`, `iam:Pass*` or `iam:*`, mutation-tested once for each of the three, planted once in
  a template and once in an inline `jsonencode`.
- [ ] The test passes on the tree as it is, and finds at least one deploy-role template that does
  grant `iam:CreateRole`, so a matcher that reads nothing fails.

### FR-005: The narrowing is measured on the deployed account

#### Description:

The policy is proved by what it refuses and what it still allows, on the deployed account after the
FR-001 apply. The refusal is measured before the apply as well, so the check is shown to
discriminate.

#### Acceptance Criteria:

- [ ] **Before the apply,** with at least one signed-in session in the table, an AdministratorAccess
  principal's
  `aws dynamodb scan --table-name <project>-<env>-sessions --max-items 1 --projection-expression pk --query 'length(Items)'`
  prints `1`. **After it,** and more than five minutes after that principal last touched the table
  (DynamoDB caches a table key per caller for five minutes of inactivity), the same command fails
  with an error naming KMS. The projection and the query keep every token and key out of the
  terminal.
- [ ] After the apply, with the web tier on: a fresh sign-in succeeds; a request made after at least
  six minutes idle (past DynamoDB's five-minute key cache) is still signed in; sign-out ends the
  session.
- [ ] The first CI plan after the apply shows no change to `module.session_store` (the deploy role
  can still refresh the key).
- [ ] After the dev parameter moves, a local dev server signs in and its session is in the dev table
  and not in the deployed one.
- [ ] A check no signed-in session can run becomes a row in `docs/testing/owed.md`.

---

## Data Model

The module's interface after this spec:

```hcl
# infra/modules/session-store/variables.tf
variable "table_name" { type = string } # root builds it, as today
variable "key_alias"  { type = string } # root builds it; names.tf no longer does

# null: the key delegates to the account's IAM (the dev store).
# Set: the key names these principals and no others (the deployed store).
variable "named_principals" {
  type = object({
    deploy_role_arn = string
    task_role_arn   = string
  })
  default = null
}
```

```text
infra/modules/session-store/policies/
├── key-delegated.json.tftpl   # the account root, kms:*  (the dev store)
└── key-named.json.tftpl       # FR-001's statements      (the deployed store)
```

## Implementation Phases

### Phase 1: The dev store and the named policy (PR 1)

- Root `locals`: the dev table and alias names, the deployed alias, the task role's constructed ARN.
- The module: `key_alias` and `named_principals` variables, the two policy templates, `names.tf`
  retired.
- `module.dev_session_store`, and the dev parameter's `SESSION_TABLE_NAME` override.
- The tests of FR-001, FR-002 and FR-004, with FR-001's mutation runs.
- Docs: the module README's *The key's policy* section rewritten, `main.tf`'s header comment, the
  `account_id` variable's description, `docs/security-baseline.md`'s `CKV_AWS_28` note (two tables
  now fail it by decision, not one), the
  `transition_plan.md` §4.7 sentence that contrasts the sealing key with this one marked superseded in
  place, and SPEC-257's acceptance criterion marked superseded in place.
- Before the push: FR-005's *before* measurement, recorded in the PR body.

### Phase 2: The task role's statements go (PR 2)

- After PR 1 has applied and FR-005's checks have run: FR-003's removal and its test.

### Completion

- The completion ritual: a decision file under `docs/decisions/identity-and-access/` (its fence: the
  session key names its principals, carries no Deny because of DynamoDB's service-principal grants,
  and the dev store delegates), the delivery doc with the mutation runs, `sh scripts/gen-index.sh`.
