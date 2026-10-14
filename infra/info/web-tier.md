# The web tier's off switch

The portal's web tier — the `network` and `spa` modules — bills by the hour whether or not anyone
uses it: the VPC's interface endpoints, the load balancer and its public IPv4 addresses, the Fargate
task and Container Insights. Everything else in the stack bills by use and costs close to nothing
idle. So the tier has an off switch, and turning it off removes those two modules whole.

**The switch is one repository variable, `TF_VAR_web_tier_enabled`, set to exactly `true` or
`false`.** Unset reads as `true`, so a variable nobody set never tears anything down, and any other
value fails the infrastructure plan. It is read by three workflows: Deploy Infrastructure (builds or
removes the tier), Deploy SPA image (skipped while off) and Security (skips the ZAP baseline while
off, since there is no portal to scan).

## What goes, and what stays

| Off removes | Off keeps |
|---|---|
| the VPC, subnets, route tables, security groups, the three interface endpoints, the S3 gateway endpoint, flow logs | Cognito and every user account |
| the load balancer, its listeners and target group, and the `portal.` alias record | every bucket and everything in it |
| the portal's certificate and its validation record | the API's certificate |
| the ECS cluster, service, task definition, log group and both task roles | the Glue catalog and every Lake Formation grant |
| the admin bucket's policy, which only admits the load balancer's access logs | the API at `api.`, every Lambda, queue and state machine |
| | the SPA image registry and its images (`spa-image`) |

**While it is off, the portal does not resolve.** The API still answers, but nobody can sign in
through the portal, so nothing a user would do works — and no live check that drives the portal can
run.

**The portal's certificate goes too, on purpose.** ACM renews a public certificate only while a
service uses it, so one kept through a long off period would expire — and an expired certificate
makes every later infrastructure apply fail, on or off. Switching on requests a new one and waits
for its DNS validation, which adds a few minutes to that apply.

## Turning it off

```bash
gh variable set TF_VAR_web_tier_enabled --body false
gh workflow run deploy-infra.yml --ref main
```

Then watch that run to green: `gh workflow run` prints the new run's URL, and `gh run watch <id>
--exit-status` follows it. (A `gh run list` straight after the dispatch can still name the previous
run, and `scripts/watch_ci.py` counts push runs on `main`, not dispatches.) A dispatch applies
without a separate plan job, so read what the apply's log says it destroyed: only resources under
`module.network[0]` and `module.spa[0]`, plus the portal's certificate, its validation and its
validation record (`aws_acm_certificate.spa[0]`, `aws_acm_certificate_validation.spa[0]`,
`aws_route53_record.spa_certificate_validation`).

**The load balancer's deletion protection must already be off in AWS.** The merge that added the
switch turned it off with the tier still on; until that apply has finished, a switch-off stops at
`DeleteLoadBalancer` with the listeners, the alias record and the service already gone. If a
switch-off ever stops there, that is the cause: re-apply with the tier on, then switch off again.

## Turning it back on

```bash
gh variable set TF_VAR_web_tier_enabled --body true
gh workflow run deploy-infra.yml --ref main
```

Watch it to green, then point the new service at an image, and watch that run to green too — it
is the one that checks the service settled on the image:

```bash
gh workflow run deploy-spa-image.yml --ref main
```

**The second dispatch is not optional.** Terraform creates the service from its own task definition,
which names `TF_VAR_spa_image_tag` — and that tag may have aged out of the registry, whose lifecycle
keeps the last thirty images. Until Deploy SPA image runs, the service can sit failing to pull. The
dispatch builds `main` if the registry lacks it and points the service at it. Then load the portal
and sign in. **A resolver that looked the portal up while it was off can keep answering "no such
host" for up to fifteen minutes** — the zone's negative-caching time — so a portal that does not
resolve straight away is not yet a failure.

**If a switch-on stops at `CreateLogGroup` with `ResourceAlreadyExistsException` on
`/aws/vpc/<prefix>-flow-logs`, a switch-off left that group behind.** Flow-log delivery outlives the
flow log by seconds, and while the flow-log role could create its own group it recreated it just
after the apply destroyed it. The role no longer can, but a group left over from before that change
still blocks the apply. The group holds only the teardown's last few records: delete it from a
terminal with `aws logs delete-log-group --log-group-name /aws/vpc/<prefix>-flow-logs`, then
dispatch Deploy Infrastructure again. Everything else the first apply created stays in place.

## What not to do

- **Do not wire anything outside `network` and `spa` to their outputs, or place anything in the
  VPC.** With the switch off there is no module instance to read from, and anything in the VPC goes
  with it. The root outputs that read them are `one(...)` and go null while off.
- **Do not turn the load balancer's deletion protection back on** without retiring the switch.
  AWS refuses to delete a protected balancer, so the switch would stop half done. The reasoning is in
  `../modules/spa/README.md`, and the Checkov disposition in `docs/security-baseline.md`.
- **Do not merge IAM changes to `network` or `spa` while the tier is off.** A pull request's plan
  contains neither module then, so the rendered-plan IAM scan cannot read their policies, and
  switching on is a dispatch that applies without a plan. Switch on first, or hold the change.
- **Do not make the variable a bool.** It is a string that accepts exactly `true` or `false`
  because a bool would also take `0` and `1`, and the two workflows that skip while the tier is off
  compare against the string `false` alone — `0` would take the tier down while they carried on.
