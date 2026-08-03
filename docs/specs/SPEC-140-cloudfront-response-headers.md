# Spec: CloudFront Response Headers Policy

**ID:** SPEC-140
**Status:** Draft
**Last Updated:** 2026-08-03
**Depends On:** SPEC-138 (security scanning — produced the findings), SPEC-139 (rendered-plan IaC scan)

## Overview

The portal is served from CloudFront with **no security response headers at all**. A browser loading
the app today is told nothing about what it may execute, where it may connect, whether it may be
framed, or whether it must stay on HTTPS. Two independent scanners report this as the same gap:
Checkov `CKV2_AWS_32` against the IaC, and the first live OWASP ZAP baseline against the deployed
origin (2026-08-03), where it accounts for **every Medium finding and six of eight Lows**.

This spec attaches a CloudFront response headers policy to the distribution so the SPA ships a
Content-Security-Policy, HSTS, anti-clickjacking, MIME-sniffing, Permissions-Policy and
cross-origin isolation headers, and stops leaking its origin's `server: AmazonS3` banner. The
user-visible behaviour of the portal does not change — the point is that the browser starts
enforcing what the app was already supposed to be doing.

The risk here is not the headers; it is a CSP that is wrong in a way no test catches and that breaks
the Query editor or an AWS call **in production only**. The phases below are built around retiring
that risk before enforcement, not around writing the policy.

## Scope

### In Scope

- An `aws_cloudfront_response_headers_policy` in `infra/modules/app/`, attached to the distribution's
  `default_cache_behavior`.
- CSP, HSTS, `X-Frame-Options` + `frame-ancestors`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, COOP and CORP.
- Removal of the origin's `server` and `x-amz-server-side-encryption` response headers.
- **Deploy-role IAM expansion** for the new resource type (`cloudfront:*ResponseHeadersPolicy`) —
  in-scope work per the CLAUDE.md infra rule, not an afterthought.
- A CSP built from Terraform **variables** (region, bucket names, Cognito domain), never hardcoded
  literals.
- A `Content-Security-Policy-Report-Only` stage, exercised against the deployed app before any
  enforcing header ships.
- Re-running ZAP to confirm the findings actually cleared.

### Out of Scope

- **`Cache-Control` and the cache-behavior split.** The SPA shell is currently served with no
  `Cache-Control` under `Managed-CachingOptimized`, so a deploy can be shadowed by a stale
  `index.html` for up to 24h. That is a real correctness bug and it produces three of ZAP's
  Informational findings — but it is a *cache policy* change (a second behavior splitting hashed
  `/assets/*` from `index.html`), not a headers-policy change, and conflating them risks breaking
  asset caching while chasing header hygiene. Separate spec.
- **`Cross-Origin-Embedder-Policy`.** Deliberately not set — see FR-006.
- **CloudFront WAF, access logging, custom domain / TLS cert, geo restriction** — the other Checkov
  CloudFront rows, all previously dispositioned `defer` or `accept` in `docs/security-baseline.md`.
- **The other three Checkov FIX items** (S3 versioning, multipart-abort lifecycle, Athena workgroup
  enforcement). Related follow-ups from the same baseline, but different resources and no shared code.
- **Flipping `GATE_CHECKOV` or `GATE_ZAP` to `block`.** Gate policy is its own change; SPEC-139
  established that Checkov must be gated by check ID rather than in bulk.
- **Nonce- or hash-based CSP.** Requires build-pipeline changes to inject per-response nonces, which
  a static S3 origin cannot do without Lambda@Edge. `'unsafe-inline'` for styles is accepted here
  and justified in FR-002.
- Anything behind Cognito. ZAP is unauthenticated and reaches only the pre-login shell.

---

## Functional Requirements

### FR-001: Response headers policy exists and is attached

#### Description

A single `aws_cloudfront_response_headers_policy` resource is defined in `infra/modules/app/` and
referenced by the distribution's `default_cache_behavior` via `response_headers_policy_id`.

#### Acceptance Criteria

- [ ] `tofu -chdir=infra validate` passes.
- [ ] `tofu -chdir=infra plan` shows exactly one new `aws_cloudfront_response_headers_policy` and an
      in-place update to `aws_cloudfront_distribution.portal`.
- [ ] The policy name is derived from `var.project_name`, matching the naming of the existing OAC.
- [ ] After apply, `curl -sSI https://<cloudfront_domain>/` returns every header listed in FR-002
      through FR-006.
- [ ] The same headers are present on a hashed asset (`/assets/*.js`) and on the SPA-fallback route
      (a deep link such as `/files`, which returns `index.html` via `custom_error_response`).

### FR-002: Content-Security-Policy

#### Description

The policy sets a CSP that permits exactly what the app needs and nothing more. Directive values are
rendered from Terraform variables so that a region, bucket or Cognito-domain change flows through
without editing a string literal.

The app's real requirements, established by reading the source rather than assumed:

