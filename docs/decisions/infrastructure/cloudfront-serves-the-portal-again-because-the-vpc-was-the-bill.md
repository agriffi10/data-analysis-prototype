---
type: Decision
title: "The web tier is the only front door, and it is on only while someone is working (SPEC-255)"
description: "**EXACTLY ONE FRONT DOOR EXISTS, and it is the web tier**: the Next.js server on Fargate. A Node app has no static fallback, so with the switch off the portal's host does not resolve and the portal is down, which is accepted. Switch it with `TF_VAR_web_tier_enabled` and CI, never by writing to AWS, and off again when the work is done. **The portal's certificate renews only while the tier is on** (ACM renews only a certificate in use, from 60 days before expiry), so one that lapsed while off needs a reviewed re-issue before the tier can serve (`infra/info/web-tier.md`)."
---

The portal is a Next.js app served by a Node server in the Fargate web tier, and nothing else
serves it. The client environment the portal is moving to requires Next.js on a server runtime, and
a Node app has no static fallback: there is no build output CloudFront could serve while the server
is away. So the CloudFront path that served the portal while the tier was off was retired with the
move: the `static-portal` module, `deploy-spa-static.yml`, and the deploy role's grant for them, the
grant in a pull request of its own once the destroy had applied, because the destroy needed it.

**The tier is off when nobody is working, and the portal is down while it is off.** The reasoning
that first brought CloudFront back still holds: the tier bills by the hour whether anyone uses it,
and it was about $81 of an $84 monthly bill with nobody using it. What changed is the price of
switching it off, which is now the portal itself. Andrew accepted that for the Next.js arc. A
session that needs the portal switches the tier on through the repository variable and Deploy
Infrastructure, then Deploy SPA image, and switches it off again through the same variable when its
work is done, saying so in its report. It never writes to AWS directly.

**The certificate is the trap the retirement leaves.** It stays outside the switch, so a switch-on
does not wait for a new one to validate. But with the distribution gone it is in use only while the
load balancer exists, and ACM renews a certificate only while it is in use, starting 60 days before
it expires. The tier must be switched on inside that window for the renewal to happen, and a
certificate that lapsed while the tier was off has to be re-issued by a reviewed infrastructure
change before the tier can serve. `infra/info/web-tier.md` gives the command that reads its expiry.

**Do NOT build a second front door beside the tier**, a holding page included: the arc keeps one
front door, and `lambdas/test_web_tier_switch.py` fails if a `static_portal` call returns to the
root. **Do NOT keep the tier on to save a switch-on**: the cost is the reason the switch exists.

## History

### 2026-11-13

- **Changed:** SPEC-255. The portal became a Next.js app on a Node server, which has no static
  fallback, so CloudFront stopped being the front door while the tier is off: `static-portal`,
  `deploy-spa-static.yml` and the deploy role's grant for them were deleted, and with them the
  Terraform-owned `config.json` object, the deploy workflow without a `paths:` filter, and the two
  accepted CloudFront findings this entry carried. The tier is now always the front door, on only
  while someone is working, and the certificate renews only while it is on.

### 2026-11-02

- **Settled:** entered the register. The web tier was nearly the whole bill and the client
  environment that required a container was shelved, so the existing switch picked the front door:
  CloudFront over S3 while off, the container while on, one origin either way. A private repo,
  `agriffi10/data-quarry-vpc`, holds the tree as it stood before that change, at `167ca968`.
