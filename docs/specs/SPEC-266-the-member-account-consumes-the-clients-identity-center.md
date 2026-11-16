---
type: Spec
id: SPEC-266
title: "The Member Account Consumes the Client's Identity Center"
description: "Creates, behind one switch and from four Identity Center inputs the client's admins supply, every member-account consumer Phase 5 needs: the Access Grants instance and its location, the Lake Formation Identity Center configuration, an Identity Center workgroup, the carrier role bounded by an allow-set gate, and the key that seals a context to its bearer."
spec_status: Draft
depends_on: []
arc: carrier
arc_order: 1
---

**Dependency notes:**
- **The AWS provider at 6.19 or later.** `infra/` pins `~> 5.0`, locked at 5.100.0, which has
  neither `aws_lakeformation_identity_center_configuration` (it first ships in 6.19.0) nor
  `aws_athena_workgroup`'s `identity_center_configuration` and
  `query_results_s3_access_grants_configuration` blocks (absent at 5.100.0, present from 6.10.0).
  The major upgrade is its own spec, proposed as a separate session on 2026-11-16 and not yet
  numbered. **The gate is the pin, not an id:** Phase 2 here does not start until `infra/providers.tf`
  on `origin/main` requires 6.19 or later. Phase 1 (the deploy role's grant) does not need the new
  resources and can land before it.
- **SPEC-267** is the Python half: it consumes the carrier role, the key and the API's new
  environment from this spec, and it builds after this spec's second PR.
- **SPEC-268, the Phase 5 server-exchange spec** (sibling, being written) seals with the key this spec
  creates. The interface between the two is SPEC-267's *API / Interface Contract*.

## Overview

The client runs one organization instance of IAM Identity Center for every account, managed through
its Landing Zone Accelerator. Its admins own the instance, the customer-managed application, the
trusted token issuer that points at our Cognito pool, the application's scopes and its actor policy.
**We build no Identity Center infrastructure.** What Phase 5 needs in OUR account is the set of
things that consume that instance: the S3 Access Grants instance associated with it, Lake
Formation's Identity Center configuration, an Athena workgroup that accepts identity-enhanced
sessions, the carrier role the API assumes with a user's identity context, and the key that binds a
forwarded context to the bearer it travels with. This spec creates those, from four values the
admins hand us, behind one switch that stays off until they do. Nothing here changes what a user
sees: no route uses any of it until SPEC-267 and the specs after it.

## Scope

### In Scope

- Five root variables: the switch and the four Identity Center inputs, validated so an unset
  repository variable cannot pass as a value.
- The Access Grants instance associated with the client's instance, one location for the
  user-space bucket and its location role. **No grants**: per-user grants are the provisioner's
  identity-shaped pass (`transition_plan.md` §3.12), a later spec.
- The location role on the user-space bucket policy's principal list, and a test that keeps the
  carrier role off it.
- The Lake Formation Identity Center configuration, created and never adopted.
- An Identity Center enabled Athena workgroup for the portal, and the decision on its
  `EnforceWorkGroupConfiguration` (FR-003).
- The carrier role, its trust and permissions, and the allow-set gate §3.6's amendment owes.
- The sealing key and its policy.
- The API role's grant to assume the carrier role, and two environment variables for SPEC-267.
- The deploy role's new grant, in its own PR before the rest (FR-006).
- A guard in the apply job that refuses deleting, forgetting or repointing the account singletons
  without a dispatch override (FR-007).

### Out of Scope

- **Anything in Identity Center itself**: the instance, the application, the trusted token issuer,
  scopes, the actor policy, user assignment to the workgroup's or Lake Formation's application.
  Those are the admins' (the request list is a sibling session's work).
- **The server's exchange and its task-role grant** (`sso-oauth:CreateTokenWithIAM`): the Phase 5
  server-exchange spec. This spec's key policy names the task role; it grants it nothing else.
- **Moving any route onto the carrier session**, any presign from vended credentials, and any
  query on the new workgroup. Later specs; this one moves no traffic.
- **The second workgroup for the driver path** (§3.10), Access Grants on the shared-space bucket,
  and any shared-space bucket policy (§3.6 leaves that to the shared-space grants spec).
- **Retiring the interim plane.** The portal role and its tags are untouched.
- **The provider upgrade** (dependency notes).

---

## Functional Requirements

### FR-001: Four inputs and one switch decide whether the consumers exist

#### Description:

