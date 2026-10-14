# `network` — the VPC, and the route it deliberately does not have

Two availability zones. Public subnets carry the load balancer and reach the internet through an
internet gateway. Private subnets carry the ECS tasks and have **no default route at all** — there
is no NAT gateway anywhere in this design, and the three destinations a task actually needs are
reached by VPC endpoints instead.

**Behind the web tier's off switch**, with `spa`: `web_tier_enabled = false` removes this module
whole, so nothing outside the two may read its outputs or be placed in the VPC
([`../../info/web-tier.md`](../../info/web-tier.md)).

| File | Holds |
|---|---|
| `main.tf` | the VPC, subnets, route tables, both security groups, and flow logs |
| `endpoints.tf` | three interface endpoints and one gateway endpoint |
| `outputs.tf` | ids the platform modules consume, and the two a live check asserts against |
| `variables.tf` | the module interface |
| `policies/` | the flow-log role's trust and permission templates |

**Every one of these applies green when it is wrong.** That is the theme of the module.

## Why no NAT gateway — and it is not cost

Interface endpoints bill per-AZ-hour plus data processed, a NAT gateway bills per-hour plus per-GB,
and across two AZs at this traffic level the endpoint set happens to be cheaper. That is a fact that
could change. What does not change is that **"no route to the internet" is a property a reviewer
reads off a route table**, where "a NAT gateway nobody uses" is a claim somebody re-argues every
year.

**The residual, stated plainly:** any future destination with no VPC endpoint is unreachable from a
task, and it fails as a **connect timeout** rather than a 403 — the slowest failure there is to
diagnose. Foreclosed today: ECS Exec (`ssmmessages`, `ssm`, `ec2messages`), Secrets Manager, SSM
Parameter Store, any runtime package fetch, and any non-AWS host. The remedy for an AWS destination
is another interface endpoint; for a non-AWS one there is none short of a NAT gateway, and that is a
spec rather than a patch.

**Flow logs exist because of this.** A connect timeout leaves nothing behind, and the flow log is the
only record of a rejected packet — which is what makes it worth its cost in a design whose whole
premise is that certain traffic cannot leave. The aggregation interval is 60s, not AWS's default
600: ten minutes on top of the publish delay is long enough that the person debugging gives up and
adds a NAT gateway.

## The S3 gateway endpoint is not an optimisation

ECR stores image layers in S3. With both ECR interface endpoints present and this one missing, the
pull fails with **`CannotPullContainerError`** — a message that reads like an authorization problem
and is not.

It is also why the endpoint is a **gateway** rather than an interface: a gateway endpoint installs a
**prefix-list route** in the tables it is associated with, which is how traffic reaches it with no
default route at all, and **a security-group egress rule to a CIDR does not match that traffic**.

**The association set is the whole point.** A gateway endpoint associated with the wrong route table
applies green and does nothing — no error, no drift, and the only symptom is a pull that cannot
complete. `route_table_ids` is therefore every private route table, derived from the resource rather
than listed, so an AZ added later cannot be forgotten.

**No endpoint policy**, and the argument is AWS's own: the full-access default can be used because
restrictions in task IAM roles still apply on top of it. The minimum alternative is documented and is
one bucket — `prod-{region}-starport-layer-bucket`, where ECR serves layers from — so this is a
choice, not an absence of options. The residual is real: with the default policy, **every S3 bucket
in every AWS account is reachable from these subnets**. What bounds it is the task role, which holds
nothing — the SPA container makes no AWS call — so there is no identity in these subnets that S3
would answer. **Tighten this to the starport bucket the moment a task has a reason to reach S3 on
its own behalf**, because the identity bound disappears at that point and this one does not.

## `private_dns_enabled` needs the VPC's two DNS settings

`enable_dns_support` and `enable_dns_hostnames` are **required, not merely advisable**.
`private_dns_enabled` on an interface endpoint silently resolves to nothing without them — the
endpoints would exist, apply green, and every call would still try to reach the public endpoint over
a route that does not exist.

## The availability-zone list: an opt-in filter, not a state filter

Two different ways this list moves under you, and **both recreate every subnet**:

- **`state = "available"` makes membership depend on AZ health.** An impaired `us-east-1a` drops
  out, the slice returns the next two names, and Terraform destroys and recreates the whole network
  — during an availability-zone event, which is the worst possible moment.
