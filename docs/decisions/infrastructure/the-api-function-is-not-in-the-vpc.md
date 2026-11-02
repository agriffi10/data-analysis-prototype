---
type: Decision
title: "The API function is not in the VPC (SPEC-193)"
description: "The API function is never attached to the VPC, which exists for the container; its module is asserted to carry no `vpc_config`, `aws_security_group` or `subnet_ids`."
---

The VPC exists for the container. Attaching the API function would need an interface endpoint per
service it later calls and would put ENI attachment on the cold-start path — and after the arc's
provider swap the token-verification host is a third party with **no AWS endpoint at all**, so a
function inside those subnets would stop verifying with no code change to blame.

Asserted as an **absence** (`vpc_config`, `aws_security_group`, `subnet_ids` forbidden in the module),
because a `vpc_config` added later shows up only as latency until the day it shows up as a timeout.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-08-26

- **Settled:** SPEC-193.
