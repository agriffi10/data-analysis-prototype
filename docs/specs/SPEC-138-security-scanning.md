# Spec: Security Scanning — SAST, Dependencies, Secrets, IaC and DAST

**ID:** SPEC-138
**Status:** Draft
**Last Updated:** 2026-08-02
**Depends On:** SPEC-004 (the CI workflow this sits beside), SPEC-005 (the deployed URL DAST targets)

## Overview

The repo has no security scanning. `ci.yml` runs ESLint + Prettier + Vitest on the SPA and ruff +
pytest on the Lambdas; ruff's `S` (bandit) family gives the Python side partial SAST as a side
effect of a lint config, and that is the entirety of it. The SPA — which holds AWS credentials in
the browser, renders user-supplied file and table names, and is the only thing between a signed-in
user and a scoped IAM role — is scanned by nothing. Dependency vulnerabilities are reported by
Dependabot but nothing in CI reads them: **10 alerts are open today, 4 of them high**, and every one
of the 137 completed specs merged green over the top of them.

This spec adds a `security.yml` workflow covering five classes of finding — static analysis,
vulnerable dependencies, committed secrets, IaC misconfiguration and a live OWASP ZAP baseline —
across all three surfaces (`apps/portal/`, `lambdas/`, `infra/`).

**It ships report-only.** Every scanner runs, publishes its findings, and exits 0. That is a
deliberate first step, not a compromise: with 10 known-open dependency alerts and an unmeasured
number of SAST findings, a blocking gate on day one either turns `main` red or forces a
fix-everything change large enough that nobody would review it honestly. The purpose of this spec
is to **learn the true finding set and write it down** (FR-009). Turning the gate on, finding by
finding, is the follow-up.

## Scope

### In Scope

- A new `.github/workflows/security.yml` — PR to `main`, a weekly schedule, and manual dispatch.
- **SAST:** Semgrep OSS with the OWASP Top Ten ruleset plus per-language rulesets, over the SPA and
  the Lambdas.
- **UI lint:** `eslint-plugin-security` + `eslint-plugin-no-unsanitized` folded into the existing
  `npm run lint`, so injection/XSS classes are caught at the same moment as every other lint error.
- **Dependencies:** `npm audit` (runtime scope and full scope, reported separately) and `pip-audit`
  over all four `requirements*.txt` files.
- **Secrets:** `gitleaks` over the full history and the PR diff.
- **IaC:** `checkov` over `infra/`.
- **DAST:** OWASP ZAP baseline scan against the deployed portal, on the weekly schedule and on
  demand.
- One explicit gate switch per scanner, defaulting to report-only, so tightening is a one-line
  reviewable change rather than a workflow rewrite.
- Every scanner pinned to an exact or minor-bounded version.
- `docs/security-baseline.md` — the first full run's findings with a disposition for each.

### Out of Scope

- **Turning any gate to blocking.** That is the follow-up spec, driven by the baseline doc this one
  produces. Nothing here fails a build on a finding.
- **Fixing the findings.** Including the 10 open Dependabot alerts. This spec makes them visible in
  CI and triages them on paper; the remediation is separate work with its own risk (the `react-router`
  advisories in particular are a runtime dependency bump, not a lockfile nudge).
- **GitHub code scanning / SARIF upload / the Security tab.** The repo is private on a personal
  account; `security_and_analysis` is null and the code-scanning API returns 403. CodeQL and SARIF
  ingestion are GitHub Code Security features not available here. FR-008 is the substitute, and this
  constraint is why FR-008 exists at all.
- **CodeQL.** Same reason. If Code Security is ever purchased, CodeQL for `javascript-typescript`
  and `python` is the natural addition and Semgrep's role narrows to the OWASP rulesets.
- **OWASP Dependency-Check.** Deliberately declined. It is the Java/NVD-centric scanner; for npm and
  PyPI it is slower (a multi-hundred-megabyte NVD sync per run) and less accurate than `npm audit`
  and `pip-audit`, which read the ecosystem-native advisory databases. The OWASP coverage that
  matters here comes from Semgrep's `p/owasp-top-ten` and from ZAP.
