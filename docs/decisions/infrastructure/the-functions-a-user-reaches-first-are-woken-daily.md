---
type: Decision
title: "The functions a user reaches first are woken daily, because an idle image function rejects its first invoke"
description: "**A container-image Lambda idle for weeks goes INACTIVE and AWS REJECTS the first invoke**; only an invoke wakes it. So the three functions a user reaches first — the API and both Cognito triggers — are invoked once a day by a `*-keep-warm` EventBridge rule in the module that owns them, with a payload each handler treats as a no-op. **A target with no permission applies green and fails every invoke silently**, and a new Cognito trigger is kept warm only if it joins the rule: `lambdas/test_keep_warm.py` derives both from the Terraform."
---

Measured on 2026-11-02 and 2026-11-03: after 19 days without a deploy, 86 of the 91 production
functions read `State=Inactive`, `StateReasonCode=Idle`. The five that stayed Active were exactly
the five invoked in that window — the API, which something calls every day, and four scheduled
functions, the slowest of them once a day. So one invoke a day is measured to keep a function
Active. AWS documents the rest for image functions: a function not invoked "for multiple weeks"
goes Inactive, the first invocation is rejected while Lambda re-optimises the image, no duration is
given, and only an invoke reactivates it. One image for the whole fleet is a settled decision, so
every function is an image function.

**Why a wake and not a retry message.** A user meets three functions before anything else: the API
on the first request after sign-in, and the two Cognito triggers on sign-up. Sign-in itself invokes
none. None of the three has a message we could write:

- **Pre-signup** fails on Cognito's managed page, in Cognito's words, and Cognito does not retry an
  invoke that fails with a 5xx.
- **Post-confirmation** is worse than an error. The user is confirmed, the trigger never runs, and
  no Glue database is created — and because the handler never ran, its own "provisioning failed,
  run the backfill" record is never written either. The user is broken and nothing says so.
- **The API**: the SPA retries only an idempotent query, once, and treats the token refresh as its
  only other retry. A wake of undocumented length surfaces as an error page.

**The cost is nothing measurable.** Three invocations a day is about ninety a month, inside Lambda's
always-free requests and compute, and about sixty scheduled events a month from two rules is a
rounding error at any EventBridge rate. Cost is why the portal left the VPC, so the bar was a wake
that does not move the bill.

**Not a scheduled workflow.** A GitHub Actions cron invoking the three needs no new
infrastructure, but GitHub disables a scheduled workflow after sixty days without repository
activity — the quiet spell this exists for — and it would spend the deploy role's credentials every
day.

**Each module wakes its own functions.** The cutover guard requires every `aws_lambda_permission`
to bind to `module.<x>.function_arn` in the module that declares the function, so a central module
taking ARNs as variables would fail it. The auth module carries one rule with two targets, the API
module one with one; the deploy grant names `rule/<project>-*-keep-warm` once, in the front door's
policy.

**The payloads are no-ops by the handlers' existing rules, not by new code.** Pre-signup gets a
valid username and no email, so it returns the event. Post-confirmation gets a `triggerSource` that
is not a sign-up confirmation, so it returns before any Glue or Lake Formation call. The API gets a
`GET /healthz` event, which answers 200 with no identity and no AWS call — a bare `{}` would answer
401 every day and read as a refusal. Each payload is a file beside the rule, and each handler's own
tests run it.

**Do NOT** widen this to the rest of the fleet by invoking handlers with synthetic events: a plane
handler given a made-up event is not a no-op in general. The async planes still go Inactive, and
whether their retries absorb a rejected first invoke is unmeasured. If that is ever extended,
`.github/lambda-probes.json` already names one function per plane judged safe to invoke with `{}`.

## History

### 2026-11-03

- **Settled:** entered the register.