The root gains `identity_center_enabled` and four inputs: `identity_center_instance_arn`,
`identity_store_id`, `identity_center_application_arn` and `identity_center_token_issuer_audience`.
This spec is their one home; later specs read them, they do not re-declare them. A new module,
`infra/modules/identity-center-consumers/`, holds every resource FR-002 to FR-005 create, and the
root counts it on the switch, the way the web tier's modules are counted. **The switch is a string
for the reason `web_tier_enabled` is one**, and it defaults to `"false"`. An unset GitHub repository
variable arrives as the empty string rather than absent (`infra/info/deploy-role-iam.md`, *Domain
variables*). So each input's own `validation` accepts the empty string or its shape, and a root
`terraform_data`, counted on the switch, carries one `lifecycle { precondition }` per input. Each
precondition refuses an empty value while the switch is `"true"`, with a message naming that
variable. A precondition rather than a validation is used because CI runs OpenTofu `~1.8`, and no
validation under `infra/` references a second variable today.

Switching the consumers off is guarded separately (FR-007).

The identity store id and the token issuer audience are not consumed by any resource here. They are
declared here so the four inputs have one home, and exported as root outputs for the provisioner and
the server spec to read.

**There is no Region input.** The Identity Center instance, the Access Grants instance, the
workgroup and Lake Formation must all be in one Region (§4.4), so the instance's home Region is
`var.aws_region` by requirement, and every consumer, the server's `sso-oauth` client included, uses
it. No ARN carries the instance's Region, so a plan cannot check it. The requirement goes on the
admins' request list, and a mismatch shows up in the Phase 3 or client-environment apply.

#### Acceptance Criteria:

- [ ] `identity_center_enabled` accepts exactly `"true"` and `"false"`, defaults to `"false"`, and
  any other value (including `"1"`, `"TRUE"` and `""`) fails validation.
- [ ] With the switch `"true"`, each input that is empty or off its shape fails the plan with a
  message naming that variable. The shapes: instance `^arn:aws:sso:::instance/(sso)?ins-[0-9a-f]{16}$`,
  identity store `^d-[0-9a-f]{10}$`, application
  `^arn:aws:sso::[0-9]{12}:application/(sso)?ins-[0-9a-f]{16}/apl-[0-9a-f]{16}$`, audience
  `^[A-Za-z0-9._:/-]{1,256}$`. A test drives each variable with the empty string and with one
  off-shape value on a scratch root, asserts the message names that variable (the reason, not the
  exit code), and runs under the OpenTofu version CI pins rather than whatever is installed locally.
- [ ] With the switch `"false"` and every input empty, the plan validates and the module plans
  nothing. A test reads `infra/main.tf` and asserts the module call is counted on the switch.
- [ ] The application ARN's account and the instance's are not required to be ours: a test asserts
  no validation compares either to `data.aws_caller_identity`, because under LZA both live in the
  management or delegated-admin account.
- [ ] `deploy-infra.yml` passes the five as `TF_VAR_` repository variables, and the switch falls
  back to `"false"` when unset (the web tier's fallback is `"true"`; this one is the opposite on
  purpose, since an unset input must never build half the consumers).
- [ ] Root outputs export `identity_store_id` and `identity_center_token_issuer_audience` as given,
  and `carrier_role_arn`, `identity_context_key_arn`, `access_grants_instance_arn` and
  `identity_center_workgroup_name`, which are empty strings with the switch off. These names are the
  interface the server-exchange spec reads.

### FR-002: The Access Grants instance and the user-space location, with no grants

#### Description:

