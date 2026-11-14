---
type: Decision
title: "The web tier has an off switch, and the balancer gave up its deletion protection for it"
description: "**The web tier has an OFF SWITCH** (`web_tier_enabled`, a string held to exactly `true` or `false`): `network` and `spa` go whole, so **nothing outside them may read their outputs or sit in the VPC**. The registry lives outside in `spa-image` so its images survive, and the ALB carries **no deletion protection**, which is what lets one apply take the tier down. `infra/info/web-tier.md`."
---

With no users, the web tier was nearly the whole bill: the VPC's interface endpoints, the load
balancer and its public IPv4 addresses, the Fargate task and Container Insights all bill by the
hour, while everything else in the stack bills by use. The `network` and `spa` modules exist only to
serve the portal, so both carry `count` on one switch and go whole; `moved` blocks put their state
at instance `[0]`, and a local plan over scratch state of the same shape showed every resource
moved and nothing added or destroyed. Production applied those blocks, and they were deleted once
it had. Procedure: `infra/info/web-tier.md`.

**The registry left `spa` for a module of its own** (`spa-image`). Inside, it would go with the tier
— and with `force_delete` deliberately unset the destroy would stop at `DeleteRepository`, while
with it set the images would go and switching back on would start a service naming a tag that no
longer exists. Its two resource-level `moved` blocks were more specific than the module move and
won over it.

**The load balancer's deletion protection is off, and `CKV_AWS_150` left the enforced list.** AWS
refuses `DeleteLoadBalancer` while it is on, and Terraform cannot turn it off and delete in one
apply, so keeping it would make every switch-off two applies with a half-torn tier between. What it
guarded was an accidental replacement of a balancer that holds no state, whose alias record the
same apply rewrites, and which the PR's rendered plan shows. Rolling the switch out needs two
applies once: the merge that adds it turns protection off with the tier still on, and only then can
the variable take the tier down.
Disposition: `docs/security-baseline.md`.

*(Superseded 2026-11-02: the certificate left the switch, because `static-portal` uses it while the tier is off. Marked 2026-11-13: SPEC-255 deleted `static-portal`, and the certificate stays outside the switch, in use and so renewed only while the tier is on; `cloudfront-serves-the-portal-again-because-the-vpc-was-the-bill.md` has the trap and `infra/info/web-tier.md` the recovery.)* **The SPA's certificate is on the switch too**, found by review rather than by any gate. ACM renews
a public certificate only while a service uses it, so one kept through an off period spanning its
renewal window would expire; the provider then reads the validation as gone and fails recreating
it on an expired certificate, which turns every later apply red, on or off. Destroyed with the
listener, it is requested again at switch-on. Its validation records read the
certificate's count through a conditional, which keeps their domain-name keys, so the merge's
apply moves the certificate and its validation to `[0]` and leaves the records where they are.
Not `flatten()`, which is unknown at plan over a new certificate with a second name and would fail
every switch-on.

**A change to the IAM in `network` or `spa` merged while the tier is off goes unscanned**: a
pull request's plan holds neither module, and switch-on is a dispatch that applies without a plan.
The runbook says to switch on first.

**The switch is a string, not a bool.** As a bool OpenTofu also accepts `0` and `1`, and the two
workflows that act without OpenTofu — Deploy SPA image skips its job, and Security its ZAP
baseline, while the tier is off — compare against the string `false`. A `0` would have taken the
tier down while they carried on deploying to and scanning nothing. A validation holds it to exactly
`true` or `false`, so every reader agrees on every value OpenTofu accepts. *(Since 2026-11-02 ZAP no
longer skips, because a portal exists on both sides of the switch. Marked 2026-11-13: it skips again
since SPEC-255, loudly, because nothing serves the portal while the tier is off;
`docs/decisions/gates-and-tests/security-scanning.md`.)*

**Do NOT** wire another module to a `network` or `spa` output, place a resource in the VPC, or turn
the balancer's deletion protection back on while the switch exists.

The switch is the `web_tier_enabled` variable.

## History

### 2026-11-13

- **Changed:** Marked for SPEC-255: `static-portal` is gone, so the certificate is outside the switch with nothing using it while the tier is off, and renews only while the tier is on; and the ZAP baseline skips again while the tier is off.

### 2026-09-30

- **Settled:** entered the register.
