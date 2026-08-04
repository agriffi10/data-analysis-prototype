# Completed Spec — SPEC-140: CloudFront Response Headers Policy

## What was completed?

- `aws_cloudfront_response_headers_policy.portal` in `infra/modules/app/cloudfront.tf`, attached to
  the distribution's `default_cache_behavior`. Ships an **enforcing** CSP, HSTS, `X-Frame-Options`,
  `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP and CORP, and strips `Server` and
  `x-amz-server-side-encryption`.
- `modules/app` gained `aws_region`, `user_space_bucket_name`, `shared_space_bucket_name` (and
  `cognito_hosted_ui_domain` as of the 2026-08-04 correction below) — passed as **constructed
  strings from root locals**, not module outputs: `modules/app` is upstream of `base → data`, so a
  module reference would be a dependency cycle.
- Deploy role gained the five `cloudfront:*ResponseHeadersPolicy` actions, applied in **its own run**
  ahead of the resource (self-grant-timing trap).

Four PRs, one per phase: #329 (IAM), #330 (policy + report-only), #331 (reporting endpoint),
#333 (promote to enforcing).

### Deliberate deviations

- **COEP not set.** `require-corp` buys cross-origin isolation this app cannot use (no
  `SharedArrayBuffer`, no high-resolution timers) at real risk to subresource loads. ZAP 90004 stays
  open by decision; reasoning is a comment in the Terraform so it is not "fixed" later.
- **`preload` not set**, which fails Checkov **CKV_AWS_259** — the only thing that check objects to.
  Emitting it would assert an intent to submit to hstspreload.org that we do not have, on a
  shared-suffix domain a custom domain will replace. Accepted, not silenced.
- **`style-src 'unsafe-inline'` retained**, which ZAP grades as a new **Medium**. Monaco injects
  `<style>` at runtime; removing it needs per-response nonces, impossible on a static S3+CloudFront
  origin without Lambda@Edge. `script-src` carries no such allowance, which is the one that matters.
  FR-009 was amended to name this rather than leave the criterion quietly unmet.

## What changed from earlier specs?

- **SPEC-138's ZAP baseline row** is superseded — `docs/security-baseline.md` now carries post-fix
  counts alongside the 2026-08-03 originals.
- `security.yml`'s ZAP step was fixed en route (#327): `cmd_options` passed a second `-J`, which
  redirected the JSON away from the filename the action reads back, failing the job **outside** the
  `fail_action` guard. The scan itself had been clean the whole time.

## Verification

`tofu validate` + `fmt` locally; Checkov 3.3.9 run locally against `modules/app` to confirm
`CKV_AWS_259` is the **only** check failing on the new resource. The CSP was verified against the
**production build served under the enforcing policy** via a same-origin page probe — not CDP
evaluation, which bypasses page CSP and initially produced a false pass. That harness caught the
`fonts.googleapis.com` omission (`src/index.css:1` `@import`s Inter; Vite leaves remote `@import`s
in built CSS) that would otherwise have stripped the typeface site-wide.

Report-only earned its keep twice: the fonts omission, and the discovery that **Safari will not
evaluate a report-only policy naming no reporting endpoint** — it logs "the policy will have no
effect" and applies nothing, so a verification pass reports zero violations whether or not any
occurred. Chrome and Firefox honour report-only without one, which is exactly why a Chromium harness
cannot surface it. Fixed in #331; the signed-in pass was then clean across every route.

**Confirmed after enforcement (2026-08-03):** `/query` exercised signed-in against the live
enforcing policy — Monaco mounts and statements run. That closes the one gap the report-only pass
structurally could not cover, since `frame-ancestors` and `upgrade-insecure-requests` are inert in
report-only mode and were live for the first time under enforcement.

**Results:** ZAP 20 alerts → 13. Every Medium and six of eight Lows cleared. Three findings remain
by decision — COEP, timestamp disclosure (bundle noise), and the new `style-src unsafe-inline`
Medium. Checkov `CKV2_AWS_32` cleared; `CKV_AWS_259` accepted. Deploy-role IAM findings held at the
permanent 2 throughout.

**Not covered:** ZAP is unauthenticated and reaches only the pre-login shell. Nothing here is
evidence about pages behind Cognito.

## Correction (2026-08-04) — the enforcing CSP broke fresh sign-in

`connect-src` never listed the Cognito **Hosted UI domain**
(`<prefix>.auth.<region>.amazoncognito.com`). The spec's requirements table classified the Hosted UI
as "top-level navigation, not a subresource" — true of the redirect *to* Managed Login, false of the
return leg: Amplify exchanges the authorization code by `fetch`ing
`https://<hosted-ui-domain>/oauth2/token`
(`@aws-amplify/auth/.../oauth/completeOAuthFlow.mjs:53`), a host that is **not** `cognito-idp`.

Under enforcement the exchange was blocked, so the returning `?code=` was never redeemed:
`getCurrentUser()` kept failing, `AuthProvider` stayed `unauthenticated`, every auth-gated route
bounced to the landing page, and clicking Sign in again round-tripped through a live Cognito session
cookie and came back with another unredeemable code — a click that looked like it did nothing.

**Why both gates missed it.** Report-only never blocks, so the pre-promotion pass proved only that
sign-in still worked while the policy was inert, and the violation it raised went to a reporting
endpoint nobody read. The post-enforcement pass (`/query`, 2026-08-03) was run **from an existing
session** — and token *refresh* goes through `cognito-idp` (`refreshAuthTokens.mjs`), which was
allowed all along. So a signed-in session kept working indefinitely and only a **fresh** sign-in was
broken; neither check performed one against the enforcing policy.

**Fix:** `var.cognito_hosted_ui_domain`, derived in root locals the same cycle-free way as the bucket
names, added to `local.csp_connect_src`. Root is the single source of the prefix default — the
**resolved** `local.cognito_domain_prefix` is passed into `modules/auth` rather than the raw
variable, so the module's ternary can no longer drift from the CSP's. The code exchange is the only
fetch to that host: both redirects are navigations, and refresh + `RevokeToken` go to `cognito-idp`.

**Guard:** a `precondition` on the `cognito_domain` output asserts
`module.auth.user_pool_domain == local.cognito_hosted_ui_domain`. The CSP allows one string and the
app fetches another (`VITE_COGNITO_DOMAIN`, a hand-maintained Actions variable) — nothing connected
them. A precondition fails the plan; a `check` block would only warn, which is exactly how this class
of bug survives CI.

**The rule this leaves behind:** enumerate `connect-src` from the **hosts the app fetches**, not the
AWS services it uses, and verify auth changes with a **signed-out** browser session.

**Discharged 2026-08-04:** applied on `main` (`a92a83a`); the live header carries
`https://dat-prod-portal.auth.us-east-1.amazoncognito.com`, and a signed-out sign-in from a clean
browser profile succeeded. The fix is confirmed by the flow itself, not by reading source.

**Still open — the CSP and the app get their domain from unlinked sources.** The precondition ties
`connect-src` to the *user pool*, but the app fetches whatever `VITE_COGNITO_DOMAIN` says, and that
is a hand-maintained GitHub Actions variable (`deploy-app.yml`, populated by hand from
`tofu output cognito_domain`). Hand-edit it and this outage returns with nothing failing. Closing it
means sourcing the build var from the Terraform output rather than by hand.