One `aws_s3control_access_grants_instance` with `identity_center_arn` set to the instance input. One
location, `s3://<user-space bucket>/`, registered with a new **location role**,
`<project>-<env>-access-grants-location`. Its trust admits `access-grants.s3.amazonaws.com` for
`sts:AssumeRole`, `sts:SetSourceIdentity` and `sts:SetContext`, conditioned on `aws:SourceAccount`
(ours) and `aws:SourceArn` (this account's Access Grants instance). Its permissions are object read,
write, delete, `ListBucket`, `AbortMultipartUpload` and `ListMultipartUploadParts` on that bucket,
and never `ListBucketMultipartUploads` (`deploy-role-iam.md`: it ignores `s3:prefix`). The policy
also carries **an explicit Deny of `s3:*` on `<bucket>/_*`**, and of `ListBucket` under
`StringLike` `s3:prefix` `_*`. The bucket holds system documents there (`_config/`, `_directory/`),
and no username can start with `_`. Without the Deny, a grant to any grantee on `*` would vend
credentials that write the feature flags past the bucket's own deny.

One gap is accepted: a listing with no prefix, or an empty one, matches no `s3:prefix` condition,
so it would return the `_config/` and `_directory/` key names, though not their contents. Only a
grant scoped to the location root can make such a listing, because a vended session is the role's
policy intersected with the grant. That grant already exposes every user's keys, so the gap adds
nothing to what it exposes. The provisioner's fence, recorded in this spec's decision file, forbids
it: per-user and per-space prefixes only, and never the location root. No
grant is created. **Only the deploy role may create one:** no identity policy under `infra/`
outside the deploy role's grants `s3:CreateAccessGrant`. The provisioner spec that issues the
per-user grants inherits the fence written into this spec's decision file: directory-user and
directory-group grantees only, never an IAM grantee, and never a grant scoped to the location root. Access Grants accepts IAM principals as
grantees, and a grant to the carrier role would apply to every user's carrier session. **The location role joins the user-space bucket policy's `StringNotLike` principal list in
the same change**, as a constructed ARN in root `locals`, present whatever the switch says. Vended
credentials act as that role, so without it every presign from them is denied on this bucket. G9
passed on a bucket with no policy and could not catch this (§3.12 item 5). Athena's result writes
on the FR-003 workgroup also go through Access Grants, as the same role.

#### Acceptance Criteria:

- [ ] A test renders `user-space-bucket-policy.json.tftpl` and asserts the location role's ARN is in
  the deny statement's `aws:PrincipalArn` exception list and the carrier role's is not. Both are
  checked as the exact constructed strings, so a pattern that matched both would fail.
- [ ] A second test asserts that no resource policy under `infra/` names the carrier role's ARN or
  its local. The allow-set gate (FR-004) bounds identity policies only, and a resource policy naming
  the role would grant around it.
- [ ] The location role's trust has one statement with exactly the three actions and both source
  conditions, asserted whole against a literal copy in the test (a substring check would survive a
  dropped condition).
- [ ] The location role's policy names no `ListBucketMultipartUploads`, no `Resource: "*"`, and no
  bucket but the user-space one.
- [ ] No `aws_s3control_access_grant` resource exists anywhere under `infra/`, and no identity
  policy outside the deploy role's templates names `s3:CreateAccessGrant` (both asserted).
- [ ] The location role's `_*` Deny is asserted whole, both the `s3:*` object statement and the
  `ListBucket` condition on `s3:prefix`, and each half is mutation-tested once.
- [ ] With the switch on, a pre-existing Access Grants instance in the account fails the apply
  rather than being adopted. Proved in the stand-in run (Phase 3) by reading the apply's error, or
  recorded as owed if the stand-in account has none to collide with.

### FR-003: Lake Formation's Identity Center configuration and the portal's Identity Center workgroup

#### Description:

`aws_lakeformation_identity_center_configuration` with `instance_arn` set to the input. It is an
account singleton that a second creator cannot have and a replacement breaks for every consumer
(§4.4). So it is **created, never adopted**: a configuration that already exists fails the apply
with the service's own error, and adopting one is a separate, deliberate PR with an `import` block,
after the ownership line in the coordination contract says it is ours.

One workgroup, `<workgroup_name>-idc`, with `identity_center_configuration` enabled on the instance
input, `query_results_s3_access_grants_configuration` enabled (`DIRECTORY_IDENTITY`,
`create_user_level_prefix = false`), engine version 3 pinned, the existing scan cutoff, CloudWatch
metrics on, `SSE_S3` result encryption, and **no workgroup output location**. A query that names no
`OutputLocation` is then refused by Athena rather than written anywhere.

**DECIDED: `enforce_workgroup_configuration = false`, and the API keeps supplying a per-user
client-side `OutputLocation`.** The reason is the execution-id fence
(`docs/decisions/identity-and-access/`, *An execution id is a claim*): every route that names an
execution proves it is the caller's by its recorded output location under `user_results_prefix`,
which is keyed on the username. Enforcing the workgroup's settings without the user prefix would put
every user's results in one location, which the proof cannot tell apart. Enforcing them with
`create_user_level_prefix` would key results on the Identity Center user id, which the API never
sees, because the context is opaque (§4.7). Either way, the proof and every results route would be
rewritten. Phase 0 measured that `CreateWorkGroup` accepts an Identity Center workgroup with this set
to false and stores it. **What it did not measure is whether a query on such a workgroup honours a
client-side location.** This spec moves no query onto the workgroup, so that premise gates the spec
that does, not this one. It is written as a row in `docs/testing/owed.md`: a `StartQueryExecution`
on this workgroup, from an identity-enhanced carrier session, with `OutputLocation` under the user's
results prefix, reports that location in `GetQueryExecution` and writes its result there through
the user's own Access Grant. If the row fails, this decision is rewritten in place with a History
entry, and the query-move spec re-keys the ownership proof. The workgroup is not rebuilt, because
the setting updates in place (only its authentication method is fixed at creation).

#### Acceptance Criteria:

- [ ] A test reads the workgroup's HCL and asserts each setting named above, including
  `enforce_workgroup_configuration = false` and the absence of `output_location`.
- [ ] No `import` block and no data source reads an existing Lake Formation Identity Center
  configuration (asserted by a test), so the module cannot adopt one silently.
- [ ] Neither PR's diff touches a file under `infra/modules/analytics/`, so the portal workgroup
  and `aws_lakeformation_data_lake_settings` are unchanged. This is checked at the diff review,
  because a test comparing against `origin/main` stops meaning anything once the change merges.
- [ ] `docs/testing/owed.md` carries the client-side result-location row as worded above, naming
  the query-move spec as the one it gates.
- [ ] A decision file under `docs/decisions/analytics/` records the
  `enforce_workgroup_configuration` decision, its reason, and the owed row that can reverse it.

### FR-004: The carrier role, bounded by its own policy, and a gate that keeps it within the allow-list

#### Description:

`<project>-<env>-carrier`, with `max_session_duration = 3600`. The API reaches it by role chaining
from a Lambda execution session, which STS caps at one hour, and Phase 0 measured that STS ends the
session at the context's expiry when that comes first.

**Trust: one statement.** The principal is the API's execution role alone, as a constructed ARN.
The actions are `sts:AssumeRole` and `sts:SetContext`, and nothing else; no `sts:TagSession`, since
the carrier takes no tags. The conditions:
- `ForAllValues:ArnEquals` on `sts:RequestContextProviders` naming
  `arn:aws:iam::aws:contextProvider/IdentityCenter`, with `Null` `false` on the same key, so a call
  carrying no context cannot satisfy it vacuously;
- `ArnEquals` on `sts:RequestContext/identitycenter:InstanceArn` naming the instance input;
- `ArnEquals` on `sts:RequestContext/identitycenter:ApplicationArn` naming the application input.

Both Identity Center keys are on AWS's list of STS condition keys for Identity Center
(`singlesignon/latest/userguide/condition-context-keys-sts-idc.html`, read 2026-11-16). That page
shows no trust policy, and a condition on a key the caller does not populate fails closed
(`deploy-role-iam.md`), so the live run (Phase 3 and SPEC-267's) is what proves STS populates them.

**Permissions: one inline policy, every action named, none wildcarded.**
- Athena `StartQueryExecution`, `StopQueryExecution`, `GetQueryExecution`, `GetQueryResults` and
  `GetWorkGroup`, on the FR-003 workgroup.
- Glue `GetDatabase`, `GetDatabases`, `GetTable`, `GetTables`, `GetPartitions` and
  `BatchGetPartition`, on this account's catalog, `database/*` and `table/*/*`. Lake Formation, keyed
  on the propagated user, decides which of those a session can read (§3.7). The core datasets do not
  exist yet, so a name-scoped list would only be rewritten when they do.
- `lakeformation:GetDataAccess`.
- `s3:GetDataAccess`, `s3:GetAccessGrantsInstanceForPrefix` and `s3:ListCallerAccessGrants`.

There is **no S3 data action, no KMS, no SQS, no Step Functions and no IAM.** Phase 0 measured that
the `AWSIAMIdentityCenterAllowListForIdentityContext` Deny was not in effect on an identity-enhanced
session, so nothing outside this policy limits what the session can do (§3.6). `Resource: "*"` is
allowed only on an action the AWS Service Reference gives no resource type
(`lakeformation:GetDataAccess` is one, since Lake Formation publishes none). Each such action is
recorded in the gate with that reason, under the same discipline as the deploy role's
`NON_SCOPABLE`.

**The allow-set gate.** `lambdas/test_carrier_allow_set.py` holds a vendored copy of the allow-list,
`AWSIAMIdentityCenterAllowListForIdentityContext` version 12, taken from `aws iam get-policy-version`
byte for byte and stored with its version id. Its `Deny`'s `NotAction` list is the allow set. The
gate finds every policy attached to the carrier role anywhere under `infra/` and checks these:
1. Every allowed action is matched by an entry of the allow set, using IAM's case-insensitive
   wildcard matching against each entry. Version 12's entries are all literal today, read
   2026-11-16, and every action the permissions above name is among them. If an action the role
   needs is ever not covered, it is dropped from the role and named in the delivery doc; the gate is
   never widened to admit it.
2. No action contains `*` or `?`.
3. No Allow statement uses `NotAction` or `NotResource`.
4. No managed policy is attached, because its actions are not in the repository to check.
5. `Resource: "*"` appears only on an action recorded as having no resource type.
6. The set of carrier policy documents it found equals the set the module declares. A document
   attached outside the files it reads fails the gate rather than going unmeasured.

The vendored copy is re-vendored on purpose, never fetched at test time: a test that reaches the
network fails on a runner without egress.

The API's execution role gains `sts:AssumeRole` and `sts:SetContext` on the carrier's constructed ARN,
whatever the switch says. A grant on a role that does not exist authorizes nothing. The API Lambda
gains `CARRIER_ROLE_ARN` and `IDENTITY_CONTEXT_KEY_ARN`, which are empty with the switch off.

#### Acceptance Criteria:

- [ ] The gate passes on the real carrier policy, and it has a **fixture corpus** under
  `lambdas/fixtures/carrier_allow_set/`. Each of checks 1 to 6 has one planted document that the
  gate refuses, and the test asserts the refusal's reason names that check and the offending
  action, statement or file. The planted actions are `s3:GetObject`, `s3:Get*`, `athena:*`, a
  `NotAction` Allow, an `aws_iam_role_policy_attachment` to the carrier, `Resource: "*"` on
  `glue:GetTable`, and a carrier policy in a file outside the gate's set. Two passing fixtures
  assert silence: the real policy, and a `Resource: "*"` on `lakeformation:GetDataAccess`.
- [ ] Each of the six checks is mutation-tested once: disable it, watch its fixture redden, then
  revert. The delivery doc says so per check.
- [ ] The vendored document's version id is `v12`, and a test asserts it, so re-vendoring is a
  visible edit.
- [ ] The trust policy is asserted whole against a literal copy in the test: exactly one statement,
  exactly the API role as principal, exactly the two actions, and exactly the four condition
  entries above.
- [ ] `max_session_duration` is 3600, asserted.
- [ ] The API role's policy carries the carrier grant with exactly `sts:AssumeRole` and
  `sts:SetContext`, and no other statement in it names the carrier.

### FR-005: The sealing key: only the server may seal, only the API may unseal

#### Description:

A symmetric customer-managed key, `alias/<project>-<env>-identity-context`, with rotation on and a
30-day deletion window. Its policy **does not delegate to the account's IAM**, unlike the session
table's key. With delegation, any principal that IAM allows could unseal, or re-seal a raw context
to its own `sub`, and the server's exclusive `Encrypt` is the property the binding rests on (§4.7).
The statements:
- **Administration for the deploy role alone**, named as the statement's `Principal` (the role
  always exists). KMS's safety check refuses a policy that would lock out its caller, and a named
  principal is the form that check is documented to read. The actions are describe, get, list, put
  the key policy, enable and disable rotation, tag and untag, schedule and cancel deletion, update
  the description, and manage aliases. No cryptographic action.
- **`kms:Encrypt` for the web tier's task role alone.** It uses `Principal: "*"`, conditioned on
  `aws:PrincipalArn` equal to the task role's constructed ARN, `kms:CallerAccount` equal to ours,
  `kms:EncryptionContext:purpose` equal to `identity-context` (the value both specs agreed), and
  `ForAllValues:StringEquals` on
  `kms:EncryptionContextKeys` for `purpose` and `sub`. `Null` `false` is set on that key **and on
  `kms:EncryptionContext:sub`**, so a context carrying `purpose` alone, which the `ForAllValues`
  would accept, is refused. The key then enforces that every seal names a bearer. The
  principal is a condition and not a named `Principal`, because the task role does not exist while
  the web tier is switched off. KMS refuses a key policy that names a principal which does not
  exist, and a condition is not validated that way.
- **`kms:Decrypt` for the API's execution role alone**, with the same conditions and the API role's
  ARN.
- **An explicit Deny** on `kms:Encrypt` for every principal but the task role, and on `kms:Decrypt`
  for every principal but the API role. Both are keyed on `aws:PrincipalArn`, together with a Deny
  for everyone on `kms:ReEncrypt*` and `kms:GenerateDataKey*`. ReEncrypt is how a holder of
  ciphertext moves it under a key someone else can decrypt.

The deploy role keeps the reads its refresh needs, so the policy cannot lock it out of the next
plan (`deploy-role-iam.md`, *Resource policies can lock out the deploy role*). Losing the deploy role
loses administration of the key. That is accepted, because the key protects nothing durable. A
sealed context lives at most an hour, so a replacement key costs every session one re-seal at its
next context refresh.

**Two things the binding rests on, said plainly in the decision file.**
- **The deploy role is the trust root.** Its `kms:PutKeyPolicy` lets it grant itself `Encrypt` and
  `Decrypt`, so whoever can run the deploy role controls the binding.
- **`aws:PrincipalArn` matches a role by NAME**, where a named `Principal` is pinned to the role's
  unique id. While the web tier is off and the task role does not exist, anyone able to create a
  role under that name would gain `Encrypt`. That is accepted only because no identity policy under
  `infra/` other than the deploy role's grants `iam:CreateRole`, and a test holds it. No identity policy gains a KMS grant: the key policy alone grants, and naming
both sides would leave two places to keep in step.

#### Acceptance Criteria:

- [ ] A test renders the key policy and asserts that the principals allowed `kms:Encrypt` are
  exactly the task role, the principals allowed `kms:Decrypt` are exactly the API role, no statement
  names the account root, and the Deny covers all four action families. Each assertion is a
  set-equality, not a membership check.
- [ ] The test asserts the encryption-context conditions exactly, including both `Null` guards
  (on `kms:EncryptionContextKeys` and on `kms:EncryptionContext:sub`), because a `ForAllValues` on an
  absent key is true.
- [ ] A test asserts that no identity policy under `infra/` outside the deploy role's templates
  grants `iam:CreateRole`.
- [ ] Each of those assertions is mutation-tested once (add a root statement; widen Encrypt to the
  API role; drop the `sub` `Null` guard; drop `ReEncrypt*` from the Deny), and the delivery doc
  lists the four reddened runs.
- [ ] No identity policy under `infra/` names the key's ARN or alias with `kms:Encrypt` or
  `kms:Decrypt` (asserted).

### FR-006: The deploy role's grant lands first, in its own PR

#### Description:

A new managed policy, `github-actions-deploy-identity-center.json.tftpl`, attached to the deploy
role. It holds what FR-002 to FR-005 need: the Access Grants instance, its Identity Center
association and its location; `iam:PassRole` on the location role, conditioned on
`iam:PassedToService` = `access-grants.s3.amazonaws.com`; the Lake Formation Identity Center
configuration; the workgroup's Identity Center settings; the two roles and their policies; the key,
its policy and its alias; and **the Identity Center and RAM actions those services call on our
behalf**. Associating Access Grants, creating Lake Formation's configuration and creating an
Identity Center workgroup each create an Identity Center application against the instance, and
Lake Formation's creates a RAM share.

The list is derived at build time, not guessed:
- from each resource's create, read, update **and delete** at the pinned provider version (*A
  destroy can authorize against `*/*`*);
