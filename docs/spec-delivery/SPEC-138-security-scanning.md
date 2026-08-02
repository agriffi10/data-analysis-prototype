# Completed Spec — SPEC-138: Security Scanning

## What was completed?

- **`.github/workflows/security.yml`** — seven jobs: `gates`, `sast` (Semgrep), `deps-npm`,
  `deps-python`, `secrets` (gitleaks), `iac` (Checkov), `dast` (OWASP ZAP baseline). PR + weekly
  schedule + dispatch; ZAP is schedule/dispatch only.
- **`.github/scripts/apply-gate.sh`** — the single gate. One `GATE_*` env value per scanner, all
  `report`. An unrecognised value or a non-numeric count exits 2 rather than degrading to
  report-only. `gates` validates all six before any scanner runs.
- **`.github/scripts/summary-section.sh`** — the job-summary writer. A zero-finding scanner writes
  an explicit line; an empty section and a step that never ran must not look alike.
- **`eslint-plugin-security` + `eslint-plugin-no-unsanitized`** in `apps/portal/eslint.config.js`,
  and `lint` gained `--max-warnings 0`. This is the only **blocking** scanner in the spec.
- **`docs/security-baseline.md`** — the first run, every finding with a disposition, and a proposed
  blocking threshold per scanner. The follow-up spec's input.

**Deviations from the spec, both additive:**

- FR-002 gained two criteria during build. Semgrep partial-parse counts are published beside the
  finding count (five test files parse partially on `vi.fn<...>()`, so a region can be unscanned
  while the job prints "0 findings"), and a scanner exit ≥ 2 fails the job even under `gate=report`.
  The same "did not run ≠ clean" rule was then applied to every scanner, and to Checkov's
  `parsing_errors`.
- Checkov findings are summarised **grouped by rule**, not per resource — 305 failures over 25 rules,
  where 32 Lambdas missing one check is one decision, not 32.

## What changed from earlier specs?

- **`npm run lint` (SPEC-004) now fails on warnings.** Without `--max-warnings 0` the new security
  rules would have landed as non-blocking warnings and CI would have stayed green — the "blocking"
  claim would have been false.
- **`query.sql.ts` (SPEC-077/078)** — two `detect-unsafe-regex` disables added. Both regexes parse
  user-typed SQL, so they were measured rather than waved through: 200k characters of pathological
  input, linear, under 0.3 ms. The measurement is recorded at the disable.
- No behaviour change anywhere in the app or the Lambda fleet.

## Verification

Local: `npm run lint` (clean at `--max-warnings 0`), `format:check`, `build`, and the full suite —
161 files / 1186 tests green. Every scanner was run locally at its pinned version against the branch
head, and each summariser was dry-run against that real output: Semgrep 1 finding + 5 partial
parses, `npm audit` 4 runtime / 6 full, `pip-audit` 0 of 13, gitleaks 0 across 357 commits, Checkov
305 failed / 439 passed / 0 parse errors.

Deferred to CI/live: the first ZAP baseline (needs the deployed `VITE_APP_URL`; runs on the weekly
schedule or by dispatch), and confirmation that the workflow's own run reproduces the local counts.

**No user-facing change** — nothing in the portal UI changed, so the SPEC-074 Help & guides sweep is
a no-op.
