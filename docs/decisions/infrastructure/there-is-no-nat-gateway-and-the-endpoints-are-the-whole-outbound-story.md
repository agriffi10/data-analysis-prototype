---
type: Decision
title: "There is no NAT gateway, and the endpoints are the whole outbound story (SPEC-193)"
description: "**The container platform (193):** no NAT gateway anywhere — private subnets reach AWS through endpoints alone, the residual is a **connect timeout** (hence flow logs), and a successful pull proves nothing unless read beside `describe-route-tables`. The API function is **not** in the VPC and authorization lives in the **router**, both asserted as absences."
---

The private subnets carry no default route of any kind. A Fargate task reaches ECR through
`ecr.api`, `ecr.dkr` and `logs` interface endpoints with `private_dns_enabled`, and reaches the image
layers through an S3 **gateway** endpoint whose prefix-list route is what makes it reachable without
a default route at all. A NAT gateway would cost about $32/month per AZ before a byte moves, and —
the part that matters more — it would silently widen the blast radius of every future task from "the
AWS services we enumerated" to "the internet".

**The residual is a connect timeout, and it is the reason flow logs are on.** A destination nobody
added an endpoint for does not fail fast; it hangs, and a hang leaves nothing behind. Flow logs are
the only record of a rejected packet in a design whose premise is that certain traffic cannot leave.

**The no-NAT assertion is repo-wide rather than module-scoped**, because scoped to the network module
it would be satisfied by adding the gateway somewhere else — which is exactly what a quick fix for a
mysterious timeout looks like.

**Verified live, and only live.** `runningCount == 1` with no `CannotPullContainerError`, read
**beside** `describe-route-tables` showing local + prefix-list and no `0.0.0.0/0`. Without that
pairing, a pull that succeeded through a route somebody added reads as proof of the endpoints.

Detail: `spec-delivery/SPEC-193`.

The API function is not in the VPC and authorization lives in the router, both asserted as absences.

## History

### 2026-08-26

- **Settled:** SPEC-193.