- **Local Zones and Wavelength Zones** are named `us-east-1-atl-2a`, `us-east-1-wl1-bos-wlz-1` and
  so on, and `-` sorts **before** `a`. This account can see 14 of the former and more of the latter.
  They are `not-opted-in` today so the data source hides them — but anyone opting into one for an
  unrelated reason would put it at the front of the sorted list, and this network would move into
  two zones Fargate does not run in.

`opt-in-not-required` is what an ordinary Availability Zone reports and what neither of the other
zone types ever reports, so the filter excludes them **structurally rather than by name**.

The list is then **sorted**, which is what makes the CIDR assignment stable. Subnets are keyed by AZ
*name* so a reordering of the data source cannot recreate them — but the CIDR still has to come from
somewhere, and deriving it from the source's own ordering would reintroduce exactly the recreate the
keying exists to prevent. **The sort fixes the order; the filter fixes the membership. Both are
load-bearing.**

## Where the security-group rules live, and why this one holds none

The **task group lives here** rather than with the service, because the endpoint group's ingress rule
references it and a module must not depend on a group its own dependent owns.

**No rule that names the task group as its own is attached here.** Every one of those names the load
balancer's group too, so they are declared in the module that creates it — a rule split across two
modules is a rule nobody can read. The one rule here that *references* the task group is the
endpoints' ingress, which belongs beside the endpoints it admits traffic to; re-declaring it in the
other module fails the apply with `InvalidPermission.Duplicate`.

**The task group permits nothing on its own, and that is correct.** Terraform revokes the AWS default
allow-all egress when it creates a security group, so with no rules attached this group permits
nothing outbound and the endpoint group's ingress rule is inert. On platform version 1.4.0 **every
leg of task startup** — the ECR credential fetch, the image pull, the log stream — travels the task
ENI and is governed by this group, so a pull attempted with the front door's rules absent **will time
out**. Those rules are 443 to the endpoint group and to the S3 gateway endpoint's managed prefix
list, and they live with the load balancer. **Do not read such a timeout as an endpoint defect.**

The endpoint group has **no egress rule, deliberately**: security groups are stateful, so the
endpoint's replies travel the connection the task opened and never consult egress at all. A
placeholder rule would only teach the next reader that one is required.

## The flow-log role's wildcard statement

AWS publishes that policy with all five actions on `Resource: "*"`. Four of them take an ARN; **three
are scoped to this log group and the fourth is left out**, and the wildcard statement is left holding
the one action that genuinely cannot be scoped: `logs:DescribeLogGroups` is a list operation with no
resource type at all. Copying AWS's document verbatim would have handed a write grant on every log
group in the account to a role whose entire job is one group — and **the rendered-plan IAM scan
reports it**, which is how this was caught rather than argued about.

**`logs:CreateLogGroup` is omitted on purpose, although AWS lists it in the role's minimum.** The
service only calls it when the group is missing, and Terraform creates the group. With it, a
switch-off of the web tier left the group behind: the flow log was deleted, then the policy, then
the group, but delivery outlives the flow log by seconds and IAM honours a deleted grant for as
long, so the role's first `CreateLogStream` after the delete got `ResourceNotFoundException` and its
`CreateLogGroup` succeeded. The next switch-on stopped at `ResourceAlreadyExistsException`. Destroy
order cannot prevent that; removing the action does. `test_network_module.py` refuses it back.

## What the offline guard proves, and what it cannot

`lambdas/test_network_module.py` is a text assertion over this module's Terraform. Every failure
it guards **applies green**: a NAT gateway somebody adds to fix a timeout, a default route in a
private table, a gateway endpoint associated with the wrong route table, an interface endpoint
with private DNS off. Terraform accepts all of them, the plan reads as an ordinary addition, and
the only symptom is an image pull that cannot complete — or a task that silently reaches the
internet.

**The no-NAT assertion is repo-wide rather than module-scoped, and that is the point.** Scoped to
this module it would be satisfied by adding the gateway somewhere else, which is precisely what a
future quick fix for a connect timeout looks like.

It cannot tell you the applied route tables match, that DNS resolves to the endpoint, or that a
pull completes. Only the live checks can — and the acceptance script pairs the pull with a
`describe-route-tables` read for exactly that reason: a pull that succeeded through a route
somebody added would otherwise read as proof of the endpoints.
