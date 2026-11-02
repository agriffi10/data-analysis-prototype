---
type: Decision
title: "IaC"
description: "OpenTofu is the IaC tool (over CDK, Pulumi and SST), `infra/modules/` are bounded-context modules, and IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`."
---

OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.

## History

### 2026-08-02

- **Settled:** entered the register.
