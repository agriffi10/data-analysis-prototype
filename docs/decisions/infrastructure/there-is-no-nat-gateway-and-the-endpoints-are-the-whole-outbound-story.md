---
type: Decision
title: "One NAT gateway carries the portal server's two internet destinations, and endpoints carry everything AWS (SPEC-193, SPEC-257)"
description: "**The container platform (193; reversed in part by 257):** private subnets reach every AWS service through endpoints, and **one zonal NAT gateway on the web tier's switch is their only default route**, for the two destinations no endpoint serves: the Cognito domain's token endpoint and the API's custom domain. **Task start never depends on it** (the client secret comes through the `ssm` endpoint), so a start that fails is still an endpoint or a security-group fault. The gateway and its Elastic IP **wait for the internet gateway**, and only a switch-on from nothing can hit that order. A destination with no endpoint now leaves through the NAT rather than timing out, so **flow logs** are the record of what a task reached. The one-NAT assertion is repo-wide. The API function is **not** in the VPC and authorization lives in the **router**, both asserted as absences."
---

*(Rewritten in place 2026-11-13 for SPEC-257. Until then this entry said there was no NAT gateway
anywhere, and that the private subnets carried no default route of any kind.)*

**Why there is one now.** The portal server holds the session (SPEC-257), so it exchanges codes and
refreshes tokens at the Cognito domain's token endpoint, and forwards `/api/` to the API's public
custom domain. Neither has a VPC endpoint. One zonal NAT gateway, in the first sorted zone's public
subnet, carries both, and every private route table's one default route points at it. It is on
`web_tier_enabled` with the rest of `network`, so it bills only while someone is working. One, not
one per zone: the tier has no users, and a zone outage costs what switching the tier off costs.

**AWS services stay on endpoints, and that keeps the original reasoning alive.** A task reaches ECR
through `ecr.api`, `ecr.dkr` and `logs` interface endpoints with `private_dns_enabled`, the image
layers through the S3 **gateway** endpoint, the session store through a DynamoDB **gateway**
endpoint, and its client secret through an `ssm` interface endpoint at start. So task start never
depends on the NAT gateway, and a start that fails is still an endpoint or a security-group fault,
not a route. What the NAT gateway did change is the blast radius SPEC-193 declined it for: a task
can now reach the internet on 443, because neither destination has a fixed address range.

**The residual is no longer a connect timeout.** A destination nobody added an endpoint for used to
hang and leave nothing behind. Now it leaves through the NAT gateway and works, billed per gigabyte.
Flow logs stay on, and they are now the record of what a task reached as well as what was refused.

**The gateway and its Elastic IP wait for the internet gateway.** A public NAT gateway created before
the internet gateway is attached fails with `Gateway.NotAttached`, and nothing in either argument
list orders them. Only a switch-on from nothing can hit it, and no check runs one, so the
`depends_on` is the whole defence.

**The one-NAT assertion is repo-wide rather than module-scoped**, so a second gateway, or one added
outside `network` as a quick fix for a timeout, fails a test rather than applying green.

**Verified live by a route table, not by a pull.** Each private table shows local, the S3 and
DynamoDB prefix-list routes and `0.0.0.0/0` to the NAT gateway, read beside a sign-in that completed.

Detail: `spec-delivery/SPEC-193`, `infra/modules/network/README.md`.

The API function is not in the VPC and authorization lives in the router, both asserted as absences.

## History

### 2026-11-13

- **Reversed in part:** SPEC-257 added one NAT gateway on the web tier's switch for the portal
  server's two internet destinations. AWS services stay on endpoints, and an `ssm` and a DynamoDB
  endpoint joined them. The entry was rewritten in place; its filename keeps the old claim so that
  links to it hold.

### 2026-08-26

- **Settled:** SPEC-193.
