# `api` — the HTTP API and its function

One HTTP API, one `$default` route, one `AWS_PROXY` integration, one Lambda, reached through a
regional custom domain. **The route table lives in the code** — a per-route integration would put it
in two places, and authorization resolves a principal once, before dispatch.

| File | Holds |
|---|---|
| `apigateway.tf` | the API, its CORS block, the integration, stage, domain and mapping |
| `lambda.tf` | the function, its role, log group and placeholder package |
| `dns.tf` | the A-alias record |
| `outputs.tf` | ids and ARNs the root and live checks consume |
| `variables.tf` | the module interface, including the **provider block** |
| `policies/` | the API trust policy and its execution-policy template |

Code: `lambdas/api/`.

## `disable_execute_api_endpoint` is on

Left enabled, the API also answers on `https://{api-id}.execute-api.{region}.amazonaws.com` — a
second front door **outside the CSP, outside the alias record**, and one that makes a CORS preflight
check ambiguous about which host it actually proved.

## CORS belongs to the API alone

AWS **ignores CORS headers returned by the integration**, so a header emitted in the handler would
not reach the browser at all. But the rule stands on its own ground: two places able to answer the
same question is how they come to disagree, and the one that wins here is not the one a reader is
looking at.

- **Exact origins, never `*`.** Both are real for the length of the arc — the container is where
  ported features are proved, CloudFront is the rollback — and **a list naming one of them leaves
  the other an app that loads and can do nothing**. `app_url` is omitted while empty, the same
  ternary the Cognito callback list and both bucket CORS rules use. It is removed at the cutover.
- **`x-request-id` must be in `allow_headers`.** The browser's API client mints it on every call, and
  **a header the preflight does not admit fails the preflight** — so the request never reaches the
  API and the browser reports a generic network error, indistinguishable from the API being down.
  This list is asserted against the client's headers rather than inferred from the app working.
- **`allow_credentials = false`, and not merely unset.** The arc sends the ID token as an
  `Authorization` bearer, which is not a credential in the CORS sense, so `true` would grant a
  capability nothing uses while making the exact-origin echo load-bearing for a browser rule that no
  longer applies. It is also the half of the credentials/`*` pairing that every browser rejects
  **while applying green**.
- **`max_age = 600`.** Every request carries `Authorization`, so **every request is preflighted** —
  the cache duration is a latency decision rather than a nicety.

**`$default` matches `OPTIONS`.** API Gateway's own CORS responder therefore never sees a preflight,
and the router must answer one **before authentication**. Only a browser enforces CORS, so `curl`
cannot see this failing.

## Two timeouts, and the order is the point

```
function (29s)  <  integration (30s, API Gateway's hard ceiling)
```

The ceiling is **not raisable**. The function must give up **first**, so a slow request returns the
handler's own error rather than a **504 from the integration while the invocation keeps running and
keeps billing**. Set equal, the two expire at the same instant and which one answers is a race.

The browser client's timeout sits **above** the function's for the same reason: the server gives up
first, so an abort always means a dead connection.

## The function is not in the VPC, deliberately

The VPC exists for the container. Attaching this would need an interface endpoint per service the API
later calls and would put ENI attachment on the cold-start path — **and after the arc's provider swap
the token-verification host is a third party with no AWS endpoint at all**, so a function inside
those subnets would stop verifying with no code change to blame.

## The provider block — five fields, and nothing else

The verifier reads these five and nothing else about who issues its tokens. That is the whole point:
the target environment swaps the identity provider by **changing values rather than rewriting an
authorization path**. Every one is computed at root, so there is exactly one wiring site.

**`oidc_jwks_uri` is passed in whole and treated as opaque.** Cognito happens to publish under the
issuer and other providers do not, so a URL built from `oidc_issuer` inside this module would bake in
the provider assumption the block exists to remove.

**The client secret, redirect URI and post-logout URI are deliberately absent.** They belong to a
server-side login flow this API does not perform, and a required variable that reaches production
unset fails a long way from its cause.

**Each field carries a `validation` rather than relying on having no default.** An unset repo variable
renders as the **empty string**, which satisfies a required variable *and* overrides a default — so
"no default" guards nothing on its own.

`oidc_required_claims` has three validation layers, each measured rather than assumed:

- `jsondecode` alone accepts a bare scalar, so `42` and `"id"` would reach the function and fail in
  the verifier's parse instead of here.
- `tomap` rejects those and a list.
- `keys` is what rejects the literal `null`, which `tomap` accepts and which **plans clean end to
  end** — and a null arriving is exactly the "token-type check never runs" outcome.

An empty **object** still passes, which is correct: a provider asserting no such claim is not
misconfigured. An empty **string** is what an unset variable looks like, and is not.

## The identity layer — three values, none defaulted

A defaulted role ARN fails a long way from its cause. **A defaulted slot count silently drops every
shared space a user is in** — which presents as the membership propagation delay the product already
documents, so nothing about the running system distinguishes it from correct behaviour.

`portal_role_arn` is the **existing** role, the same ARN the Identity Pool's role attachment names.
**No new role is created**: the user-space bucket policy's hand-maintained allowlist already names
this one, and `aws:PrincipalArn` resolves an assumed-role request to the role's IAM ARN, so assuming
the same role keeps that entry valid.

`principal_tag_key` agreement with the Identity Pool's map is **asserted by test rather than made
structural** — the map and two of the portal role's permission templates hard-code the literal, and
threading a variable through them would edit templates this arc must leave byte-identical.

## Small shapes that are load-bearing

- **The role policy is inline, not managed-plus-attachment.** The deploy role holds
  `iam:PutRolePolicy` on this role and holds neither `iam:AttachRolePolicy` nor a scoped
  `iam:CreatePolicy` — so the managed shape is refused at apply, and **the refusal reads as a missing
  permission rather than as a wrong shape**.
- **`api_execution_role_arn` is a real reference, not a constructed string.** IAM validates a trust
  policy's `Principal` and refuses an ARN naming a role that does not exist yet, so **the dependency
  edge is what makes a from-scratch apply order the two correctly**.
- **`api_certificate_arn` is fed from the certificate *validation* resource**, not the certificate.
  Both carry the same ARN, but only the validation creates the edge that stops a clean rebuild
  attaching a `PENDING_VALIDATION` certificate.
- **The Route 53 zone id is a variable, never a lookup.** `data "aws_route53_zone"` needs
  `route53:ListHostedZonesByName`, which the deploy role does not hold, and the failure would read as
  a mysterious `AccessDenied` on the first plan.
- **The domain is `REGIONAL`**, with a certificate in this module's own region. The us-east-1-only
  certificate rule belongs to CloudFront and does not apply here.
- **The API mapping is at the empty path**, so what reaches the handler is already the path the router
  expects — no stage prefix to strip, and no disagreement between the two hostnames about what a
  request's path is.
- **HTTP APIs need no account-level CloudWatch Logs role.** A reader arriving from REST APIs will look
  for one and **must not add it**: the delivery permissions live on the deploy role, not on an
  `apigateway.amazonaws.com` account setting.
- **The invoke permission is scoped to this API's executions.** `"*"` would let any API Gateway in the
  account invoke the function — a grant nobody would write on purpose, and one that reads as
  boilerplate in a diff.
- **No `api_origin`/`api_host` output.** Both are built at **root** and passed down; re-exporting them
  would make a module output the source of a value three other modules consume, which is the
  unknown-at-plan shape the root-locals rule exists to avoid.
