---
type: Decision
title: "Response headers / CSP: the request proxy stamps a per-request nonce (SPEC-140, SPEC-255)"
description: "The request proxy (`src/proxy.ts`) serves the only page CSP and the seven security headers. **The nonce goes in `script-src` only**: one in `style-src` switches off the `'unsafe-inline'` Monaco needs, and `'unsafe-eval'` is development only. **A request carrying a body skips the proxy**, because Next would wait for the whole body before answering anything, and gets `next.config.ts`'s lockdown floor. **The image's guard ahead of Next refuses every server-action request**, so an action added to the code passes `next dev` and is refused in production; `check:actions` fails the build on one. Enumerate `connect-src` from the hosts the app fetches, prove enforcement with a positive `connect-src` violation plus a same-origin control, and diff scanner findings per check ID, never by count."
---

The portal's browser-facing security posture is set by the Next.js server's request proxy,
`src/proxy.ts`, on every request that carries no body: an **enforcing** CSP, HSTS
(`includeSubDomains`, **no `preload`**), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
`Permissions-Policy`, COOP and CORP. Six decisions carry the weight.

**(1) A fresh nonce per page, in `script-src` only.** The proxy mints 16 random bytes per request and
builds the policy in `src/server/contentSecurityPolicy.ts`: `script-src 'self' 'nonce-<nonce>'`, with
`'unsafe-eval'` added only under `next dev`, because React's development build evaluates code and
production evaluates nothing. It sets the policy and `x-nonce` on the request too, overwriting
whatever the client sent under those names, so Next stamps the nonce on every script and stylesheet it
emits and the root layout puts it on `theme-init.js`. `style-src` keeps `'unsafe-inline'` and carries
**no** nonce, because a nonce in a directive switches its `'unsafe-inline'` off, and Monaco injects
`<style>` elements at runtime. A nonce exists only on a page rendered per request, so the root layout
opts every route into dynamic rendering, and no page may opt out: a prerendered page carries no nonce
and its scripts are blocked. The nonce-free half, the seven headers and the lockdown policy, lives in
`src/lib/securityHeaders.ts`, which imports no `server-only` because `next.config.ts` runs in plain
Node and imports it too.

**(2) A request carrying a body never reaches the proxy.** When the proxy matches such a request, Next
clones the body for it and then waits for the whole body before any page or handler answers, whatever
the proxy returns: a client declaring a gigabyte and sending one byte held every path, the health
probe included (measured by the SPEC-257 session, then on this server). So the proxy's matcher
excludes any request with a `Content-Length` or `Transfer-Encoding` header, and `next.config.ts`'s
`headers()` gives exactly those requests the seven headers and a lockdown policy (`default-src 'none';
base-uri 'none'; form-action 'none'; frame-ancestors 'none'`), since no page takes a body. The
residual is a body-less GET sent with `Content-Length: 0`: it gets the lockdown policy and a page that
cannot boot, which no browser does on its own. Responses Next answers before routing carry no policy
at all, which `the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are.md` records; since
SPEC-263 that class is only same-origin redirects, because a guard the image starts ahead of Next
(`apps/portal/server-guard.cjs`) answers a malformed percent-escape, a target that is not a path,
every WebSocket upgrade and every request Next would decode as a server action with 400, the seven
headers and the lockdown policy, from its own copy of `SECURITY_HEADERS` and `LOCKDOWN_POLICY`, which
`src/server/serverGuard.test.ts` holds equal to `src/lib/securityHeaders.ts`. It reads no body, so it
holds nothing. A server-action request is one carrying a `Next-Action` header, or a
`multipart/form-data` body, which Next decodes on a page path with no header at all; the portal
defines no action and sends no form body, so every one is a probe, and Next answered each by running
its action decoder and logging an error with a stack (an outside `POST /` did so on 2026-11-18). It
is refused on every path, `/api/` included, because Next resolves `/api/../` to the page at `/`, so a
path exemption would be a way round it. The guard runs only in the image, so an action added to the
code would work under `next dev` and be refused in production: `npm run check:actions` reads the
build's server reference manifest in CI and fails on any action it lists, and on a missing manifest.