| Need | Source |
|---|---|
| AWS API calls to S3, Cognito IdP, Cognito Identity, Athena, Glue, SQS | `apps/portal/.env.example`, `src/lib/` clients |
| Monaco web worker | `SqlEditor.tsx:4` — Vite `?worker` import, same-origin chunk |
| Monaco runtime-injected `<style>` elements | `monaco-editor` behaviour |
| Cognito Hosted UI (Managed Login v2) | top-level navigation, **not** a subresource or form post |

#### Acceptance Criteria

- [ ] `default-src 'self'`.
- [ ] `connect-src` lists the S3, `cognito-idp`, `cognito-identity`, `athena`, `glue` and `sqs`
      endpoints for the configured region, each interpolated from a Terraform variable — the
      rendered policy contains **no** hardcoded region string, account id or bucket name.
- [ ] `script-src 'self'` — no `'unsafe-inline'`, no `'unsafe-eval'`.
- [ ] `style-src 'self' 'unsafe-inline'`, with an inline comment naming Monaco as the reason.
- [ ] `worker-src` permits the Monaco worker and is verified against the **built** app, not the dev
      server.
- [ ] `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`, `form-action 'self'`.
- [ ] Loading the built app with this CSP enforced produces **zero** CSP violations in the browser
      console across: sign-in, `/files` (list, upload, download), `/query` (editor mount, run a
      statement), `/data-quality`, `/notifications`, `/help`.

### FR-003: Report-Only before enforcement

#### Description

The CSP ships first as `Content-Security-Policy-Report-Only`, is exercised against the **deployed**
app, and is only then promoted to the enforcing header. There is no backend and therefore no
`report-uri` collector; verification is manual browser-console inspection, and the spec says so
rather than implying automated collection.

#### Acceptance Criteria

- [ ] A deploy exists in which the distribution returns `Content-Security-Policy-Report-Only` and no
      enforcing `Content-Security-Policy`.
- [ ] Every route in FR-002's list is exercised by hand against that deploy, and the observed console
      violations (or their absence) are recorded in the delivery doc.
- [ ] Promotion to the enforcing header is a **separate commit** from the one that introduced
      Report-Only, so the enforcing change can be reverted without reverting the policy.
- [ ] If a violation is found, the CSP is corrected and Report-Only is re-verified before promotion —
      a violation is never resolved by widening to `'unsafe-inline'` for scripts.

### FR-004: Transport and framing headers

#### Acceptance Criteria

- [ ] `Strict-Transport-Security: max-age=31536000; includeSubDomains` — `preload` is **not** set
      (the domain is a shared `*.cloudfront.net`; preloading it is not ours to request).
      **This fails Checkov `CKV_AWS_259`, accepted deliberately.** `preload` is the *only* thing
      that check objects to — max-age, `include_subdomains` and `override` all satisfy it (verified
      against checkov 3.3.9). Emitting `preload` without submitting to hstspreload.org would make
      the header assert an intent we do not have, on a domain a custom domain will replace. Revisit
      when that custom domain lands.
- [ ] `X-Frame-Options: DENY`, alongside `frame-ancestors 'none'` from FR-002.
- [ ] `X-Content-Type-Options: nosniff`.
- [ ] `Referrer-Policy: strict-origin-when-cross-origin`.

### FR-005: Permissions-Policy

#### Acceptance Criteria

- [ ] A `Permissions-Policy` header is present as a custom header (CloudFront has no first-class
      field for it).
- [ ] Camera, microphone, geolocation, USB, payment and interest-cohort are all disabled — the portal
      uses none of them.

### FR-006: Cross-origin isolation headers

#### Description

`Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` are set.
`Cross-Origin-Embedder-Policy` is **deliberately not set**: `require-corp` exists to enable
cross-origin isolation, which this app makes no use of (no `SharedArrayBuffer`, no high-resolution
timers), while carrying a real risk of breaking subresource loads to buy a scanner Low. This is a
decision, not an omission, and the ZAP finding stays open with this reasoning attached.

#### Acceptance Criteria

- [ ] `Cross-Origin-Opener-Policy: same-origin`.
- [ ] `Cross-Origin-Resource-Policy: same-origin`.
- [ ] No `Cross-Origin-Embedder-Policy` header is emitted.
- [ ] The reasoning above appears as a comment in the Terraform, so the next reader does not "fix"
      the gap by adding it.

### FR-007: Strip origin-identifying headers

#### Description

The S3 origin's `server: AmazonS3` banner and `x-amz-server-side-encryption` reach the viewer today
(confirmed by `curl` on 2026-08-03). Both are removed via the policy's `remove_headers_config`.

#### Acceptance Criteria

- [ ] `curl -sSI https://<cloudfront_domain>/` shows no `server: AmazonS3`.
- [ ] The same response shows no `x-amz-server-side-encryption`.
- [ ] Assets still load — removal is verified against a JS asset, not only the shell.

### FR-008: Deploy-role IAM

#### Description

`aws_cloudfront_response_headers_policy` is a **new resource type** for this repo. The deploy role
currently grants `cloudfront:*Distribution`, `*OriginAccessControl` and `Get/ListCachePolicy` — and
**no** `*ResponseHeadersPolicy` action at all (`infra/modules/base/policies/github-actions-deploy.json.tftpl:17-31`).
Without this FR the apply fails on the first plan.

