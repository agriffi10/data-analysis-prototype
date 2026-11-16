---
type: Decision
title: "The Next.js server reproduces CloudFront's jobs, and two are divergences (SPEC-194, SPEC-255)"
description: "**The portal's server reproduces every job the distribution did bar two DIVERGENCES**: no brotli, no HSTS `preload`. **A header the request proxy sets overrides every other source**, a route handler's `Cache-Control` and Next's `immutable` included, so the proxy sets none. **An unmatched path answers the not-found page, HTML under a 404**: a missing `/_next/` chunk needs the `%5Fnext` route's plain-text 404, and `/healthz` must stay a route handler whose `ok` body the matrix asserts. **A guard ahead of Next answers a malformed path, a target that is not a path and every upgrade with 400 and the headers.** Assert on **responses**, never config text."
---

Producing the image is easy, and **that ease is the trap**: a CDN in front of a bucket was doing
several jobs, each configured once and then invisible, and **every one fails silently when it is
wrong**. A missing fallback breaks only deep links and only on reload. A wrong cache header runs last
week's bundle intermittently, on exactly the users whose cache is warm. A CSP missing one host breaks
one flow days later. A health check that falls through to the shell makes the balancer call a broken
server healthy and keep it in rotation. So each job is either reproduced or named as a divergence out
loud, and the whole set is asserted **on responses** by `.github/scripts/spa-image-matrix.sh`, which
runs on every pull request that touches the portal and before every image push. Reading the source
passes on a header something else overrides.

**Who does each job.** The request proxy, `src/proxy.ts`, puts the page policy and the seven security
headers on every request that carries no body. Next owns the cache classes: pages `private, no-cache,
no-store, max-age=0, must-revalidate`, hashed assets `public, max-age=31536000, immutable`, `public/`
files `public, max-age=0`. The route handlers for `/config.json`, `/healthz` and the `/_next/` 404 set
`no-store`. A request carrying a body skips the proxy, and `next.config.ts` gives it the security
headers and a lockdown policy (`response-headers-csp.md` says why).

**A header the proxy sets overrides every other source**, measured: a `Cache-Control` set there
replaced a route handler's `no-store` and Next's `immutable` on hashed assets alike. So the proxy sets
no `Cache-Control`, and a change that adds one breaks every cache class at once while each page still
renders.

**A path no page serves answers the root not-found page under a 404** (since SPEC-263; until then
the optional catch-all answered it 200 with the app shell). A non-static path under `/_next/` would
get that page's HTML, so `src/app/%5Fnext/[...rest]/route.ts` answers any `/_next/` path that matched
no built file with a plain-text 404 (the folder name escapes the underscore, because Next treats a
folder starting with `_` as private and routes nothing to it); a missing file under `/_next/static/`
gets Next's own plain 404. `/healthz` is a route handler answering `ok` in plain text, and the matrix
asserts the body, because a deleted handler would leave the probe reading a page. A removed
root-level file answers 404, so a removal reads from the status.

**Responses Next answers before routing reach neither the proxy nor `next.config.ts`.** A trailing
slash gets a 308 to the bare path. A `//host` or a `/\host` path gets a 308 to a same-origin path,
because Next collapses the slashes to one. None carries a policy or a security header; nginx had a
server-level floor for its equivalent, and Next has none. The class is accepted in
`docs/security-baseline.md` because each body is fixed text and each redirect is same-origin, and the
matrix pins every case, so a change to the class is visible.

**The rest of that class is answered by a guard ahead of Next (SPEC-263).** The image starts
`apps/portal/server-guard.cjs`, which starts Next's standalone server behind it. A path whose
percent-escape does not decode made Next answer a bare 500 with no headers and no log line, and an
absolute-form target (`GET http://host/files`, `javascript://…`, `*`) got a 308 to the URL it names, in
the client's own scheme and host. The load balancer never passes an absolute-form target on, so that
redirect was unreachable, but only because of the balancer. The guard answers both 400 with every
security header, the lockdown policy and one log line naming the method, so the image no longer
depends on what fronts it. It also answers every WebSocket upgrade, which the portal does not serve
and which Next left open with no answer at all on a path it would redirect. The matrix's guard rows
go red with the image's `CMD` back on `server.js` (observed on #1018's image, 724c27133).

**The two divergences, each with its cost and its re-open trigger.**

1. **gzip only, no brotli.** Next compresses with gzip per request. Brotli-capable browsers,
   effectively all of them, receive gzip, so the bundle transfers roughly 15–20% larger than it did
   through the distribution. Re-open trigger: a measured load-time problem, or a CDN back in front.
2. **HSTS drops `preload`.** Emitting it claims a submission to the preload list this deployment has
   not made and does not intend; the grant is against the **registrable domain** and close to
   irreversible, and these are subdomains of a parent this repository does not own, so the claim would
   commit sibling services nobody asked. It costs no Checkov finding, because the check that wanted
   it, `CKV_AWS_259`, evaluates only a CloudFront response-headers policy, and none exists now.

The `Server` banner is no longer a divergence: the Node server sends no `Server` header, and
`poweredByHeader: false` stops `X-Powered-By`. The matrix asserts both absent.

## History

### 2026-11-15

- **Changed (SPEC-263):** the catch-all retired, so an unmatched path answers the not-found page
  under a 404 and a removed root-level file is read from its status. A guard ahead of Next answers a
  malformed escape, a target that is not a path and every upgrade with 400 and the headers, where
  Next answered a bare 500, an off-site 308 that only the balancer kept away, or nothing.

### 2026-11-14

- **Corrected:** the before-routing class was misstated as same-origin redirects throughout. Measured
  with raw request lines: the trailing slash, `//host` and `/\host` are same-origin, but an
  absolute-form line is redirected off-site, and only the load balancer keeps it from a client. The
  matrix now pins all four.

### 2026-11-13

- **Changed:** SPEC-255 replaced nginx with the Next.js server. The `Server: nginx` divergence closed,
  because Node sends no banner. nginx's `add_header` inheritance rule, its per-location snippet and
  its server-level floor went with it; what replaces them is one proxy for the headers and each cache
  class's own owner, and two new traps: a proxy header overrides everything, and the optional
  catch-all answers unmatched paths 200, which is why `/_next/` has its own 404 route and `/healthz`
  its asserted body. Responses answered before routing carry no policy, accepted.

### 2026-08-27

- **Settled:** SPEC-194. The SPA moved from a distribution over an S3 origin to an nginx container,
  which reproduced every CloudFront job bar three divergences (`Server: nginx`, no brotli, no HSTS
  `preload`). Its trap was `add_header` inheritance: a location defining any header of its own
  inherited none, so every location included one snippet with `always`, under a server-level floor
  for errors raised before a location resolved.
