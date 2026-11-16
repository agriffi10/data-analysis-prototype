---
type: Spec
id: SPEC-265
title: "The Bridge Pool Signs In Through Entra"
description: "Gives the successor account a Cognito User Pool federated to Entra ID over SAML, keyed on Entra's object id, with a pre-token trigger that looks the portal username up by that id, and a tested guardrail that no user token and no portal role can rewrite a federated identity or what keys it."
spec_status: Draft
depends_on: [SPEC-195, SPEC-203, SPEC-262]
---

**Dependency notes:** SPEC-195 (the API's verifier reads its issuer, audience and username claim
from configuration, which is what lets FR-004 repoint it rather than rewrite it). SPEC-203 (the
membership index, which replaces the Cognito membership slots whose write grant FR-005 drops).
SPEC-262 (the Next.js server is the OIDC client and the only holder of the user's tokens, so the
server's client is the only app client the bridge pool needs). `docs/transition_plan.md` is the
design: §2 item 1, §3.3 (*Variant B points the bridge at Entra*, and its guardrail), §6.1 (the
username claim, the guardrail on user tokens and on portal roles), §3.10 (the driver path's public
client, which this spec does not build but whose rules FR-002's test already holds), and Phase 1's
**[B]** items.

**Decided while authoring, 2026-11-16, by Andrew:**

- **SAML, not OIDC.** The plan let the bridge federate "over SAML or OIDC, as the client's
  established pattern does", with the federated subject either a persistent SAML `NameID` from
  `objectid` or "the OIDC `sub`". Microsoft's ID-token reference says Entra's `sub` is a pairwise
  identifier, unique to each application, and the `oid` claim is the object id. Cognito takes an
  OIDC-federated user's identity from `sub` and documents no way to take it from another claim. Over
  OIDC, then, the Cognito identity is never the object id, and the username list and Identity
  Center's `externalId`, both keyed on the object id, cannot be reached from it without a mapped
  attribute, which §6.1 rules out as a key. Over SAML, Cognito identifies the user by the `NameID`,
  and Entra can send a persistent `NameID` whose source is `user.objectid`. So the bridge is SAML,
  and if the client's established pattern is OIDC, the client is asked for SAML for this application
  (gate G8).
- **The lookup is a pre-token-generation trigger**, not a second reader in the server and the API.
  One function reads the federated subject and writes the username into the ID token, so the server
  and the API keep reading one claim name from one local, as they do today. The same trigger emits
  the object id as a claim, which Phase 5's trusted token issuer maps to Identity Center's
  `externalId`.

## Overview

The portal moves into the client's AWS environment, where everyone signs in with their corporate
Entra ID account. The client's established pattern is a Cognito User Pool federated to Entra, so the
portal keeps a pool, but only as a bridge. Entra authenticates the user, and Cognito turns that
sign-in into the token the portal and, from Phase 5, Identity Center consume. This spec builds that
bridge for the successor account and leaves the current environment exactly as it is. A user signs
in with Entra and sees no Cognito screen. Their portal username, which keys their S3 prefix and Glue
database, is looked up by their Entra object id, which never changes and is never given to anyone
else. The pool is shaped so that nobody can get a token any other way, and neither a user nor a
portal role can rewrite the identity a token carries or the index that turns it into a username. A
local sign-up, a second identity provider, an admin-scope token, or a portal role able to edit a
user, the pool or the index is how one person ends up with another person's files. So tests over
the infrastructure hold all of these, not a reviewer's memory.

## Scope

### In Scope

- A root flag, `entra_federation`, whose absence leaves today's pool and clients unchanged and whose
  presence configures the bridge, for the successor account.
- The bridge pool: one SAML identity provider (Entra), self-sign-up off, no local users, no sign-up
  triggers wired, no membership attributes, and the server's app client alone, restricted to the
  Entra provider, the `openid email profile` scopes and the refresh flow.
- A pre-token-generation trigger that looks the username up in an index keyed on the object id, and
  emits the username claim and the object-id claim.
- The two readers of the username claim (the server and the API's verifier), the sign-in
  redirect's provider name, and the verifier's audience, all switched by the same flag.
- Dropping the shared-spaces plane's Cognito write grant under the flag, and an IAM test that no
  portal role can change a bridge-pool user, the pool, its identity provider, its trigger, or the
  identity index.
- The deploy-role IAM for the new resource type (the identity provider) and the new function, in its
  own PR first.

### Out of Scope

- **Writing the identity index.** This spec defines the index's shape and reads it. The provisioner
  (§3.12, a Phase 1 item without a spec yet) writes it from the client's username list. Until then an
  operator writes an entry by hand for a live check. The list's own shape, delivery and fence are
  §3.12's open Phase 0 questions, not this spec's.
- **The Entra side.** The enterprise application, its persistent `NameID` sourced from
  `user.objectid`, the email claim it releases and its certificate are the tenant owner's (gate G8).
  This spec consumes the metadata URL.
- **What must land before the flag is set anywhere.** The flag changes three things other planes
  rely on today, and each needs its own work first. Setting the flag before all three land breaks a
  user-visible path:
  - **The shared-spaces plane's slot writes.** The bridge pool has no `custom:shared_space_k`
    attributes, and FR-005 removes the grant that wrote them, so the slot writes in
    `shared-space-common/membership.py` must stop. That is the Phase 1 item *Wire
    `MEMBERSHIP_SOURCE` to the index*, which has no spec yet. Without it, adding members to a shared
    space fails.
  - **The recipient checks.** `cpcommon.cognito.user_exists` (file-send and table-share) asks
    Cognito whether a portal username exists. In the bridge pool, Cognito usernames are
    `{provider}_{object id}`, so every recipient would read as unknown. Table Share is flagged off in
    Phase 1, and file-send is not. Moving the check off Cognito is its own spec.
  - **The per-user Glue database.** The flag unwires `post_confirmation`, which creates it today
    (§2 item 7). The provisioner (§3.12) takes that over.
- **The driver path's public client** (§3.10). It belongs to Phase 5, when an IdC workgroup exists to
  query. FR-002's test holds its rules the moment it is declared.
- **Identity Center.** The trusted token issuer, its `externalId` mapping on the object-id claim
  emitted here, and everything after the ID token are Phase 5's. They are client-owned under LZA.
- **Applying the flag.** The flag is unset in this repository's account and stays unset. Standing
  the portal up in the successor account is Phase 1's own workstream. The federated half of this
  spec's live check is owed until that account and G8 exist.
- **Local development against the bridge pool.** The bridge pool has no development client
  (Phase 1 [B]), so `npm run dev:session-env` keeps serving the current environment's pool. Under the
  flag the development session parameter is not created.
- **Entra sign-out.** Cognito's `/logout` ends the portal's session and not the Entra one. The
  leaver window is not a concern (Andrew, 2026-11-15, §4.7).

---

## Functional Requirements

### FR-001: The bridge pool federates to Entra over SAML, and nothing else can sign in

#### Description:

A root variable `entra_federation`, default `null`, of type
`object({ provider_name = string, metadata_url = string })`, is passed to `infra/modules/auth`.
While it is `null`, every resource the module declares today is configured exactly as it is today.
While it is set:

- The pool has one identity provider, `aws_cognito_identity_provider.entra` (`count` on the flag),
  of type `SAML`, named `provider_name`, with `provider_details` of `MetadataURL = metadata_url` and
  `IDPInit = "false"`, and an attribute mapping of `email` only, from Entra's email-address claim.
  Cognito takes the user's identity from the SAML `NameID`, which Entra sends as a persistent
  identifier sourced from `user.objectid` (G8, the tenant owner's configuration).
- `admin_create_user_config.allow_admin_create_user_only` is `true`. No local user can be created
  except by an administrator, and none is.
- The pool's `lambda_config` names the pre-token-generation trigger (FR-003) at `V2_0` and **no**
  `pre_sign_up` or `post_confirmation` trigger. `user_pool_tier = "ESSENTIALS"` is declared in both
  modes, because `V2_0` and Managed Login both need it, and it is what the pool has today.
- The pool declares no `custom:shared_space_k` attributes.
- The server's client takes `supported_identity_providers` from
  `aws_cognito_identity_provider.entra[*].provider_name`, a resource reference, so Terraform creates
  the provider before the client names it. Cognito rejects a client naming a provider that does not
  exist. The client also has `explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]` and
  `allowed_oauth_scopes = ["openid", "email", "profile"]`, and keeps token revocation on.
- The development client (`aws_cognito_user_pool_client.dev`) and the development session parameter
  are not created (`count` on the flag). Their outputs become nullable: the module's `dev_client_id`,
  root's `cognito_dev_client_id`, and the branding loop in `deploy-infra.yml`, which skips an output
  that is null.

**All three trigger functions are created in both modes**, with their roles, keep-warm targets and
invoke permissions. Only the pool's `lambda_config` changes with the flag. An unwired trigger cannot
be invoked by the pool, and creating them unconditionally keeps `fleet.py`'s inventory, the
deploy-lambdas `MISSED` check, the cold-start probes and the post-confirmation role that root
constructs as a Lake Formation admin true in both accounts. The only `count` added is on the
identity provider, the development client and the development session parameter. Each of the
latter two gets a `moved` block whose `from` is the address the current state holds.

**The shape the tests read.** Each client argument that differs by mode indexes one of two literal
objects, `local.client_settings.cognito` (today's values) and `local.client_settings.bridge`, by
`local.identity_mode` (`"cognito"` or `"bridge"`, from the flag). The pool's differing arguments
follow the same pattern. No argument is a ternary written inline, so a test reads each branch as a
literal.

#### Acceptance Criteria:

- [ ] With `entra_federation = null`, CI's `tofu plan` against this repository's account shows no
      change other than the new function, its role, log group, keep-warm target and invoke
      permission (FR-003), and the `moved` blocks' address changes with no destroy.
- [ ] With it set (a test fixture's values), `tofu validate` passes, and a plan in a scratch root
      shows one SAML identity provider, a `lambda_config` with only `pre_token_generation_config`, no
      `custom:shared_space_*` schema, one app client, and no development session parameter.
- [ ] Every `moved` block's `from` matches an address `tofu state list` reports today. The build
      checks this against the current state, not against the configuration.
- [ ] FR-002's test asserts that `client_settings.bridge.supported_identity_providers` references
      `aws_cognito_identity_provider.entra`, not `var.entra_federation`, so the dependency edge that
      orders the apply cannot be lost.

### FR-002: A presence test holds the guardrail on every client and on the pool

#### Description:

`lambdas/test_session_infrastructure.py` gains a test that reads **every** `aws_cognito_user_pool_client`
in the infra tree, with the sweep the revocation test already uses (raw headers counted against
parsed blocks). For each client it asserts, in the bridge branch of `local.client_settings`:

- `allowed_oauth_scopes` is **present** and does not contain `aws.cognito.signin.user.admin`;
- `explicit_auth_flows` is **present** and is exactly `["ALLOW_REFRESH_TOKEN_AUTH"]` (an omitted
  argument defaults to three flows, so absence fails);
- `supported_identity_providers` is **present**, is the Entra provider's reference, and never
  includes `COGNITO`;
- `enable_token_revocation` is `true`.

A client that does not read `local.client_settings`, such as a new client written with literals,
is asserted on its own literals by the same rules. For the pool it asserts, in the bridge branch:

- exactly one `aws_cognito_identity_provider`;
- `provider_details` has `IDPInit = "false"`;
- `allow_admin_create_user_only` is `true`;
- `lambda_config` has no `pre_sign_up`.

The `cognito` branch must equal today's values, which `SIGN_IN_SETTINGS` already pins. A
conditional guard owes both branches, and the `cognito` branch is the one serving users today.

#### Acceptance Criteria:

- [ ] The test passes on the FR-001 configuration.
- [ ] Each check fails on its own planted violation, with a message naming the client and the rule.
      The plants are: the admin scope added, `explicit_auth_flows` removed, `ALLOW_USER_SRP_AUTH`
      added, `COGNITO` added, a second identity provider, `IDPInit = "true"`,
      `allow_admin_create_user_only = false`, a `pre_sign_up` added to the bridge branch, and
      revocation off. The build runs each plant, records the failure message, then reverts it.
- [ ] A third `aws_cognito_user_pool_client` declared in a new file with literal settings that break
      the rules fails the test. This proves the sweep is tree-wide and not a named list.
- [ ] A `cognito` branch changed from today's value fails, so the test cannot be satisfied by
      weakening the current environment.

### FR-003: A pre-token trigger looks the username up by the object id

#### Description:

A new fleet function, `lambdas/pre-token-generation/pre_token_generation.py`, wired as the bridge
pool's pre-token-generation trigger at event version `V2_0`. When wired, it runs on every sign-in
and every refresh. For each event it:

1. Takes the subject from `userName`. It requires `userAttributes["cognito:user_status"]` to be
   `EXTERNAL_PROVIDER`, so an administrator-created local user named like a federated one does not
   pass. `userName` must start with the literal `{ENTRA_PROVIDER_NAME}_`, compared case-insensitively
   and never as a pattern. The remainder, lowercased, must match
   `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`.
2. Reads `identity-index/{object_id}.json` from the admin bucket, the one holding `memberships/`
   (`local.athena_admin_bucket_name`, passed as `IDENTITY_INDEX_BUCKET`), through an S3 client
   created at module scope.
3. Validates the entry: `object_id` equals the subject, and `username` matches
   `cpcommon.config.CATALOG_IDENTIFIER_RE` (no third copy of the rule).
4. On success, adds two claims to the ID token through
   `claimsAndScopeOverrideDetails.idTokenGeneration.claimsToAddOrOverride`: the username, under the
   name in `USERNAME_CLAIM`, and `entra_object_id` (the subject). Terraform renders `USERNAME_CLAIM`
   from `local.oidc_username_claim`, the local the server and the verifier read, so the writer and
   both readers take one name from one place.

It fails closed in two ways, chosen by whether retrying could help:

- **Refused, so no claims are added and the event is returned unchanged.** This covers a user who is
  not `EXTERNAL_PROVIDER` or whose `userName` lacks the prefix, a subject that is not a GUID (an
  Entra `NameID` misconfigured to a UPN lands here), no index entry, and an invalid entry. The server
  already refuses a sign-in whose ID token lacks the username claim (`handlers.ts`), and treats a
  refreshed token without it as a session that has ended (`session.ts`, `active`). The API's
  verifier rejects it too. The function logs one structured line with a reason code
  (`not_federated`, `subject_not_object_id`, `not_on_index`, `invalid_entry`) and the subject, never
  the username of another entry.
- **Raised, a fault.** Any S3 error other than a missing key, which fails that sign-in or refresh at
  Cognito. Which token-endpoint error a raised trigger produces on refresh is measured in the owed
  live check. If it is `invalid_grant`, the server ends the session (`session.ts`) and an S3 fault
  signs that user out. That is accepted: it fails closed, and their next sign-in succeeds once S3
  answers.

It is declared like the other Cognito triggers in `infra/modules/auth/lambda.tf`: a `docker-lambda`
module call, its own execution role, `s3:GetObject` on `{admin bucket}/identity-index/*` and nothing
else in S3, logs, and an invoke permission for the pool. It has `timeout_seconds = 5`, which matches
Cognito's wait, and `memory_mb = 512`, which buys CPU for the image's cold start inside that wait. It
joins `keep-warm.tf`'s daily invoke. `keep-warm.json` carries no `cognito:user_status`, so it is a
no-op by rule 1 and reads nothing.

#### Acceptance Criteria:

- [ ] A federated event whose index entry exists returns both claims with the entry's values, under
      the configured claim name. The test asserts that the S3 key requested was
      `identity-index/{subject}.json`.
- [ ] Each refusal returns the event with no `claimsToAddOrOverride`, and the logged reason code is
      the one named. Asserting the code alone is not enough: each test pairs one input with its code.
      The refusals tested are `not_federated`, once for a non-`EXTERNAL_PROVIDER` status and once for
      a missing prefix; `subject_not_object_id`, for a UPN; `not_on_index`; and `invalid_entry`, once
      for a mismatched `object_id` and once for a username failing the catalog rule.
- [ ] An S3 `AccessDenied` or throttle raises. A `NoSuchKey` does not raise.
- [ ] `keep-warm.json` run through the handler returns the event unchanged and makes no S3 call.
- [ ] The function is in `fleet.py`'s inventory and the cold-start probe set, carries the
      Google-style docstrings and no inline comments, and passes the layer import-safety test.
- [ ] The execution role's policy allows `s3:GetObject` on `identity-index/*` only, asserted over
      the template.
- [ ] After deploy in this account, where the function exists but is unwired, a cold invoke with a
      synthetic `EXTERNAL_PROVIDER` event, `userName` `unwired_{guid}`, for a subject with no entry, returns within 5 seconds,
      measured from the function's own `REPORT` line (`Init Duration` plus `Duration`), and logs
      `not_on_index`. This is a read-only half of the live check, runnable here.

### FR-004: The server and the API read the trigger's claim, and the redirect names Entra

#### Description:

- `local.oidc_username_claim` in `infra/main.tf` is `"portal_username"` when `entra_federation` is
  set and `"cognito:username"` otherwise. The server's `OIDC_USERNAME_CLAIM`, the verifier's
  `oidc_username_claim` and the trigger's `USERNAME_CLAIM` all read that one local.
- **Before the local can change**, `OIDC_USERNAME_CLAIM` moves from `OPTIONAL_SESSION_VARIABLES`
  into the server's required `SESSION_VARIABLES`, so a stale environment fails to start instead of
  silently reading `cognito:username` while the API reads `portal_username`. Root already renders it
  into the task definition. The build confirms the live task definition carries it before the
  promotion merges.
- `session_environment` becomes `merge(local.session_environment_base,
  local.session_environment_bridge)`. The base keeps today's literal block. The bridge part is
  `{ OIDC_IDENTITY_PROVIDER = one(aws_cognito_identity_provider.entra[*].provider_name) }` under the
  flag and `{}` otherwise. Referencing the provider resource ties the setting to the apply that
  creates the provider, because Cognito rejects an `identity_provider` the client does not list.
- The verifier's `oidc_audience` is the server's client alone under the flag, since there is no
  development client to name, and unchanged otherwise.

#### Acceptance Criteria:

- [ ] `lambdas/test_session_infrastructure.py` still proves both readers, and now the trigger, take
      the claim from the one local. Its session-environment reader reads the base block and the
      bridge part. Its dev-client assertions read the counted resource.
      `lambdas/test_api_module.py`'s claim pin moves from the literal `cognito:username` to the
      conditional, asserting both branches' values, and its audience pin asserts both modes.
- [ ] The server refuses to start, naming `OIDC_USERNAME_CLAIM`, when it is unset (a config test),
      and starts when it is set. `apps/portal/.env.example` documents it as required.
- [ ] Under the flag, `session_environment` carries `OIDC_IDENTITY_PROVIDER` from the provider
      resource and `oidc_audience` has one entry. Without the flag, neither changes from today.
- [ ] `authorizeUrl` sends `identity_provider` when the variable is set. This is already tested, and
      the build confirms the test still runs.

### FR-005: No portal role can change a bridge-pool user, the pool, its trigger or the index

#### Description:

In the bridge, what keys an identity is the SAML provider, the pool's clients and trigger wiring, the
trigger's code and configuration, and the identity index, not a user attribute. The guardrail covers
all of them.

- Under the flag, the shared-spaces plane's execution role does not carry the
  `CognitoMembershipAttributes` statement (`cognito-idp:AdminUpdateUserAttributes`, `AdminGetUser`,
  `ListUsers` on `userpool/*`). The statement moves out of
  `infra/planes/shared-spaces/execution.json.tftpl` into a separate policy whose attachment exists
  only while `entra_federation` is `null`.
- A new test, `lambdas/test_portal_roles_cannot_rewrite_identity.py`, reads every IAM policy
  template in the infra tree attached to a portal role: every plane's execution role, the API's, the
  server's task role, the shared portal role and the triggers'. The deploy role is not a portal role
  and is excluded by name, because it builds all of this. Matching is case-insensitive and
  wildcard-aware in both directions: a granted pattern like `cognito-idp:*`, `s3:Put*`, `*` or a
  resource like `{admin}/*` counts. A `NotAction` or `NotResource` Allow counts as matching. The test
  asserts that, under the flag, no `Allow` statement grants:
  - any `cognito-idp:` action other than `AdminGetUser` and `ListUsers`, the reads the recipient
    checks use;
  - any S3 write action (`PutObject`, `DeleteObject`, `PutObjectAcl`, `CopyObject` targets,
    `RestoreObject`, or a wildcard covering them) on a resource matching
    `{admin bucket}/identity-index/*`;
  - any `lambda:Update*`, `lambda:PutFunction*`, `lambda:AddPermission` or
    `lambda:DeleteFunction` on the trigger's function.

#### Acceptance Criteria:

- [ ] Under the flag, the shared-spaces role has no Cognito statement. Without it, the role's
      effective actions are unchanged from today, asserted over the rendered statements.
- [ ] The test passes on the FR-005 tree. Today's `{admin}/*` statements are Denies
      (`file-ops`, `archive`), and the test does not count a Deny as a grant.
- [ ] The test fails on each planted violation, with a message naming the template and the grant.
      The plants are: `cognito-idp:Admin*` added to a plane's template,
      `cognito-idp:UpdateIdentityProvider`, `cognito-idp:*`, a `NotAction` Allow, `s3:PutObject` on
      `{admin}/*`, `lambda:UpdateFunctionConfiguration` on `*`, and the moved policy's attachment
      losing its flag condition.
- [ ] The test's template count is compared with a raw count of `.json.tftpl` files under the policy
      directories it sweeps, so a template the sweep misses fails the test rather than passing over
      it.

---

## Data Model

```python
# admin bucket: identity-index/{object_id}.json, one object per Entra user, written by the
# provisioner (out of scope), read by the trigger (FR-003).
class IdentityIndexEntry(TypedDict):
    object_id: str  # Entra object id, lowercase GUID; equals the key's stem
    username: str   # catalog-safe portal username, CATALOG_IDENTIFIER_RE

# Claims the trigger adds to the ID token on success (FR-003).
class AddedClaims(TypedDict, total=False):
    # key: the value of USERNAME_CLAIM (local.oidc_username_claim, "portal_username" under the flag)
    entra_object_id: str  # mapped to Identity Center externalId in Phase 5

REFUSAL_REASONS = ("not_federated", "subject_not_object_id", "not_on_index", "invalid_entry")
```

```hcl
variable "entra_federation" {
  type = object({
    provider_name = string # the pool's name for the Entra IdP; also OIDC_IDENTITY_PROVIDER
    metadata_url  = string # Entra's federation metadata URL for the enterprise application
  })
  default = null
}

locals {
  identity_mode = var.entra_federation == null ? "cognito" : "bridge"
  # client_settings = { cognito = { ...today's literals... }, bridge = { ... } }  (FR-001)
}
```

## Environment Variables

The trigger reads `ENTRA_PROVIDER_NAME`, `IDENTITY_INDEX_BUCKET` and `USERNAME_CLAIM`, plus the
`LOGS_QUEUE_URL` and `ENV_NAME` that the observability module needs, as the other triggers do. All
are set by Terraform. Where the flag is unset, `ENTRA_PROVIDER_NAME` is the placeholder `unwired`,
from `try(var.entra_federation.provider_name, "unwired")`. The pool cannot invoke an unwired
function, so only a direct invoke reaches it. A synthetic `unwired_{guid}` event then exercises the
S3 read, which is what FR-003's cold-invoke check sends. The server's `OIDC_USERNAME_CLAIM` becomes required, and
`apps/portal/.env.example` documents it as such. Every developer reruns `npm run dev:session-env`
after the promotion merges.

## File & Folder Structure

```
infra/
├── variables.tf, outputs.tf           # entra_federation; cognito_dev_client_id nullable
├── main.tf                            # oidc_username_claim, session_environment, oidc_audience
├── modules/auth/
│   ├── cognito.tf                     # pool, identity provider, client_settings; moved blocks
│   ├── lambda.tf                      # the trigger, created in both modes
│   ├── keep-warm.tf, outputs.tf, variables.tf
│   └── policies/pre-token-generation-*.json.tftpl
├── modules/base/policies/github-actions-deploy.json.tftpl   # PR 1
└── planes/shared-spaces/                                    # the grant moved out, attached when flag off
.github/workflows/deploy-infra.yml     # branding loop skips a null dev client output
lambdas/
├── pre-token-generation/pre_token_generation.py (+ test)
├── test_session_infrastructure.py     # FR-002, FR-004
├── test_api_module.py                 # FR-004
└── test_portal_roles_cannot_rewrite_identity.py             # FR-005
apps/portal/src/server/session/config.ts (+ test), apps/portal/.env.example   # FR-004
```

## Implementation Phases

### Phase 1: Deploy-role IAM (its own PR, first)

- Read `infra/info/deploy-role-iam.md`. The deploy role scopes each trigger by name, so the new
  function needs the same statements `-pre-signup` has: the function, `-pre-token-generation-role`,
  its log group, and the probe invoke. Add those, and add `cognito-idp:CreateIdentityProvider`,
  `DescribeIdentityProvider`, `UpdateIdentityProvider`, `DeleteIdentityProvider` and
  `ListIdentityProviders` on `userpool/*`.

### Phase 2: The trigger (FR-003)

- The function, its tests, its role and template, the keep-warm target and probe, created in both
  modes and wired nowhere yet. It needs no `requirements.txt`, because boto3 is in the image. Deploy
  it and run FR-003's cold-invoke check here.

### Phase 3: The flag, the pool and the guardrail test (FR-001, FR-002)

- The variable, `identity_mode` and `client_settings`, the conditional pool and clients, the counted
  resources with `moved` blocks, the nullable outputs and the branding loop, and the presence test
  with its plants.

### Phase 4: The readers and the roles (FR-004, FR-005)

- Promote `OIDC_USERNAME_CLAIM` after confirming the live task definition carries it. Then add the
  conditional local, the trigger's `USERNAME_CLAIM`, the provider name and the audience. Move the
  shared-spaces grant and add the role test.

### Phase 5: Close-out

- The federated half of the live check is owed in `docs/testing/owed.md` until the successor account
  and G8 exist. Two real users sign in through Entra, and each ID token carries the expected username
  claim and `entra_object_id`. A user missing from the index is refused at sign-in, and no Cognito
  screen is shown. A refresh while the trigger raises records which token-endpoint error Cognito
  returns. Phase 1's own verification, the `username` session tag in CloudTrail, is the plan's and
  follows.
