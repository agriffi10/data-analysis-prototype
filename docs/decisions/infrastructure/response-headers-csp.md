---
type: Decision
title: "Response headers / CSP (SPEC-140)"
description: "nginx serves the only CSP and security headers. Enumerate `connect-src` from the hosts the app fetches, prove enforcement with a positive `connect-src` violation plus a same-origin negative control, and diff scanner findings per check ID, never by count."
---

> **Superseded in part by SPEC-194 (2026-08-27), on two points.** *Where the policy lives:* both
> CSP locals are at **root** now, not in `modules/app` — a check at root cannot read a local inside
> a module, and that module is deleted when the distribution is retired. The four-input shape
> described below is gone; `connect-src` is assembled at root from the same variables plus the API
> origin, and the module takes the assembled policy as an input. *Who emits it:* the container
> serves the same policy from nginx, with `connect-src` supplied by the task definition and every
> other directive baked in the image. The rules below are unchanged and inherited — enumerate from
> the hosts the app **fetches**, verify with a positive violation event and a negative control (see
> the correction below), diff per alert ID. HSTS `preload` is dropped for the container's domain,
> re-decided.

> **Superseded and CORRECTED by SPEC-202 (2026-09-02), on two further points.** *Where it runs:* the
> distribution, its response-headers policy, its OAC and `modules/app` are destroyed. nginx serves
> the only policy now, and `CKV_AWS_259` — the check the `preload` decision was argued against —
> came off `.github/checkov-enforced.txt` in the same change, because an enforced check ID matching
> no finding is a hard error.
>
> *How to verify one, which is the part that was wrong rather than merely stale.* This entry
> prescribed "a same-origin page script plus a negative control, because CDP evaluation bypasses
> page CSP". What was measured to reach that rule was **`script-src`** (`new Function` reported as
> allowed) — the debugger's script-evaluation exemption — and the prescription generalised from it
> is **unsatisfiable** against a policy carrying `script-src 'self'`: an inline script is blocked and
> an Elements-panel `<script>` is parser-marked non-executable, so the arc's one enforcement check
> had no runnable method and its failure read as a broken snippet rather than as a finding. The
> corrected rule, measured 2026-08-31 against the deployed container: **CDP evaluation is exempt
> from `script-src`, NOT from `connect-src`.** So assert a **positive** `securitypolicyviolation`
> event with `effectiveDirective: "connect-src"` and `disposition: "enforce"`, from an evaluated
> `fetch` to a host the policy excludes, **plus a same-origin negative control in the same run** —
> without the control, a blocked request and a broken network are the same observation.


One `aws_cloudfront_response_headers_policy` on the distribution's default cache behavior carries the browser-facing security posture — **enforcing** CSP, HSTS (`includeSubDomains`, **no `preload`**), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP — and strips `Server` and `x-amz-server-side-encryption`. Four decisions carry the weight. **(1) The CSP is assembled from variables, never literals.** `connect-src` *is* the app's network surface — there is no backend, so anything missing from it is a broken feature — and it is built from `var.aws_region`, the two bucket names and the Hosted UI domain, passed as **constructed strings from root locals** because `modules/app` is upstream of `base → data` and a module reference would be a dependency cycle. A hardcoded region or bucket would have to be hunted down during the client-environment transition. (**Correction 2026-08-04:** the Hosted UI domain was missing from the shipped list, and it broke sign-in outright once the policy went enforcing — Amplify's authorization-code exchange POSTs to `https://<hosted-ui-domain>/oauth2/token`, which is **not** `cognito-idp`, so the returning `?code=` was never redeemed and the app sat signed-out over a live Cognito session. Enumerate `connect-src` from the **hosts the app actually fetches**, not from the AWS services it uses.) **(2) Report-only first is not ceremony.** A CSP wrong about `worker-src` or `style-src` breaks the Monaco editor in production and nowhere else, because no unit test observes a CSP. It earned its keep twice: it caught that `src/index.css:1` `@import`s Inter from `fonts.googleapis.com` (Vite leaves remote `@import`s in built CSS, so an enforcing CSP would have stripped the typeface site-wide), and it exposed that **Safari refuses to evaluate a report-only policy naming no reporting endpoint** — logging "the policy will have no effect" and applying nothing, so a verification pass reports zero violations whether or not any occurred. Chrome and Firefox honour report-only without one, which is exactly why a Chromium-based harness cannot surface it; the same reason CDP `Runtime.evaluate` is useless for CSP probing, since it bypasses page CSP entirely (it reported `new Function` as *allowed* under `script-src 'self'`). Verify a CSP with a **same-origin page script**, and always include a negative control that proves enforcement is live. (**Correction 2026-08-04:** report-only also has a blind spot the promotion to enforcing walked straight into. Report-only **never blocks**, so the sign-in pass that "reported no violations" succeeded *because* the policy was inert, and the one violation it did raise was reported to an endpoint nobody read. A report-only pass proves a flow still works; it proves nothing about whether the flow would survive enforcement. **Read the violation reports, or re-run the flow against the enforcing policy before calling it verified.**) **(3) Three findings are accepted, not silenced.** `Cross-Origin-Embedder-Policy` is absent because `require-corp` buys cross-origin isolation this app cannot use (no `SharedArrayBuffer`, no high-resolution timers) at real risk to subresource loads. `preload` is absent because it declares an intent to submit to hstspreload.org that we do not have, on a shared-suffix `*.cloudfront.net` name a custom domain will replace, and it is near-irreversible once granted — this **fails Checkov `CKV_AWS_259`, whose sole objection is that flag**. (**Update 2026-08-03:** `preload` was flipped on, clearing `CKV_AWS_259` — it is inert without an hstspreload.org submission, so **never submit this `*.cloudfront.net` domain** to hstspreload.org.) `style-src 'unsafe-inline'` stays because Monaco injects `<style>` at runtime — this is a **new ZAP Medium introduced by the fix itself**, and removing it needs per-response nonces, impossible on a static S3+CloudFront origin without Lambda@Edge; `script-src` carries no such allowance, which is the one that matters. **(4) A finding total is not a signal.** `CKV2_AWS_32` clearing and `CKV_AWS_259` appearing cancelled at 305, so the Checkov total looked untouched; ZAP went 20 → 13 while gaining a Medium. Diff **per check ID and per resource**, never by count. Full account: `docs/spec-delivery/SPEC-140-cloudfront-response-headers.md`.

## History

### 2026-09-02

- **Changed:** SPEC-202 destroyed the distribution, leaving nginx the only policy, and corrected the verification rule: CDP evaluation is exempt from `script-src`, not `connect-src`.

### 2026-08-27

- **Changed:** SPEC-194 moved both CSP locals to root, had the container serve the policy from nginx, and dropped HSTS `preload` for the container's domain.

### 2026-08-04

- **Changed:** The Hosted UI domain was added to `connect-src` after its absence broke sign-in; enumerate from the hosts the app fetches.
- **Changed:** Report-only was found to prove nothing about surviving enforcement; read the reports or re-run the flow against the enforcing policy.

### 2026-08-03

- **Settled:** SPEC-140.
- **Changed:** HSTS `preload` was flipped on to clear `CKV_AWS_259`, inert without an hstspreload.org submission.
