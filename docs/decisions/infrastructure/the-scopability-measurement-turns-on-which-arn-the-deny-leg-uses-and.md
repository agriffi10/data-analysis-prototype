---
type: Decision
title: "The scopability measurement turns on which ARN the deny leg uses, and the population it guarded was two of seventeen"
description: "**Scopability is MEASURED, never assumed — and WHICH ARN you scope the deny leg to decides whether the measurement means anything.** `implicitDeny` is equally what a **wrong ARN** reads, the wrong *resource type* of the right service included. Use a **service-wide `arn:aws:<svc>:<region>:<acct>:*`**, which is type-agnostic and cannot be the wrong type; a \"validate it with a scopable sibling\" leg **does not work** and passes on the case it was derived from. Actions with no resource type sit alone in a wildcard; the only other forced wildcard is one a **measured condition key** narrows, exempting the ACTIONS it covers and never the statement — any-condition-exempts admits `iam:PassRole` on `\"*\"`. **A simulate matches PATTERNS, not the ARN the service passes** — it cannot tell you that a service calls something on your behalf, or that a condition key goes unpopulated, which are the two traps that cost this project an apply each. Contradicting intuition: `ec2:DescribeVpcAttribute` and `route53:GetChange` **are** scopable; `ecs:DescribeTaskDefinition` is not, and scoping it is the refresh deadlock arriving by your own hand. **A condition on a key the caller does not populate fails CLOSED**, and the refusal names neither. **A service may call an action on your behalf that appears in no action list** — ELB calls `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`."
---

`implicitDeny` under a scoped ARN plus `allowed` under `"*"` was the recorded method, and the first
leg is only as good as the ARN it names. `implicitDeny` is equally what a **wrong ARN** reads —
including an ARN of the right service and the wrong **resource type**, which is the case that
actually bites.

Measured, on the widening that found it: `lambda:GetEventSourceMapping`, `UpdateEventSourceMapping`
and `DeleteEventSourceMapping` each read `implicitDeny` under a **function** ARN and were on their
way into the non-scopable set. They scope to an `event-source-mapping` ARN. The register already
carried the general form — *a mapping ARN and a function ARN are different resource types* — which
is exactly the trap re-derived by someone holding the rule and not the instance.

**The fix is a service-wide ARN, `arn:aws:<service>:<region>:<account>:*`, which is type-agnostic
and therefore cannot be the wrong type.** Checked across all 59 non-scopable entries plus eleven
known-scopable controls: zero disagreements with the AWS Service Reference. The ARN shape is per
service, so S3 and IAM take `arn:aws:s3:::*` and `arn:aws:iam::<account>:*`.

**The plausible fix that does not work is worth more than the one that does**, because it is what
the next author will reach for. "Validate the ARN with a sibling action IAM *does* scope to that
resource type" fails on the very case it was derived from: under a function ARN `lambda:GetFunction`
reads `allowed` — the sibling leg passes — while all three event-source-mapping actions still read
`implicitDeny`. A sibling proves the ARN is a well-formed resource of the *service*, never that it
is the right type for the *action*, and choosing the sibling requires already knowing the answer. It
was written into three documents as the remedy before a review ran it.

Where a service defines no resource type at all no ARN can match, so there is nothing to validate:
`lakeformation` publishes **zero** across all 61 of its actions. That comes from the AWS Service
Reference, used as a **second frame while recording** and never as a live read — a test reaching the
network fails on a runner with no egress and passes by finding nothing when the endpoint changes
shape. That second frame is what caught the three above; the simulate alone agreed with the wrong
answer.

**The rules also guarded two documents of seventeen.** Both wildcard rules ran over the two platform
templates while the inline document and fourteen plane policies went unread, and every run passed on
the two it saw. A member of the non-scopable set planted into a scoped statement in a plane policy
left the suite green; so did the same plant in the inline document; the same plant in a platform
template reddened it. Widening added twenty-one measured actions and found **no defect in the
shipped policies** — the value was the blind spot, not a bug. The file set is now asserted against
the policy directory by exact count, because a floor passes a deletion.

**A wildcard is forced in exactly two ways, and the second one is where a fence turns into an escape
hatch.** The second is a `Resource: "*"` narrowed by **condition** — the two event-source-mapping
statements, where `lambda:FunctionArn` pins the mapping to one function-name pattern and, since a
mapping shares its function's region, pins the region too. That is the whole of what an
`event-source-mapping:*` pattern could have added, which is why those three keep the wildcard.
**Splitting the statement is possible** — built and measured at a couple of hundred characters
against roughly 3,600 of remaining budget — it simply buys nothing; the impossibility first written down here was false, and it was
the entire stated justification for the exemption.

**The exemption is per ACTION, never per statement.** Excusing any statement that carries some
condition makes a condition an escape hatch, and the cheapest condition narrows nothing: behind
`aws:RequestedRegion`, an account-wide `iam:PassRole` on a bare wildcard read as forced with the
whole suite green. Two reviewers in different frames found that independently, one of them planting
the grant. So an action is excused only where a key the statement actually tests is recorded as
narrowing **that action**, and everything else in the statement is still judged. The other failure
the pairing watches for is the register's own **condition on a key the caller does not populate**:
an action that never supplies `lambda:FunctionArn` is denied by the condition meant to protect it,
naming neither.

Actions with no resource type sit alone in a wildcard. A simulate matches patterns, not the ARN the service passes, so it cannot tell you that a service calls an action on your behalf that appears in no action list (ELB calls `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`) or that a condition key goes unpopulated, the two traps that cost this project an apply each. Contradicting intuition, `ec2:DescribeVpcAttribute` and `route53:GetChange` are scopable, while `ecs:DescribeTaskDefinition` is not, and scoping it is the refresh deadlock arriving by your own hand.

## History

### 2026-09-07

- **Settled:** entered the register.
