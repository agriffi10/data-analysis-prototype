# Spec: Scan the Rendered IAM Policies (Checkov over the plan JSON)

**ID:** SPEC-139
**Status:** Draft
**Last Updated:** 2026-08-02
**Depends On:** SPEC-138 (the gate + summary scripts and the report-only convention), SPEC-005 (`deploy-infra.yml`, which already produces the plan)

## Overview

SPEC-138 shipped Checkov over `infra/` and recorded, at the step itself, that it cannot see the
thing that matters most: Checkov parses `.tf`, and every IAM policy in this system is produced by
`templatefile()` from a `.tftpl`. The `policy` attribute of each `aws_iam_policy` is an unevaluated
function call in Checkov's terraform graph, so the `${aws:PrincipalTag/username}` isolation model —
the single mechanism keeping one user out of another's S3 prefix and Glue database — is scanned by
nothing.

This spec closes that gap by scanning the **rendered** policies. `tofu show -json` on a saved plan
emits every policy document with its interpolations resolved, and Checkov's `terraform_plan`
framework evaluates those documents as IAM rather than as opaque strings.

The gap is not theoretical and the fix is not speculative — both were measured before this spec was
written. Against the `.tf` tree, Checkov's 305 findings contain **zero** IAM policy-document checks.
Against a plan JSON carrying one rendered wildcard policy, **nine** fire: CKV_AWS_62, CKV_AWS_63,
CKV_AWS_286 through CKV_AWS_290, CKV_AWS_355 and CKV2_AWS_40 — privilege escalation, credentials
exposure, data exfiltration, unconstrained write, permissions management. That is precisely the
class of check an isolation model built on principal tags needs, and precisely the class SPEC-138
could not run.

The scan lives in `deploy-infra.yml`, not `security.yml`, because that is where the plan and the
AWS credentials already are.

## Scope

### In Scope

- `deploy-infra.yml`'s `plan` job saves the plan (`-out`) and emits `plan.json` (`tofu show -json`).
- A Checkov step over `plan.json` with `--framework terraform_plan`, reusing SPEC-138's
  `apply-gate.sh` and `summary-section.sh`.
- `GATE_CHECKOV_PLAN`, shipped as `report`, consistent with every other SPEC-138 scanner.
- The IAM findings triaged into `docs/security-baseline.md` as a new section.
- The SPEC-138 blind-spot comments updated to point here instead of describing an open gap.

### Out of Scope

- **Turning the gate on.** Same reasoning as SPEC-138: measure first. The proposed threshold goes in
  the baseline doc.
- **Fixing any IAM finding.** Triage on paper; remediation is separate work, and changing a policy
  that implements per-user isolation is not a change to make as a side effect of adding a scanner.
- **Replacing the `.tf` Checkov scan in `security.yml`.** The two are complementary: the plan scan
  sees rendered policies but only runs when `infra/**` changes; the `.tf` scan runs on every PR and
  on the weekly sweep. Neither subsumes the other.
- **Converting the `.tftpl` policies to `.json`.** Measured and rejected: Checkov emits nothing for a
  standalone IAM policy document — a file containing `"Action": "*", "Resource": "*"` produces zero
  findings and exit 0, because Checkov evaluates `aws_iam_policy` *resources*, not loose files. The
  extension was never the blocker; the unevaluated `templatefile()` call was. See FR-005.
- **Uploading `plan.json` as an artifact, or posting it to the PR.** FR-004.
- **Scanning on the `apply` path.** `main` applies what the PR already planned; re-scanning there
  would report findings after the change had shipped.

---

## Functional Requirements

### FR-001: The plan is emitted as JSON

#### Description

`deploy-infra.yml`'s plan step currently streams human-readable text to `/tmp/plan.txt` for the PR
comment. It gains a saved plan file and a JSON rendering, without changing what the PR comment
contains — the comment is a review aid and its format is not this spec's business.

#### Acceptance Criteria

- [ ] `tofu plan` writes a plan file via `-out`, and `tofu show -json` renders it to `plan.json`.
- [ ] The existing PR plan comment is unchanged in content and format.
- [ ] `plan.json` is produced with the same `TF_VAR_*` environment as the existing plan step — a
      plan rendered under different variables is a different plan.
- [ ] If `plan.json` is absent or not valid JSON, the Checkov step fails rather than reporting zero.

### FR-002: Checkov scans the rendered plan and the IAM checks actually run

#### Description

Checkov runs with `--framework terraform_plan` over `plan.json`. The point of the exercise is the
IAM policy-document checks, so their presence is asserted rather than hoped for: a run that reports
findings but contains no IAM check has silently regressed to the SPEC-138 state, and would look
identical to a clean result.

#### Acceptance Criteria

- [ ] Checkov runs over `plan.json` with `--framework terraform_plan`, pinned to the same
      `CHECKOV_VERSION` as `security.yml`.
- [ ] The summary reports how many findings are **IAM policy-document** checks, distinctly from the
      total.
- [ ] The job **warns loudly** when the scanned plan contains `aws_iam_policy` resources but zero
      IAM checks were evaluated — that combination means the policies went unread again.