- from AWS's documented permissions for each on-behalf call;
- from `aws iam simulate-custom-policy` against a service-wide ARN for every action placed on
  `Resource: "*"`.

It lands in **PR 1, alone**, and applies green on `main` before PR 2 opens. Every plane module's "no
`time_sleep` needed" comment relies on that order. PR 2's first-use resources sit behind a
`time_sleep` whose `triggers` key on this policy's body, so a later edit to the grant re-fires the
guard.

#### Acceptance Criteria:

- [ ] PR 1 changes only the new template, its attachment and the base README's grant list, and
  `lambdas/test_deploy_platform_policies.py` (budget and wildcard rules) passes on it. A test asserts
  the new template's path is in that suite's `MANAGED_POLICIES` glob result, so it is measured
  rather than assumed to be.
- [ ] The role's managed-policy attachment count after PR 1 is counted as resource blocks, per
  `deploy-role-iam.md`, and asserted at or below `MAX_ATTACHED_MANAGED_POLICIES`.
- [ ] Every `Resource: "*"` action in the new template is in `NON_SCOPABLE` with a recorded
  simulate, or narrowed by a condition recorded in `CONDITION_NARROWED_ACTIONS`.
- [ ] PR 2 does not open until PR 1's deploy run on `main` is green, and the PR 2 body links that
  run.
