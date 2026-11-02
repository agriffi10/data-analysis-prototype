---
type: Spec
id: SPEC-004
title: "GitHub Actions CI"
description: "Gives developers a GitHub Actions CI workflow that installs dependencies, lints, runs unit tests, and builds on every push and pull request, so failures block merges."
spec_status: Completed
depends_on: []
---

---

## Overview

This spec adds a GitHub Actions CI workflow that runs on every push and pull request. The workflow installs dependencies, runs the linter, runs the unit test suite, and produces a production build. It serves as a quality gate — lint failures, failing tests, or a failing build all block merges. No deployment happens in this workflow; deployment is handled by SPEC-005 workflows, which trigger only on merge to `main`.

---

## Scope

### In Scope

- GitHub Actions workflow: install dependencies, lint, run unit tests, production build
- Triggered on every push to any branch and on pull requests targeting `main`

### Out of Scope

- Deploying to AWS (covered in SPEC-005)
- End-to-end or integration tests
- Caching of `node_modules` (can be added as a follow-on optimization)

---

## Functional Requirements

### FR-001: Workflow Trigger

#### Description:
The CI workflow runs automatically on every push to any branch and on every pull request targeting `main`. This ensures CI gates both PR merges and direct pushes to `main` (where SPEC-005 deploy workflows will subsequently fire).

#### Acceptance Criteria:
- [ ] Workflow file is at `.github/workflows/ci.yml`
- [ ] Workflow triggers on `push` to all branches (`branches: ['**']`)
- [ ] Workflow triggers on `pull_request` targeting `main`

---

### FR-002: Dependency Installation

#### Description:
Dependencies are installed from the repo root so all npm workspace packages are available.

#### Acceptance Criteria:
- [ ] `npm ci` is run from the repo root (not from `apps/portal/`)
- [ ] The step fails and stops the workflow if `npm ci` exits non-zero

---

### FR-003: Linting

#### Description:
ESLint runs against the `apps/portal/` workspace as a quality gate. A lint failure must fail the workflow and prevent subsequent steps from running.

#### Acceptance Criteria:
- [ ] `npm run lint` is run with `working-directory: apps/portal` before the test step
- [ ] A non-zero exit from `npm run lint` fails the workflow job
- [ ] Subsequent steps (test, build) do not run if lint fails

---

### FR-004: Unit Tests

#### Description:
The full Vitest unit test suite runs against the `apps/portal/` workspace. A test failure must fail the workflow.

#### Acceptance Criteria:
- [ ] `npm run test` is run with `working-directory: apps/portal` after the lint step
- [ ] A non-zero exit from `npm run test` fails the workflow job
- [ ] The test runner does not start a watch process — tests run once and exit (Vitest `run` mode, not `watch`)

---

### FR-005: Production Build

#### Description:
A production Vite build runs after tests pass to confirm the app compiles cleanly. No `VITE_*` environment variables are injected — the build is expected to succeed with missing env vars (values are undefined at build time, which is acceptable for CI verification).

#### Acceptance Criteria:
- [ ] `npm run build` is run with `working-directory: apps/portal` after the test step
- [ ] A non-zero exit from `npm run build` fails the workflow job
- [ ] The built output at `apps/portal/dist/` is not uploaded or deployed — CI only

---

## File & Folder Structure

```
.github/
└── workflows/
    └── ci.yml
```

---

## Workflow Sketch

Structural outline for the implementer — not final YAML.

```
name: CI

on:
  push:
    branches: ['**']
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - checkout
      - setup Node (pin to version matching package.json engines or .nvmrc)
      - npm ci                          # run from REPO ROOT — installs all workspaces
      - npm run lint                    # working-directory: apps/portal
      - npm run test                    # working-directory: apps/portal (run mode, not watch)
      - npm run build                   # working-directory: apps/portal
```

---

## Implementation Phases

### Phase 1: CI workflow

- Create `.github/workflows/ci.yml` following the sketch above
- Confirm `npm run test` in `apps/portal/package.json` uses `vitest run` (not `vitest` with default watch mode)

#### Checkpoint

Open a pull request against `main`. The CI workflow triggers, `npm ci` completes at the repo root, lint passes, tests pass, and the build produces `apps/portal/dist/`. The Actions run shows green. Introduce a lint error in a second commit — confirm the CI run turns red and test/build steps are skipped.

---

## Open Questions

- [ ] Should Node.js version be pinned via `.nvmrc`, `package.json engines` field, or hardcoded in the workflow YAML?
