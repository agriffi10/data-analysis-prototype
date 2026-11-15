---
type: Decision
title: "The Next.js server reproduces CloudFront's jobs, and two are divergences (SPEC-194, SPEC-255)"
description: "**The portal's server reproduces every job the distribution did bar two DIVERGENCES**: no brotli, no HSTS `preload`. **A header the request proxy sets overrides every other source**, a route handler's `Cache-Control` and Next's `immutable` included, so the proxy sets none. **The optional catch-all answers any unmatched path 200 with the app shell**: a missing `/_next/` chunk needs the `%5Fnext` route's plain-text 404, and `/healthz` must stay a route handler answering `ok`, or a probe reads a broken server as healthy. Assert on **responses**, never config text."
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

**The optional catch-all answers any path nothing else matched with a 200 and the app shell.** That
is how a deep link works, and it is also three traps. A missing hashed chunk under `/_next/` would get
the shell as `text/html` too, so `src/app/%5Fnext/[...rest]/route.ts` answers any `/_next/` path that
matched no built file with a plain-text 404 (the folder name escapes the underscore, because Next
treats a folder starting with `_` as private and routes nothing to it). `/healthz` is a route handler
answering `ok` in plain text, and the matrix asserts the body, because a deleted handler would leave
the catch-all answering the probe with a 200. And a removed root-level file still answers 200 HTML,
preserved deliberately and pinned by the matrix, which is why a removal is read from the
content type and never from the status code here.

**Responses Next answers before routing reach neither the proxy nor `next.config.ts`.** A trailing
slash gets a 308 to the bare path. A `//host` or a `/\host` path gets a 308 to a same-origin path,
because Next collapses the slashes to one. An absolute-form request line, `GET http://host/files`,
gets a 308 to the URL it names, in the client's own scheme and host, which is off-site. A malformed
escape gets a plain-text 500. None of them carries a policy or a security header. nginx had a
server-level floor for its equivalent; Next has none. The class is accepted in
`docs/security-baseline.md` because each body is fixed text, and the off-site redirect is unreachable
through the load balancer, which turns an absolute-form line into origin form or refuses it, and
refuses an HTTP/2 `:path` that does not start with `/`. So **the balancer is what holds that redirect
off**, and anything else put in front of the container, or a change to the balancer's listeners or
HTTP attributes, has to be measured for it again. The matrix pins every case, the off-site
`Location` included, so a change to the class is visible.

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
