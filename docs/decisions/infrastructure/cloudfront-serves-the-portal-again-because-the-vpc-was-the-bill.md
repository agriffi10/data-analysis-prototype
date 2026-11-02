---
type: Decision
title: "CloudFront serves the portal again, because the VPC was the bill"
description: "**EXACTLY ONE FRONT DOOR EXISTS, and the web tier's switch picks it**: off is CloudFront over S3 (`static-portal`), on is the container. Its first apply after a switch-off leaves an empty bucket answering 403 until `deploy-spa-static.yml` is dispatched."
---

The web tier cost about $81 of an $84 monthly bill with nobody using it, and switching it off took
the portal down with it. CloudFront and S3 bill by use. The container was chosen because a client's
target environment needed a runtime it controlled and could not go through CloudFront. That
environment is shelved, so the constraint no longer applies to the live deployment.

**The container stays in the tree, dormant behind the switch, rather than being deleted.** That
keeps the change small, and it stays the path back if a client environment returns. A private repo,
`agriffi10/data-quarry-vpc`, holds the tree as it stood before this landed, at `167ca968`.

**`config.json` is a Terraform-owned object, not a deploy step.** The old workflow resolved Terraform
outputs and rendered the document with `jq`. An object rendered from the root map needs neither, a
value change reaches it on apply, and a sync pass cannot touch it.

**The deploy workflow has no `paths:` filter**, because a filter cannot see a previous run that
failed: production would sit on the old bundle behind green merges until the next app change.

**Two deploy-role findings are accepted rather than fixed.** IAM takes no resource for
`cloudfront:CreateDistribution` or `cloudfront:CreateResponseHeadersPolicy`, measured with
`simulate-custom-policy` and confirmed in the AWS Service Reference, while the scanner's bundled data
still calls them restrictable. `.github/checkov-plan-accepted.txt` carries both.

**Do NOT switch the tier on without reading `infra/info/web-tier.md`:** both modules own the same A
record, so the switching apply can stop on it.

## History

### 2026-11-02

- **Settled:** entered the register.