- [ ] The cross-account half (the on-behalf calls against an organization instance in another
  account) is a row in `docs/testing/owed.md`. Our account has no organization, so Phase 3's
  stand-in proves only the same-account half, and the delivery doc says which half was proved.

### FR-007: Switching the consumers off, or repointing them, takes a deliberate second act

#### Description:

**Switching off destroys account singletons, so it takes a second, deliberate act.** Setting the
switch to `"false"` would delete the Lake Formation Identity Center configuration and the Access
Grants instance, which §4.4 says every consumer in the account shares. That makes it unlike
`web_tier_enabled`, which is flipped for cost. So a new guard,
`scripts/identity_center_destroy_guard.py`, runs **in the apply job**, which is the one that runs on
a merge, a dispatch and a `skip_refresh` break-glass alike. Today that job runs
`tofu apply -auto-approve` with no saved plan, and the PR-only plan job never sees what the merge
applies. So the existing `OpenTofu apply` step's `run` block becomes the four lines below. They stay
**one step**, for two reasons: every step that plans or applies must start with `tf_var_guard.py`
and carry `REPO_VARS`, and a saved-plan apply re-reads `TF_VAR_` values, so a second step with
copied variables could disagree with the plan.
1. `tofu plan -lock-timeout=10m $REFRESH_FLAG -out=tfplan`;
2. `tofu show -json tfplan > plan.json`, written to a file rather than piped, because a pipe without
   `pipefail` hides a failed `show`;