- [ ] Findings are grouped by check ID, as in SPEC-138's `.tf` scan.
- [ ] `parsing_errors > 0` fails the job, even under `gate=report`.

### FR-003: It gates like every other SPEC-138 scanner

#### Description

`GATE_CHECKOV_PLAN`, shipped `report`, routed through `.github/scripts/apply-gate.sh`. No new gating
mechanism — the value of one gate script is that it is the only one.

#### Acceptance Criteria

- [ ] `GATE_CHECKOV_PLAN: report` is declared in `deploy-infra.yml` alongside `CHECKOV_VERSION`.
- [ ] The gate is applied by `apply-gate.sh`; an unrecognised value is a hard error.
- [ ] The summary is written by `summary-section.sh`, so a zero-finding run says so explicitly.
- [ ] With findings present, the `plan` job concludes green and the PR is not blocked.
- [ ] A Checkov failure to run fails the job regardless of the gate.

### FR-004: The plan JSON never leaves the job

#### Description

A rendered plan is more revealing than the `.tf` it came from: resolved ARNs, account identifiers,
resource attributes, and every policy document in full. SPEC-138 uploads each scanner's raw output
as an artifact; **this one must not**. The Checkov *result* is publishable; the plan that produced it
is not.

This is the one place where SPEC-138's own convention is deliberately broken, and the break is the
requirement.

#### Acceptance Criteria

- [ ] `plan.json` and the binary plan file are **not** uploaded as artifacts and **not** posted to
      the PR.
- [ ] The Checkov JSON result **is** uploaded, with a retention period.
- [ ] Both plan files are deleted before the job ends, so a later step added to this job cannot
      pick them up by accident.
- [ ] The reason is stated at the step, not only in this spec.

### FR-005: The `.tftpl` decision is recorded where the next person will look

#### Description

"Rename the policies to `.json` so they can be scanned" is the obvious idea, it was raised, and it is
wrong for a non-obvious reason. Left unrecorded it will be proposed again — and it is the kind of
change that looks harmless, touches 57 files, and buys nothing.

The finding: Checkov produced **zero** findings for a standalone policy JSON containing
`"Action": "*", "Resource": "*"`. It evaluates `aws_iam_policy` resources, not loose documents. The
extension was never what blinded it; the unevaluated `templatefile()` call was, and that call is in
the `.tf`.

#### Acceptance Criteria

- [ ] `docs/decisions.md` records the rejection with the measurement.
- [ ] The SPEC-138 blind-spot comment in `security.yml` is updated: it currently describes an open
      gap and must point at the plan scan instead.
- [ ] The note states the secondary reason to keep the extension — `.tftpl` is the signal that
      `$${aws:PrincipalTag/username}` escaping applies, which is the most error-prone thing about
      these files.
- [ ] 51 of the 57 templates happen to parse as JSON and 6 do not; the note says so rather than
      implying the whole set is invalid.

### FR-006: The IAM findings are triaged

#### Description

`docs/security-baseline.md` gains a section for the plan scan: every IAM finding, a disposition, and
a proposed gate. Any finding touching the per-user isolation policies is called out by name — a
finding on `portal-role-permissions` is a different kind of news from one on a deploy role.

#### Acceptance Criteria

- [ ] A new dated section records the run it came from.
- [ ] Every finding has a disposition of fix / accept / defer, and a reason.
- [ ] Findings on the per-user isolation policies are identified as such.
- [ ] A proposed `GATE_CHECKOV_PLAN` threshold is stated.
- [ ] The SPEC-138 coverage-gap entry "the IAM policies are unscanned" is rewritten as closed, with
      the residual limitation — the scan runs only when `infra/**` changes — stated in its place.

---

## Known Limitation (accepted, not deferred)

The plan scan runs on PRs touching `infra/**`, so it is **not** part of the weekly sweep. That is
correct rather than merely tolerable: an IAM policy cannot change without an `infra/**` change, and
Checkov is version-pinned, so its rules cannot change without a PR either. The weekly sweep exists to
catch drift in things that move on their own — advisory databases, the deployed origin — and IAM
policy content is not one of them. FR-006 records this in place of the old gap.

## File & Folder Structure

```
.github/workflows/deploy-infra.yml     # -out, tofu show -json, the Checkov step, the gate
.github/workflows/security.yml         # the blind-spot comment now points here
docs/security-baseline.md              # the plan-scan section; the old gap entry rewritten
docs/decisions.md                      # the .tftpl→.json rejection, with the measurement
CLAUDE.md                              # one Key Decisions line
```

## Implementation Phases

### Phase 1: Emit and scan

- `-out` + `tofu show -json`, the Checkov step with `--framework terraform_plan`, the IAM-check
  assertion, the grouped summary, the gate, and the plan-file cleanup.

### Phase 2: Triage and record

- Read the first real run's IAM findings, write the baseline section, rewrite the closed gap.
- The `decisions.md` entry, the `security.yml` comment, the Key Decisions line, INDEX + delivery doc.
