---
type: Spec
id: SPEC-266
title: "The Member Account Consumes the Client's Identity Center"
description: "Would have created, behind one switch and from four Identity Center inputs the client's admins supply, every member-account consumer Phase 5 needs; cancelled before it was built, and the design moved into the transition plan."
spec_status: Cancelled
depends_on: []
arc: carrier
arc_order: 1
---

**Dependency notes:** None to build on; it waited on the AWS provider moving to 6.19 or later.
**Transition context:** `docs/transition_plan.md`. This spec was cancelled while still Draft; nothing
was built.

## Why this spec was cancelled

**User decision, 2026-11-17: work meant for after the move into the client environment gets no spec;
it lives in [`docs/transition_plan.md`](../transition_plan.md).** This repeats the rule of 2026-09-01
(SPEC-204's tombstone): a spec that can only be built or proved in another environment is a spec
whose claims drift with no test to catch them. Every resource it creates consumes the client's organization Identity Center instance, and the parts that decide whether it works (the cross-account on-behalf calls, and whether STS populates the carrier's two Identity Center condition keys) can only be measured there.

**The design was not discarded.** It is now in the transition plan:
[§4.4, *Building the consumers*](../transition_plan.md#building-the-consumers) (the provider upgrade
that gates it, the flag and the four inputs' shapes, refusing to adopt an existing singleton, the
destroy guard over the applied plan and its override, the deploy role's grant for calls made on our
behalf, the server's and the API's wiring, and the stand-in apply and destroy run);
[§3.6](../transition_plan.md#36-the-carrier-role) (the carrier's trust details, its permissions and
the allow-set gate); [§3.9](../transition_plan.md#39-the-storage-plane--s3-access-grants) (the location
role's permissions, its `_*` Deny and the fence on grants); §3.5's workgroup bullet (the decision to
keep `EnforceWorkGroupConfiguration` false, and the probe it rests on); and §4.7's *The key itself*
(the sealing key's policy). The ARCS carrier-arc entry is marked cancelled and points there too.

## What validating it against the built code found, 2026-11-17

Recorded because the corrections are the reason a client-environment design should not sit in
`docs/specs/` unbuilt.

- **The provider pin holds.** `infra/providers.tf` requires `~> 5.0`, locked at 5.100.0, and that
  binary carries none of `aws_lakeformation_identity_center_configuration`,
  `identity_center_configuration` or `query_results_s3_access_grants_configuration`. When 6.19 and
  6.10 first ship them could not be checked offline.
- **The precondition precedent holds**: the one cross-variable check under `infra/` is a
  precondition (`infra/certificates.tf`), and CI runs OpenTofu `~1.8`.
- **Its trust policy and the plan's disagreed, and each was half right.** The spec used one statement
  for `sts:AssumeRole`, `sts:SetSourceIdentity` and `sts:SetContext`, with no
  `sts:RequestContextProviders` condition and an `aws:SourceArn` naming the Access Grants instance.
  The plan used a second statement for `sts:SetContext` with the provider condition, and an
  `aws:SourceArn` naming the location. AWS's "Register a location" page, read on 2026-11-17, names the
  **instance** and puts `sts:SetSourceIdentity` beside `sts:AssumeRole`, which the spec had right, and
  says the Identity Center case "includes a second statement", which the plan had right, though the
  page never prints it. §3.9 now carries the corrected shape and the owed check.
- **One path was wrong.** The spec put its destroy guard at `scripts/`; every workflow guard lives in
  `.github/scripts/` (`frozen_fleet_guard.py`, `tf_var_guard.py`), and §4.4 says so.
- **One reason was misattributed.** `web_tier_enabled` is a string for exactness against 0 and 1
  (`infra/variables.tf`); the empty-means-unset reason comes from `infra/info/deploy-role-iam.md`.
