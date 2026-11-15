# `auth` — the User Pool and the two Cognito triggers

A standalone Cognito User Pool for native username/password users (no external IdP), and the two
Lambda triggers that police and provision a new account. This module used to hold an Identity Pool
too, exchanging the user's token for scoped AWS credentials; it went when the browser stopped
making AWS calls, and the API now assumes the portal role from the same verified claims.

| File | Holds |
|---|---|
| `cognito.tf` | the User Pool, its schema and password policy, the portal server's client and the local dev client (each with its SSM parameter), the Hosted UI domain |
| `lambda.tf` | `pre-signup` and `post-confirmation`, their roles, log groups and invoke grants |
| `outputs.tf` | the pool and client ids, the server session's lifetime, the Hosted UI domain, and the triggers' names and role |
| `variables.tf` | the module interface |
| `policies/` | trust and permission templates for both triggers |

Code: `lambdas/pre-signup/`, `lambdas/post-confirmation/`.

## ⚠ Do not reintroduce `data "aws_region"` in this module

This module carries a module-level `depends_on = [module.base]`. **A module-level `depends_on` defers
every data source inside the module to apply time** whenever the dependency has a pending change —
and `module.base` changes on most PRs, since it holds the deploy-role policies. **A deferred value
on a ForceNew attribute plans a replacement**, and this module holds the user directory. Take the
region from `var.aws_region`, which is the same value by construction (`providers.tf` does
`region = var.aws_region`) and is known at plan time.

The rule was learned on the Identity Pool this module used to hold: a deferred
`data.aws_region.current` made the pool's provider name `(known after apply)`, and every infra merge
destroyed and recreated the principal-tag mapping the ABAC model then depended on. The pool is
retired. The general rule, and why `ignore_changes` is the wrong fix for it, is
`infra/info/deploy-role-iam.md`'s ForceNew data-source trap.

## The claims the API turns into principal tags

Per-user isolation is "attributes for access control": the API stamps a `username` principal tag
**server-side, from a claim of the verified ID token, never from anything the client sends**. This
pool issues the claims; the API reads them.

**The tag value must be `cognito:username`.** A first attempt, under the Identity Pool, mapped the
bare `username` claim and produced a CloudTrail `AssumeRoleWithWebIdentity` event with **no
`principalTags` at all** — that claim does not exist in a Cognito User Pool ID token — so the tag
was never stamped. The API reads `cognito:username` for the same reason (root's
`oidc_username_claim`).

Tag `shared_space_k` reads the `custom:shared_space_k` claim. A slot the user is not in carries no
claim, so the tag is not stamped and that slot's templated statement matches nothing — implicit deny.

**Grant and revoke take effect on the next token refresh**, not instantly.

## One string is four things

The username becomes the user's **S3 prefix**, the value of the **`username` principal tag**, and the
user's **Glue database name**.

- An IAM `RoleSessionName`/tag value allows at most 64 chars from `a-z A-Z 0-9 = , . @ - _`.
- Signup additionally enforces `^[a-z][a-z0-9_]{2,62}$` in the **pre-signup** trigger — a
  catalog-safe identifier, so the Glue database name is legal.
- **Case-insensitivity is immutable after pool creation**, so `Alice` and `alice` must never become
  two distinct users and two distinct S3 prefixes.

## The membership slots are effectively permanent

Adding custom attributes to an existing pool is an in-place `AddCustomAttributes`, **not** a pool
replacement — but they can never be modified or removed afterwards. **Raise
`max_shared_memberships`, never lower it.** Only the privileged orchestrator role writes these, via
`AdminUpdateUserAttributes`.

## Callback URLs: one per client, and they did not always

Two clients remain, each with exactly one callback and one sign-out URL: the portal server's,
built from the deployed origin, and local development's, built from `dev_origin`
(`http://localhost:5173`). The public SPA client and its list retired with SPEC-262, when the browser
stopped holding tokens.

The public client's list once carried the container and CloudFront together through a cutover,
because **an app client naming only one of them makes the other an origin that cannot complete a
sign-in**, and it used `distinct()` because Cognito **rejects** a duplicated URL rather than
deduplicating it. A future client with more than one entry has the same two traps.

## Managed Login v2, and the branding CI has to add

`managed_login_version = 2` serves the modern Managed Login UI. **The classic Hosted UI did not
reliably complete the OAuth redirect after a self-service signup email-code confirmation** — the user
landed confirmed-but-not-signed-in with no redirect back to the app. Managed Login carries
signup → confirm → auto-sign-in → redirect through to the callback.

**Managed Login also requires a branding style per app client, or the v2 pages fail to render.** The
native `aws_cognito_managed_login_branding` resource exists only in the AWS provider's 6.x line, and
this repo is pinned to `~> 5.0` — which **does** support `managed_login_version` but **not** the
branding resource. Rather than take a provider major bump for one resource, the Cognito-provided
default branding is ensured imperatively in CI after apply (`deploy-infra.yml`) — the same "Terraform
owns infra, CI owns imperative deploy steps" split used for Lambda code. Revisit when the provider
moves to 6.x.

## The two triggers

- **`pre-signup`** enforces the username rule server-side. Logs only — it makes no AWS API call.
- **`post-confirmation`** creates the user's Glue database (named exactly as the username) and
  Lake-Formation-grants the shared portal role on it, so its role carries Glue + LF on top of logs.

Both reach into `cpcommon` for **one import — `observability`** — and emit under
`service="auth"`. **None of the six variables `cpcommon.config` requires is set on either**,
deliberately: `observability` never reaches `config`. That was once enforced by a crash at import;
config resolves on **first access** now, so the guard is no longer "does the import crash" but "does
any branch read one" — `test_layer_import_safety.py` scans each function's whole source for a
`cpcommon` import as well as running it.

~~`ignore_changes` covers `layers` as well as the code.~~ **Superseded by SPEC-213:** the function is container-packaged, declares no `layers`, and `ignore_changes` names `image_uri`. The lesson below is why the field was there and is kept for it. It was **missing** on `pre-signup` while the
code already imported `cpcommon`, so an apply landing after a deploy stripped the layer back off and
**re-broke signup**.

## Both triggers are woken once a day

`keep-warm.tf` invokes both triggers once a day. An image function idle for weeks goes Inactive and
Lambda rejects the invoke that wakes it, and Cognito does not retry that failure: pre-signup would
fail on Cognito's own page, and post-confirmation would confirm the user with no database and no
record that provisioning was skipped, because the handler never ran. The payload,
`keep-warm.json`, is a no-op by each handler's existing rules, and both handlers' tests run it.
`lambdas/test_keep_warm.py` holds every trigger in `lambda_config` to a target and a permission.
Reasoning: `docs/decisions/infrastructure/the-functions-a-user-reaches-first-are-woken-daily.md`.

## The propagation guards

Three `time_sleep` resources absorb IAM's eventual consistency on the applies that grant a permission
and then use it. The one in `lambda.tf` is the instructive one: **every resource that needs a
freshly-granted permission must depend on it** — the exec role for `iam:CreateRole`, the log group
for `logs:CreateLogGroup` — **not just the function**, or those calls race the propagation and hit
`AccessDenied`.

## `logs_queue_arn` is a constructed string, not `module.observability`'s output

`module.observability` consumes this module's `user_pool_id`, so a real reference here would be a
**module cycle**.

Similarly, `post_confirmation_exec_role_arn` is exported as **informational only**:
`module.analytics` adds this role as a Lake Formation admin via a **constructed ARN from the root
locals**, not this output, so the value is known at plan time. An unknown here **broke the
`compact()` in the LF admins list and silently dropped the grant**.
