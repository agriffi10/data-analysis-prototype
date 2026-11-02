# `static-portal` — the portal without a VPC

The built SPA in a private S3 bucket, served by CloudFront at the portal's own hostname. It exists
while `web_tier_enabled` is `false`, in place of `network` and `spa`, and bills by use rather than
by the hour. How the switch works: [`../../info/web-tier.md`](../../info/web-tier.md).

| File | Holds |
|---|---|
| `s3.tf` | the bucket, and `config.json` as an object Terraform owns |
| `cloudfront.tf` | the distribution, its origin access control and its security headers |
| `dns.tf` | the A-alias record |

**The origin is the container's origin**, so Cognito's callback lists, the buckets' CORS rules, the
API's CORS rule and the CSP's `connect-src` are the same on either path.

**The deploy is `deploy-spa-static.yml`.** The infrastructure here does not put a build in the
bucket: until that workflow has run, every path but `config.json` answers 403, because the fallback
page is missing too. After a switch-off, dispatch it once Deploy Infrastructure is green.

**Differences from the container:**
- A missing hashed chunk answers the shell with a 200, where nginx gives an honest 404. Custom error
  responses apply to the whole distribution, and a module script refuses `text/html` either way.
- No `/healthz`: nothing probes it.
- No access logs, where the balancer logged to the admin bucket. Deferred: there are no production
  users to investigate on behalf of.
- CloudFront compresses at the edge, brotli included, so the build's `.gz` files are not uploaded.