- **Scanning the rendered IAM policies.** Checkov parses `.tf`; the `.tftpl` policy templates under
  `infra/modules/base/policies/` are opaque strings to it, so the isolation model's actual policy
  documents are a **known blind spot** (FR-006). Closing it means scanning a `tofu plan` JSON, which
  needs AWS credentials and couples this workflow to `deploy-infra.yml` — a separate decision.
- **Authenticated DAST.** ZAP runs unauthenticated against the CloudFront origin. It will not reach
  anything behind Cognito.
- **Adding `bandit` as a separate tool.** Ruff already selects `S`. A second bandit would duplicate
  it and re-litigate the four `S` ignores that `pyproject.toml` records as decisions.
- **Runtime/production security controls.** No WAF, no CSP header changes, no bucket policy changes.
  If ZAP reports a missing header, that is a finding for the baseline doc, not a fix in this spec.

---

## Functional Requirements

### FR-001: The workflow exists, is report-only, and every scanner is version-pinned

#### Description

`.github/workflows/security.yml` runs on `pull_request` → `main`, on a weekly `schedule`, and on
`workflow_dispatch`. It does **not** run on push to `main` — `main` builds and deploys, it does not
lint or test (`ci.yml`'s own comment), and the weekly schedule covers drift.

Each scanner's blocking behavior is set by a single named switch at the top of the workflow, with
report-only as the value this spec ships. A reader must be able to see which scanners gate and which
do not without reading any step's implementation.

Every scanner is pinned to an exact version or bounded to a minor. This is not caution for its own
sake: `pyproject.toml` records that ruff 0.16.0 widened its default rule set from 59 rules to 413 and
turned a green `main` red with 500 findings in files nobody had touched (#311). A security scanner
that adds rules on release does the same thing, to every open PR at once, and with a scarier label
on it. An unpinned scanner would make this spec a recurring outage.

#### Acceptance Criteria

- [ ] The workflow triggers on `pull_request` → `main`, `schedule` (weekly), and `workflow_dispatch`,
      and on no other event.
- [ ] Every job declares `timeout-minutes` (repo convention since #314).
- [ ] Every job declares least-privilege `permissions`; only the ZAP job may need more than
      `contents: read`, and if it does not, it gets `contents: read` too.
- [ ] Every scanner version is pinned exactly or bounded to a minor, in one place, with the #311
      reasoning cited once.
- [ ] With a finding present, every scanner job concludes green. The workflow's overall conclusion on
      a PR containing a deliberate finding is success.
- [ ] Flipping any one scanner to blocking is a single-value edit at the switch, requiring no change
      to that scanner's step.

### FR-002: SAST over the SPA and the Lambdas, with the OWASP Top Ten ruleset

#### Description

Semgrep OSS scans both code surfaces. Registry rulesets are used rather than hand-written rules:
`p/owasp-top-ten` (the requested OWASP coverage), plus `p/react`, `p/typescript`, `p/javascript` for
the SPA and `p/python` for the Lambdas. Semgrep OSS needs no account or token for registry rulesets.

`node_modules`, `dist`, `coverage`, `htmlcov`, `.terraform` and `__pycache__` are excluded — a
finding inside a vendored dependency is `npm audit`'s job (FR-004), not SAST's, and including them
would bury the real findings.

#### Acceptance Criteria

- [ ] Semgrep runs `p/owasp-top-ten` against `apps/portal/src` and `lambdas/`.
- [ ] It additionally runs the React/TypeScript/JavaScript rulesets against `apps/portal/src` and the
      Python ruleset against `lambdas/`.
- [ ] Build output, vendored dependencies and caches are excluded; a finding in `node_modules` is
      never reported.
- [ ] The finding count, and each finding's rule ID, file and line, appear in the job summary
      (FR-008).
- [ ] A deliberately planted test finding (e.g. a `dangerouslySetInnerHTML` on a non-constant) is
      detected and reported, and the job still concludes green.
- [ ] Test files are scanned, not excluded — a test that hard-codes a credential-shaped string is a
      finding worth seeing, even if the disposition is "accepted".

### FR-003: The UI lint pass gains security rules

#### Description

`eslint-plugin-security` and `eslint-plugin-no-unsanitized` are added to `apps/portal`'s flat config
and therefore to the existing `npm run lint` — which **already blocks CI**. This is the one place in
this spec where a finding can fail a build, and that is correct: these rules fire on injection and
XSS sinks in code being written now, at the same moment as every other lint error, before the
finding ever becomes a baseline entry.

`security/detect-object-injection` is disabled. It fires on every computed member access — the plugin's
own documentation acknowledges it as high-noise, and this codebase indexes into record types
constantly. Leaving it on would mean either hundreds of disable comments or a rule set nobody reads.

Because `npm run lint` blocks, the plugins land only once the existing tree is clean under them. If
the first run is not clean, the fixes are part of this spec's Phase 2 — not deferred to the baseline
doc, which covers report-only scanners.

#### Acceptance Criteria

- [ ] Both plugins are in `apps/portal/package.json` devDependencies, version-bounded, and recorded
      in `CLAUDE.md`'s tech-stack table (the "don't add dependencies without noting them here" rule).
- [ ] `eslint.config.js` enables both, scoped to `**/*.{ts,tsx}`.
- [ ] `security/detect-object-injection` is off, with the reason stated at the disable.
- [ ] `npm run lint -w apps/portal` passes on the branch head with zero warnings.
- [ ] A deliberate `innerHTML = userValue` is reported by `no-unsanitized/property` and fails lint.
- [ ] Any pre-existing violation is fixed in this spec, not suppressed with an inline disable, unless
      the disable carries a written reason.

### FR-004: Vulnerable dependencies are reported for both ecosystems

#### Description

`npm audit` runs twice and reports the two results **separately**, because they mean different things
for a static SPA: `--omit=dev` is what ships to a user's browser and is the gating candidate; the
full-scope run covers the build toolchain, which is a supply-chain concern but not a runtime one. Of
today's four high alerts, `react-router` is runtime and `postcss`/`brace-expansion` are build-time —
collapsing them into one number would lose exactly the distinction that decides what to fix first.

`pip-audit` runs over all four requirements files: `lambdas/requirements.txt`,
`lambdas/requirements-dev.txt`, `lambdas/control-plane-common/requirements.txt`,
`lambdas/table-builder-infer-schema/requirements.txt` and `lambdas/data-quality-polars/requirements.txt`.
The list is derived, not hard-coded — a new layer's requirements file must be scanned the day it is
added, without anyone remembering to edit this workflow.

#### Acceptance Criteria

- [ ] `npm audit --omit=dev` and a full-scope `npm audit` both run, and their results are reported
      under distinct headings.
- [ ] `pip-audit` covers every `requirements*.txt` under `lambdas/`, discovered by glob rather than
      listed literally.
- [ ] Adding a new `lambdas/<x>/requirements.txt` causes it to be scanned with no workflow edit.
- [ ] Each advisory is reported with package, installed version, severity, advisory ID and the fixed
      version where one exists.
- [ ] Both jobs conclude green with the 10 currently-open advisories present.

### FR-005: Committed secrets are detected across the full history

#### Description

`gitleaks` runs against the whole repository history, not just the PR diff — a credential committed
in SPEC-011 and "removed" in SPEC-012 is still in the pack file and still valid. The gitleaks binary
is invoked directly rather than via `gitleaks-action`, which couples to a `GITLEAKS_LICENSE` for
organization accounts; the direct invocation has no license mechanics to break if this repo ever
moves to an org.

Output is redacted. A secret scanner that prints the secret it found into a CI log that a wider
audience can read has made the problem worse, and this repo's log-field rule (`decisions.md`, tokens
and emails always out) applies to CI output for the same reason it applies to `logs/`.

#### Acceptance Criteria

- [ ] gitleaks scans the full commit history on the schedule, and at minimum the PR range on a PR.
- [ ] Findings are redacted; no raw secret value appears in a log or artifact.
- [ ] A finding reports commit, file, line and rule — enough to act on without the value.
- [ ] Known false positives, if any, are recorded in a committed `.gitleaks.toml` allowlist with a
      written reason per entry, not suppressed by narrowing the scan.
- [ ] The job concludes green when a finding is present.

### FR-006: IaC misconfiguration scanning over `infra/`, with the blind spot recorded

#### Description

`checkov` scans `infra/` with the terraform framework — OpenTofu's `.tf` files parse as terraform.
`.terraform/` and the bootstrap state config are excluded.

The blind spot is stated in the workflow itself, not just here: the IAM policies that implement this
system's entire isolation model live in `.tftpl` files rendered by `templatefile()`, and Checkov sees
them as opaque strings. A reader who sees a green Checkov job must not conclude the IAM is checked.
It is not. The `${aws:PrincipalTag/username}` conditions, the shared-role scoping, the
`DATA_LOCATION_ACCESS` grants — none of that is covered by this FR.

#### Acceptance Criteria

- [ ] Checkov runs over `infra/` with the terraform framework and concludes green with findings
      present.
- [ ] `.terraform/`, provider caches and lockfiles are excluded.
- [ ] Findings report check ID, resource address, file and line.
- [ ] The `.tftpl` blind spot is stated as a comment in `security.yml` at the Checkov step **and** in
      `docs/security-baseline.md`, naming the `tofu plan` JSON as the way to close it.
- [ ] Any check suppressed is suppressed by ID in a committed config with a written reason — never by
      narrowing the scanned path.

### FR-007: A scheduled OWASP ZAP baseline against the deployed portal

#### Description

The ZAP baseline scan runs on the weekly schedule and on `workflow_dispatch`, against
`vars.VITE_APP_URL`. It does not run on PRs: a PR has not been deployed, so it would scan whatever
`main` last shipped and attribute the result to the wrong change.

It is unauthenticated and passive — it spiders and reports, it does not attack. Against a
Cognito-gated SPA that means it exercises the static shell and the CloudFront response headers, so
the findings it can produce are mostly OWASP A05 Security Misconfiguration: CSP, HSTS,
`X-Content-Type-Options`, `X-Frame-Options`, cookie attributes. That is a narrow but real slice, and
it is a slice nothing else in this spec covers.

Issue-writing is off. ZAP's action opens a GitHub issue per run by default; on a report-only baseline
that is a weekly issue restating the same headers.

#### Acceptance Criteria

- [ ] The scan runs on `schedule` and `workflow_dispatch` only, never on `pull_request`.
- [ ] The target is `vars.VITE_APP_URL`; if the variable is unset the job skips with a clear message
      rather than failing or scanning a default.
- [ ] Automatic issue creation is disabled.
- [ ] The HTML and JSON reports are uploaded as artifacts with a retention period set.
- [ ] The job concludes green with findings present.
- [ ] The comment at the step states that the scan is unauthenticated and reaches only the
      pre-login surface, so a green run is not evidence about anything behind Cognito.

### FR-008: Findings are legible without GitHub code scanning

#### Description

The Security tab is unavailable on this repo (see Out of Scope), so there is no alert list, no
deduplication across runs, and no "new vs. existing" diffing. Everything a reviewer needs must be in
the run itself.

Every scanner writes a section to `$GITHUB_STEP_SUMMARY` — a count, and the findings in a table —
and uploads its machine-readable output as an artifact. The summary is what a reviewer reads on a PR;
the artifact is what the follow-up spec diffs against the baseline. A scanner that finds nothing says
so explicitly; a silent section is indistinguishable from a step that failed to run.

#### Acceptance Criteria

- [ ] Each scanner appends a titled section to the job summary with its finding count.
- [ ] A zero-finding scanner writes an explicit "no findings" line, never an empty section.
- [ ] Each scanner uploads its raw output (JSON/SARIF/HTML as applicable) as an artifact with a
      retention period.
- [ ] Artifacts upload even when the scanner step found something — no step's failure or finding
      prevents the summary or the artifact.
- [ ] A reviewer can determine, from the PR checks UI alone, which scanners ran and how many findings
      each produced.

### FR-009: The first full run is captured and triaged

#### Description

The deliverable of a report-only spec is the written baseline. `docs/security-baseline.md` records
the first complete run: every finding, with a disposition of **fix**, **accept** or **defer**, and a
one-line reason. The 10 open Dependabot advisories are included, since the npm and pip jobs will
re-report them.

This document is the input to the follow-up spec. Without it, "report-only" is indistinguishable from
"switched off", and this spec would have delivered noise.

#### Acceptance Criteria

- [ ] `docs/security-baseline.md` exists and records the run it was taken from.
- [ ] Every finding from every scanner has a disposition and a reason.
- [ ] The four high-severity npm advisories each have a named disposition, with runtime vs. build-time
      scope stated.
- [ ] The Checkov `.tftpl` blind spot and the ZAP unauthenticated limitation are both stated as
      coverage gaps, not findings.
- [ ] The doc names, per scanner, the threshold at which it should become blocking — the concrete
      proposal the follow-up spec implements.
- [ ] It is a snapshot, not a living register: it is dated, and the follow-up spec supersedes it
      rather than editing it forever.

---

## Scanner Matrix

| Surface | Scanner | Class | OWASP | Trigger | Gate (this spec) |
|---|---|---|---|---|---|
| `apps/portal/src`, `lambdas/` | Semgrep `p/owasp-top-ten` + language rulesets | SAST | A01, A03, A07, A08 | PR, weekly | report-only |
| `apps/portal` | `eslint-plugin-security`, `eslint-plugin-no-unsanitized` | SAST (lint) | A03 | PR (existing `ci.yml`) | **blocking** |
| `lambdas/` | ruff `S` (bandit) — *already present* | SAST | A03, A02 | PR (existing `ci.yml`) | **blocking** |
| `apps/portal` | `npm audit` (runtime + full) | Dependencies | A06 | PR, weekly | report-only |
| `lambdas/` | `pip-audit` | Dependencies | A06 | PR, weekly | report-only |
| whole repo | `gitleaks` | Secrets | A02, A07 | PR, weekly | report-only |
| `infra/` | `checkov` | IaC misconfig | A01, A05 | PR, weekly | report-only |
| deployed portal | OWASP ZAP baseline | DAST | A05 | weekly, dispatch | report-only |

## File & Folder Structure

```
.github/workflows/security.yml              # new — every scanner, the gate switch, the summaries
.github/workflows/README.md                 # the table gains a fifth row
apps/portal/eslint.config.js                # security + no-unsanitized (FR-003)
apps/portal/package.json                    # two devDependencies
.gitleaks.toml                              # allowlist, only if FR-005 turns one up
.checkov.yml                                # suppressions by ID, only if FR-006 turns one up
docs/security-baseline.md                   # new — the triaged first run (FR-009)
docs/decisions.md                           # the no-GHAS decision and its consequence
CLAUDE.md                                   # tech-stack table + one Key Decisions line
docs/specs/INDEX.md                         # status row
docs/spec-delivery/SPEC-138-security-scanning.md
```

## Implementation Phases

### Phase 1: The workflow skeleton

- `security.yml` with its triggers, the gate switch, per-job timeouts and permissions, and the
  summary + artifact plumbing that FR-008 requires — proven with one trivial scanner before the rest
  are hung off it.

### Phase 2: SAST

- Semgrep with the OWASP and language rulesets (FR-002).
- The two ESLint plugins, and whatever fixes the existing tree needs to pass under them (FR-003).
  This phase is not done while `npm run lint` is red.

### Phase 3: Dependencies and secrets

- `npm audit` at both scopes, `pip-audit` over the globbed requirements files (FR-004).
- `gitleaks` over full history, redacted (FR-005).

### Phase 4: IaC

- `checkov` over `infra/`, with the `.tftpl` blind spot written at the step (FR-006).

### Phase 5: DAST

- The ZAP baseline job, scheduled and dispatchable, skipping cleanly on an unset `VITE_APP_URL`
  (FR-007).

### Phase 6: Baseline and docs

- Run the whole workflow, collect every finding, and write `docs/security-baseline.md` with a
  disposition each (FR-009).
- The docs sweep: workflows README, `CLAUDE.md` tech stack + one Key Decisions line, the
  `decisions.md` entry, INDEX row, delivery doc.
- **No user-facing change** — nothing in the portal UI changes, so the SPEC-074 Help & guides sweep
  is a no-op and is recorded as such.
