# The web tier's switch

The portal's web tier — the `network` and `spa` modules — bills by the hour whether or not anyone
uses it: the VPC's interface endpoints, the load balancer and its public IPv4 addresses, the Fargate
task and Container Insights. Everything else in the stack bills by use and costs close to nothing
idle. So the tier has a switch.

**The tier is the only front door.** The portal is a Next.js app on a Node server, and a Node app
has no static fallback, so there is nothing else to serve it: with the switch off, the portal's host
does not resolve and the portal is down. That is accepted. Switch it on while someone is working and
off when they are done, through the repository variable and CI as below, never by writing to AWS
directly.

**The switch is one repository variable, `TF_VAR_web_tier_enabled`, set to exactly `true` or
`false`.** Unset reads as `true`, so a variable nobody set never tears anything down, and any other
value fails the infrastructure plan. It is read by Deploy Infrastructure (builds or removes the
tier), Deploy SPA image (skipped while off) and the weekly Security scan, whose ZAP baseline skips
with a warning and a job-summary note while off, because there is no host to scan.

## What goes, and what stays

| Off removes | Both keep |
|---|---|
| the VPC, subnets, route tables, security groups, the four interface endpoints, the S3 and DynamoDB gateway endpoints, flow logs | Cognito and every user account, both app clients, and the server client's secret parameter |
| the load balancer, its listeners and target group, and its `portal.` alias record | every data bucket and everything in it |
| the ECS cluster, service, task definition, log group and both task roles | the portal's and the API's certificates |
| the admin bucket's policy, which only admits the load balancer's access logs | the Glue catalog and every Lake Formation grant |
| the NAT gateway and its Elastic IP, which bill by the hour | the API at `api.`, every Lambda, queue and state machine, and the SPA image registry |
| | the session table and its customer-managed key: off must not schedule the key for deletion or drop every session |

**The hostname does not change**, so Cognito's callbacks, the buckets' CORS rules, the API's CORS rule
and the CSP's `connect-src` are the same whenever the tier is on.

## Turning it on

```bash
gh variable set TF_VAR_web_tier_enabled --body true
gh workflow run deploy-infra.yml --ref main
```

Watch it to green, then point the new service at an image, and watch that run to green too — it
is the one that checks the service settled on the image:

```bash
gh workflow run deploy-spa-image.yml --ref main
```

`gh workflow run` prints the new run's URL, and `gh run watch <id> --exit-status` follows it. (A
`gh run list` straight after the dispatch can still name the previous run, and
`scripts/watch_ci.py` counts push runs on `main`, not dispatches.)

**The second dispatch is not optional.** Terraform creates the service from its own task definition,
which names `TF_VAR_spa_image_tag` — and that tag may have aged out of the registry, whose lifecycle
keeps the last thirty images, or be an image built for a task definition that no longer matches.
Until Deploy SPA image runs, the service can sit failing to pull or to start. The dispatch builds
`main` if the registry lacks it and points the service at it. Then load the portal and sign in.
**A resolver that looked the portal up while it was off can keep answering "no such host" for up to
fifteen minutes** — the zone's negative-caching time — so a portal that does not resolve straight
away is not yet a failure.

**If a switch-on stops at `CreateLogGroup` with `ResourceAlreadyExistsException` on
`/aws/vpc/<prefix>-flow-logs`, a switch-off left that group behind.** Flow-log delivery outlives the
flow log by seconds, and while the flow-log role could create its own group it recreated it just
after the apply destroyed it. The role no longer can, but a group left over from before that change
still blocks the apply. The group holds only the teardown's last few records: delete it from a
terminal with `aws logs delete-log-group --log-group-name /aws/vpc/<prefix>-flow-logs`, then
dispatch Deploy Infrastructure again. Everything else the first apply created stays in place.

## Turning it off

```bash
gh variable set TF_VAR_web_tier_enabled --body false
gh workflow run deploy-infra.yml --ref main
```

Watch that run to green. A dispatch applies without a separate plan job, so read what the apply's
log says it destroyed: only resources under `module.network[0]` and `module.spa[0]`, and nothing
under `module.session_store` or `module.auth`. The first switch-off after SPEC-257 discharges a row
in `docs/testing/owed.md` with that reading. Nothing is built in their place.

**The load balancer's deletion protection must already be off in AWS.** It is off by design; if a
switch-off ever stops at `DeleteLoadBalancer` with the listeners, the alias record and the service
already gone, that is the cause: re-apply with the tier on, then switch off again.

## The portal's certificate renews only while the tier is on

The portal's certificate sits outside the switch, so a switch-on does not wait for a new
certificate to validate. Only the load balancer's listener uses it, and **ACM renews a certificate
only while it is in use**, attempting renewal from 60 days before it expires. So the tier must be
switched on at some point inside that window for the renewal to happen. Read the expiry with:

```bash
aws acm list-certificates --region <region> --query "CertificateSummaryList[?DomainName=='<portal host>'].[NotAfter,InUse,RenewalEligibility]"
```

or from the ACM console's certificate list. `InUse` is `false` whenever the tier is off. If the certificate lapsed while the tier was off, the
listener serves an expired certificate and browsers refuse the portal: re-issuing it is a reviewed
infrastructure change (Deploy Infrastructure has no replace input), and the tier cannot usefully
serve until it lands.

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
  because a bool would also take `0` and `1`, and Deploy SPA image and the ZAP skip compare against
  the string `false` alone — `0` would take the tier down while they carried on.
