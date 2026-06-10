# Completed Spec - GitHub Actions CI

## What was completed from this spec?

A CI workflow at `.github/workflows/ci.yml` that runs on every push to every branch and on every pull request targeting `main`. The workflow installs all npm workspace dependencies from the repo root (`npm ci`), then runs lint, unit tests, and a production build sequentially inside `apps/portal/`. Any non-zero exit at any step fails the job and skips subsequent steps. No artifacts are uploaded. Node 22 LTS is pinned in the workflow (resolves the open question from the spec; no `.nvmrc` or `engines` field was added since the workflow is the only consumer of the Node version constraint).

## What has changed?

- `.github/workflows/ci.yml` created (new file — no prior workflows existed)
- `apps/portal/package.json` `test` script was already `vitest run` — no change needed
