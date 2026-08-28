# `app` — the CloudFront delivery path

The SPA's original front door: a private S3 bucket of built assets, served through CloudFront with
Origin Access Control. **Still production, and still the rollback** — the container path in
`modules/spa` reproduces every job here and is the eventual replacement.

| File | Holds |
|---|---|
| `s3.tf` | the static-assets bucket, its access block, lifecycle rule and OAC bucket policy |
| `cloudfront.tf` | the OAC, the response-headers policy, and the distribution |
| `outputs.tf` | bucket name/ARN, distribution id, domain name |
| `variables.tf` | the module interface |

Custom error responses map 403/404 → `index.html` with a 200, so SPA client-side routes work on
direct load and refresh.

## The CSP string is not built here

It arrives **assembled from root**, so one computation feeds both delivery paths — this distribution
and the container — and so a **root-level check has something it can read**. A local inside a module
is invisible to that check, and this module is deleted when the distribution is retired, which would
orphan the computation the container depends on.

Both CSP locals live at root for the same reason.

## `preload` is inert, and close to irreversible

The `strict_transport_security` block sets `preload = true` to satisfy Checkov `CKV_AWS_259`, which
objects to nothing else — max-age, `include_subdomains` and `override` all pass already.

It changes **no behaviour today**: browsers act on the preload list, and entry to that list requires
a manual submission at hstspreload.org that we have not made and are not making. The directive
states an intent, and the cost of stating it is that someone could act on it later.

**Do not submit this domain to hstspreload.org.** Preload is close to irreversible once granted, and
this is a shared-suffix `*.cloudfront.net` name that a custom domain will eventually replace
(`CKV2_AWS_42`). When the custom domain lands, decide submission there on its own merits.

The container path deliberately **diverges** here: it emits HSTS without `preload`. That divergence,
along with `Server: nginx` and the absence of brotli, is one of the three the SPA image is allowed.

## Cross-Origin-Embedder-Policy is deliberately absent

`require-corp` exists to enable cross-origin isolation. This app has no use for it — no
`SharedArrayBuffer`, no high-resolution timers — so it would buy a scanner Low in exchange for a real
risk of breaking subresource loads. **ZAP alert 90004 stays open by decision**, recorded as accepted
in `docs/security-baseline.md`. Do not "fix" it by adding the header without revisiting that.

## `config.json` gets its own behaviour, with caching disabled

The runtime configuration document must **never** be answered from an edge cache.

`CachingOptimized` cannot express that. Its MinTTL is 1 second, and CloudFront applies MinTTL **even
when the origin sends `no-store`** — so the header alone never reaches zero. The larger numbers bite
only if the object reaches the edge *without* a `Cache-Control` header, which is one forgotten flag
away: the 24-hour DefaultTTL then applies, and the 365-day MaxTTL lets an unreachable origin keep
serving the last document it saw. Any of those serves one environment's account ids to another
environment's users, **as a portal that looks entirely healthy**. `CachingDisabled` (0/0/0) makes the
guarantee a property of the distribution instead of a flag on one upload step.

**`ResponseHeadersPolicyId` is per-behaviour and is not inherited from the default one.** Omitting it
on this behaviour would serve `config.json` with no CSP, no HSTS, no frame or content-type options,
and without the `Server`/encryption header stripping — on a URL any scanner finds immediately.

## The lifecycle rule expires nothing

The only rule is `abort-incomplete-multipart-uploads` (`CKV_AWS_300`): `deploy-app.yml` syncs `dist/`
on every deploy, and an interrupted sync leaves orphaned parts that are billed and invisible to every
listing. **Nothing here expires objects** — the deploy's own `--delete` pass owns reconciliation, and
a lifecycle expiry would race it.