3. `python3 ../scripts/identity_center_destroy_guard.py plan.json`;
4. `tofu apply -lock-timeout=10m tfplan`, which applies exactly the plan the guard read.

The plan and the apply each carry the lock wait, because a PR's plan can hold the state lock, and
the lock is released between the two. The workflow's `paths:` filters name the script and its
fixtures, as `test_config_workflows.py` requires of every file a run block names.

**The guard keys on resource TYPE at any address, not on a module path.** A `moved` block or a
refactor can relocate a resource without a delete, and the next change would then delete it at an
address a path match ignores. It refuses three things:
- any change whose actions include `delete` (a replacement included) on an
  `aws_s3control_access_grants_instance` or an `aws_lakeformation_identity_center_configuration`;
- a `forget`, the action a `removed` block plans, on either type. It drops the singleton from
  state, and the next switch-on then collides with it;
- an update on either type that changes `identity_center_arn` or `instance_arn`, since repointing
  either breaks every consumer just as a delete does. An attribute counts as changed when
  `after_unknown[attr]` is true or `before[attr] != after.get(attr)`, because an unknown value is
  dropped from `after` rather than set to null, and a key-in-`after` test would pass it;
- a plan file that is missing, unparseable or has no `format_version`, which fails closed.

A plan with no changes is not an empty plan: it parses, and the guard is silent. The override is the
`workflow_dispatch` input `allow_identity_center_destroy`, which defaults to `false`. A push to
`main` never carries it, so no merge can delete or repoint them. **A merge that switches them off
therefore turns `main` red, by design**, and it stays red until a dispatch with the override
applies it. The fix for that red is the dispatch, never a revert of the switch-off. The guard is a
gate, so it gets a fixture corpus.