Per CLAUDE.md, adding a new resource type trips the recurring IAM traps: self-grant timing (the role
must be able to grant itself before it can use the grant) and the **refresh deadlock** — tightening
or widening one of the role's own grants can require the very permission the pending change
restores, failing plan, apply *and* revert alike.

#### Acceptance Criteria

- [ ] `github-actions-deploy.json.tftpl` gains `cloudfront:CreateResponseHeadersPolicy`,
      `GetResponseHeadersPolicy`, `UpdateResponseHeadersPolicy`, `DeleteResponseHeadersPolicy` and
      `ListResponseHeadersPolicies`.
- [ ] The IAM change is applied **in its own run, before** the run that creates the policy — a single
      run that both grants and uses the permission is the self-grant-timing trap.
- [ ] `Deploy Infrastructure` completes green on `main` without needing the `skip_refresh` lever. If
      the lever *is* needed, a normal run follows it, per the Key Decisions entry.
- [ ] The rendered-plan Checkov scan (SPEC-139) still reports zero `Resource: "*"` on
      `portal-role-permissions`, and its IAM finding count does not rise above the permanent 2.

### FR-009: The findings actually cleared

#### Description

The spec is not done because the headers exist; it is done because the two scanners that reported
the gap stop reporting it.

#### Acceptance Criteria

- [ ] Checkov no longer reports `CKV2_AWS_32` against the distribution.
- [ ] The only **new** Checkov finding introduced by the policy is `CKV_AWS_259` (the accepted
      `preload` decision in FR-004), recorded in `docs/security-baseline.md`. Any other new check
      failing on `aws_cloudfront_response_headers_policy.portal` is a real regression, not noise —
      note that the total failure count is a poor signal here, since CKV2_AWS_32 clearing and
      CKV_AWS_259 appearing cancelled out at 305.
- [ ] A dispatched `Security` run shows ZAP with **zero Medium** findings and **zero Low** findings
      other than the two accepted in `docs/security-baseline.md` (COEP, Timestamp Disclosure).
- [ ] `FAIL-NEW` remains 0 and no **new** alert class appears that was not in the 2026-08-03 baseline.
- [ ] `docs/security-baseline.md` is updated with the post-fix counts.

---

## Interface Contract

No application interface changes. The entire surface is the HTTP response, which FR-001 through
FR-007 specify directly. The expected shell response after this spec:

```
HTTP/2 200
content-type: text/html
content-security-policy: default-src 'self'; script-src 'self'; …
strict-transport-security: max-age=31536000; includeSubDomains
x-frame-options: DENY
x-content-type-options: nosniff
referrer-policy: strict-origin-when-cross-origin
permissions-policy: camera=(), microphone=(), geolocation=(), …
cross-origin-opener-policy: same-origin
cross-origin-resource-policy: same-origin
# and NOT: server, x-amz-server-side-encryption, cross-origin-embedder-policy
```

## Environment Variables

None. The CSP is rendered from existing Terraform variables in `infra/modules/app/`; no new `VITE_*`
variable is introduced, and nothing is added to `.env.example`.

## File & Folder Structure

```
infra/
├── modules/
│   ├── app/
│   │   ├── cloudfront.tf              # + response headers policy, + attachment
│   │   └── variables.tf               # + any variable the CSP needs that isn't already passed
│   └── base/
│       └── policies/
│           └── github-actions-deploy.json.tftpl   # + cloudfront:*ResponseHeadersPolicy
docs/
├── security-baseline.md               # post-fix counts (FR-009)
└── spec-delivery/
    └── SPEC-140-cloudfront-response-headers.md
```

## Implementation Phases

### Phase 1: Deploy-role IAM, applied on its own

- Add the five `cloudfront:*ResponseHeadersPolicy` actions to `github-actions-deploy.json.tftpl`.
- Merge and apply **before** any policy resource exists, so the grant is in place and settled before
  something needs it.
- Confirm `Deploy Infrastructure` is green on `main`; note whether `skip_refresh` was needed.

### Phase 2: The policy, Report-Only

- Add `aws_cloudfront_response_headers_policy` with the full FR-004 → FR-007 header set, and the CSP
  as **Report-Only only**.
- Attach it to `default_cache_behavior`.
- Build the CSP from Terraform variables; add the FR-006 comment explaining the COEP decision.

### Phase 3: Verify Report-Only against the deployed app

- Exercise sign-in, `/files`, `/query`, `/data-quality`, `/notifications`, `/help` in a real browser.
- Record every console violation, or record that there were none.
- Correct the CSP and re-verify if anything fires — never by widening `script-src`.

### Phase 4: Promote to enforcing

- Move the verified CSP from the Report-Only field to the enforcing one, as its own commit.
- Re-check the FR-002 route list with the CSP enforced.

### Phase 5: Prove the findings cleared

- Dispatch `Security`; confirm ZAP against FR-009's thresholds.
- Confirm Checkov no longer reports `CKV2_AWS_32`.
- Update `docs/security-baseline.md`; write the delivery doc.
