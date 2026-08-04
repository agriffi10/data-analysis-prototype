# Completed Spec - GitHub Actions CI

## What was completed from this spec?

A CI workflow at `.github/workflows/ci.yml` that runs on every push to every branch and on every pull request targeting `main`. The workflow installs all npm workspace dependencies from the repo root (`npm ci`), then runs lint, unit tests, and a production build sequentially inside `apps/portal/`. Any non-zero exit at any step fails the job and skips subsequent steps. No artifacts are uploaded. Node 22 LTS is pinned in the workflow (resolves the open question from the spec; no `.nvmrc` or `engines` field was added since the workflow is the only consumer of the Node version constraint).

> **Superseded 2026-08-04.** The workflow was not the only consumer — README's Prerequisites
> stated a version too, and a developer's local npm major decides the lockfile's `peer` metadata,
> which is how the drift surfaced. Node is now **24** in `.nvmrc`, read by every workflow via
> `node-version-file`, with `engines.node: ">=24"` in the root manifest.

## What has changed?

- `.github/workflows/ci.yml` created (new file — no prior workflows existed)
- `apps/portal/package.json` `test` script was already `vitest run` — no change needed