#### Acceptance Criteria:

- [ ] The destroy guard has a fixture corpus of saved-plan JSON documents.
  - Refused, each asserting a reason that names the address and the rule:
    - a `delete` of each guarded type at the module's indexed address
      (`module.identity_center_consumers[0]…`);
    - a `["delete", "create"]` replacement, and a `["create", "delete"]` one
      (`create_before_destroy`);
    - a `["forget"]` of each guarded type;
    - a `delete` of a guarded type at an address outside the module, as after a `moved` block;
    - an update changing `identity_center_arn`, one changing `instance_arn`, and one where
      `identity_center_arn` is unknown (`after_unknown`);
    - a missing file, an unparseable file, and a document with no `format_version`.
  - Silent:
    - a plan with zero resource changes;
    - creates of both types;
    - an update to a guarded type that changes only tags;
    - a `delete` of an unguarded type, such as the workgroup;
    - a guarded `delete` with the override set.
  - Each refusal rule is mutation-tested once.
- [ ] The apply step's `run` block runs the plan, the `show`, the guard and the apply in that
  order, with `-lock-timeout` on the plan and the apply. A test reads the workflow and asserts all
  of these:
  - the order;
  - that the apply names the same plan file the guard's JSON came from;
  - that no `tofu apply` in the job runs without a plan file;
  - that the `paths:` filters name the script.

  `test_config_workflows.py`'s existing lock-wait and `tf_var_guard` checks pass on it unchanged, and
  the dispatch input defaults to `false`.

---

## Data Model