**(3) `connect-src` is enumerated from the hosts the app actually fetches, not the AWS services it
uses.** The Hosted UI domain was once missing from it, and that broke sign-in outright when the policy
went enforcing: Amplify's authorization-code exchange POSTs to `https://<hosted-ui-domain>/oauth2/token`,
which is **not** `cognito-idp`, so the returning `?code=` was never redeemed and the app sat signed out
over a live Cognito session. Where the list comes from is
`connect-src-comes-from-the-task-definition-every-other-csp-directive-is.md`.

**(4) Verify enforcement with a positive violation and a control.** CDP evaluation is exempt from
`script-src` but **not** from `connect-src`, so an evaluated `fetch` to a host the policy excludes must
raise a `securitypolicyviolation` with `effectiveDirective: "connect-src"` and `disposition:
"enforce"`, and a same-origin `fetch` in the same run must succeed: without the control, a blocked
request and a broken network are the same observation. Reporting no violations is not evidence. **No unit test observes a CSP**, so a
policy wrong about `worker-src` or `style-src` breaks the Monaco editor in production and nowhere
else, which is why the live checks open the Query editor under the enforcing policy. The
report-only stage this policy went through taught the same thing twice: Safari applies nothing from a
report-only policy naming no reporting endpoint, and report-only never blocks, so a pass under it
proves a flow works and nothing about whether it survives enforcement.

**(5) Three scanner findings are accepted, not silenced.** `Cross-Origin-Embedder-Policy` is absent,
because `require-corp` buys cross-origin isolation this app cannot use (no `SharedArrayBuffer`, no
high-resolution timers) at real risk to subresource loads. `preload` is absent, because it claims a
submission to the preload list this deployment has not made, against a registrable domain it does not
own, and is near-irreversible once granted. And `style-src 'unsafe-inline'` stays for Monaco, as (1)
says; `script-src` carries no such allowance, which is the one that matters.

**(6) A finding total is not a signal.** Two Checkov findings once cancelled at 305, so the total looked
untouched, and ZAP went 20 to 13 while gaining a Medium. Diff **per check ID and per resource**.

## History

### 2026-11-18

- **Changed:** the guard ahead of Next also refuses a request carrying a `Next-Action` header or a
  `multipart/form-data` body, on every path, and `check:actions` fails a build that defines a server
  action.

### 2026-11-15

- **Changed (SPEC-263):** a guard ahead of Next answers a malformed escape, a target that is not a path
  and every upgrade with 400, the headers and the lockdown policy, from a copy a unit test holds equal.

### 2026-11-13

- **Changed:** SPEC-255. nginx's policy was replaced by the Next.js request proxy's, and the policy
  now carries a per-request nonce in `script-src`, with `'unsafe-eval'` in development only. A request
  carrying a body skips the proxy and gets `next.config.ts`'s lockdown floor, because a matched bodied
  request held every path until its body arrived. `style-src 'unsafe-inline'` stays, now because a
  nonce there would switch it off rather than because a static origin cannot mint one.

### 2026-09-02

- **Changed:** SPEC-202 destroyed the distribution, leaving nginx the only policy, and corrected the
  verification rule: CDP evaluation is exempt from `script-src`, not `connect-src`, so the earlier
  "same-origin page script" recipe was unsatisfiable under `script-src 'self'`.

### 2026-08-27

- **Changed:** SPEC-194 moved both CSP locals to root, had the container serve the policy from nginx,
  and dropped HSTS `preload` for the container's domain.

### 2026-08-04

- **Changed:** The Hosted UI domain was added to `connect-src` after its absence broke sign-in;
  enumerate from the hosts the app fetches.
- **Changed:** Report-only was found to prove nothing about surviving enforcement; read the reports or
  re-run the flow against the enforcing policy.

### 2026-08-03

- **Settled:** SPEC-140. One CloudFront response-headers policy carried the posture, with the CSP
  assembled from variables and promoted from report-only to enforcing. Full account:
  `docs/spec-delivery/SPEC-140-cloudfront-response-headers.md`.
- **Changed:** HSTS `preload` was flipped on to clear `CKV_AWS_259`, inert without an hstspreload.org
  submission.