```hcl
# infra/variables.tf — the five, and the shape they validate to when the switch is "true"
variable "identity_center_enabled"               { type = string, default = "false" } # "true" | "false"
variable "identity_center_instance_arn"          { type = string, default = "" }
variable "identity_store_id"                     { type = string, default = "" }
variable "identity_center_application_arn"       { type = string, default = "" }
variable "identity_center_token_issuer_audience" { type = string, default = "" }

# infra/main.tf — constructed strings, known at plan, used whatever the switch says
locals {
  identity_center_enabled         = var.identity_center_enabled == "true"
  carrier_role_arn                = "arn:aws:iam::${account}:role/${project}-${env}-carrier"
  access_grants_location_role_arn = "arn:aws:iam::${account}:role/${project}-${env}-access-grants-location"
}
```

## Environment Variables

The API Lambda gains two, both empty with the switch off; SPEC-267 requires them lazily, only on a
route that declares the carrier plane, so an empty value never fails a cold start:

```
CARRIER_ROLE_ARN=arn:aws:iam::<account>:role/<project>-<env>-carrier
IDENTITY_CONTEXT_KEY_ARN=arn:aws:kms:<region>:<account>:key/<key-id>
```

## File & Folder Structure

```
infra/
├── modules/identity-center-consumers/
│   ├── main.tf            # Access Grants instance, location, LF configuration, workgroup
│   ├── iam.tf             # carrier role, location role
│   ├── kms.tf             # the sealing key and alias
│   ├── policies/          # carrier-trust, carrier-permissions, location-trust, location-permissions, key-policy (.json.tftpl)
│   ├── variables.tf, outputs.tf, README.md
├── modules/base/policies/github-actions-deploy-identity-center.json.tftpl
├── modules/data/policies/user-space-bucket-policy.json.tftpl   # + the location role
├── modules/api/                                                # carrier grant, two env vars
scripts/identity_center_destroy_guard.py                         # refuses a module delete without the dispatch override
lambdas/
├── test_carrier_allow_set.py
├── test_identity_center_consumers.py                           # switch, inputs, trust, key, workgroup, bucket policy
├── test_identity_center_destroy_guard.py                       # the guard's fixture corpus
├── fixtures/carrier_allow_set/                                 # the vendored allow-list v12 and the planted corpus
```

## Implementation Phases

### Phase 1: The deploy role's grant (PR 1)

- Derive the list per FR-006, simulate every wildcard, write the template and attach it.
- Land PR 1 through the queue; wait for its deploy run on `main` to go green.

### Phase 2: The consumers, behind the switch (PR 2)

- The five variables and their validation, the module counted on the switch, the outputs and the
  workflow's `TF_VAR_` lines.
- FR-002 to FR-005's resources; FR-007's guard and the apply step's new shape; the bucket-policy
  line; the API role's grant and two env vars.
- The tests, the allow-set gate with its corpus and its mutation runs, and the key-policy mutation
  runs.
- In our account the switch stays `"false"`, so the CI plan for PR 2 must show the bucket policy's
  one added ARN, the API role's added statement and two env vars, and nothing in the module. The PR
  body quotes that plan's summary line.
- Decision files:
  - the workgroup decision (FR-003), under `analytics/`;
  - *the carrier role is bounded by its own policy, because the allow-list is not a fence*, under
    `identity-and-access/`;
  - *we consume the client's Identity Center from four inputs and build none of it, and switching
    the consumers off takes a dispatch override*, under `infrastructure/`.

### Phase 3: Prove the apply, and the destroy, against a stand-in instance

- Our account is in no organization, so a throwaway Identity Center **account** instance stands in,
  as it did in Phase 0, with a customer-managed application and a trusted token issuer on the live
  Cognito pool. The build writes the stand-up and teardown as a script and hands it to Andrew,
  because production AWS writes are his to run.
- Under the PR queue lock: set the four inputs and the switch `"true"` as repository variables,
  dispatch `Deploy Infrastructure`, and record the apply. Then set the switch back to `"false"`,
  dispatch once **without** `allow_identity_center_destroy` and record the guard's refusal, dispatch
  again with it set to `true`, and record the destroy: every module resource gone, and the Access Grants
  instance, the Lake Formation configuration and the workgroup absent when read back from the
  account. Then run the teardown script.
- What it proves: the same-account half of FR-006's grant, the create and destroy paths, and FR-002's
  refusal of a pre-existing instance if one is planted. What it cannot prove, and the delivery doc
  says so: the cross-account calls, and whether STS populates the two Identity Center condition
  keys. SPEC-267's end-to-end run owns the second.
