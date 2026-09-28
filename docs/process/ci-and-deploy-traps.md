# Operational traps that only bite in CI / on deploy


These pass locally and fail later — check them as part of the work, not as an afterthought.

- **Six steps now fail NOWHERE but your machine** — lint, both suites and mypy are commented out in
  `ci.yml`, whose header names all six and carries the restore rule, so a green PR is no evidence
  any ran. `tsc -b` (via `npm run build`) is the only check CI still makes; `npm run test` never
  typechecks and `tsc -p tsconfig.json` checks nothing. The Python linter is `ruff check lambdas/
  scripts/ .github/scripts/` — **all three trees**; `pytest` never sees it. All, by exit code.
- **A fresh worktree borrows the parent's `node_modules`, so the JS gates pass wrongly. `npm ci`
  first** — a guard refuses them until you do.
- **Never hand-roll a CI watch.** `gh pr checks --watch` can exit clean against the **previous**
  commit's checks, and a hand-written shell condition inverted and printed "settled" while two
  deploys were still running — both reported a green that was not there. Use
  `python3 scripts/watch_ci.py --pr <n>` (or `--branch main` after a merge): every query is keyed to
  one resolved sha, so a stale-sha report is not expressible, and the "are we done" and "did it pass"
  decisions are unit-tested in `lambdas/test_watch_ci.py`. Exit 0 means settled **and** green, so it
  composes with `&&`; anything unfinished, unknown or absent exits non-zero. **A commit on `main` is
  judged by its push runs only**: Dependabot's jobs record `main`'s head too, and a failed one beside
  green deploys is not a red `main`, though an unfiltered `gh run list` shows it as one. The filter
  hides the weekly scheduled Security scan too; its result is
  `gh run list --workflow security.yml --event schedule --limit 1`. **Nor is the list a reliable
  read of the newest runs**: its endpoint intermittently serves a page weeks stale, and a head
  missing from that page reads as "no push run yet" while `main` is green. So every script that
  judges a commit asks `actions/runs?head_sha=` for it — `watch_ci.py`, the queue's `turn`, and the
  supervisor's watch and archive check. The session-start check's verdict is
  `python3 scripts/watch_ci.py --branch main --once`. Then it reads what the head's own runs may
  not include — each path-filtered deploy's last outcome — one workflow at a time, because the two
  image deploys run on every push and crowd the others out of any short repo-wide list. Run this
  twice and keep, per workflow, the row with the newer `createdAt`:

  ```bash
  for w in deploy-infra deploy-lambdas deploy-config; do gh run list --workflow $w.yml --branch main --event push --limit 1 --json workflowName,conclusion,headSha,createdAt; done
  ```

  It is best-effort context, never the verdict: this endpoint has served a run weeks stale too,
  and a path-filtered deploy's newest run is rarely main's head, so nothing proves one read fresh.
  A red row is a failure to investigate; a green one proves nothing.
- **Vitest needs the Vite config for jsdom.** Running vitest with an explicit file path *from the repo
  root* uses no Vite config → `document is not defined`. Run from `apps/portal` or via
  `npm run test -w apps/portal`.
- **`import.meta.env.VITE_*` read at module top level** is captured at import — `vi.stubEnv` in
  `beforeEach` is too late and CI has no `.env`. Stub at top level **and dynamic-import** the module.
- **A new configuration key is wired in FIVE places, and none of them is a build env.** Production
  reads a runtime `/config.json`; a `VITE_*` value is the **dev
  fallback only**, and `npm run check:bundle` asserts the production bundle carries no `VITE_` names
  at all. Wiring the build env and stopping there ships a key that exists nowhere the browser can
  see it. The list — including the container entrypoint's own `KEYS`/`REQUIRED`, which is what
  decides whether the container starts — is
  [`apps/portal/info/runtime-configuration.md`](../../apps/portal/info/runtime-configuration.md).
  **The third site is no longer "a repository variable":** a value Terraform computes is read from
  state through `.github/config-outputs.json`, and only a genuine **input** — one Terraform is given
  rather than derives — is still a variable. Putting a derived value back in the settings page
  reinstates the failure the resolver exists to prevent, and it fails quietly, because an unset
  variable interpolates to the empty string, which satisfies a required Terraform variable and
  overrides its default.
- **`lambdas/` has a second local-only gate beside ruff: `mypy` is BLOCKING** at zero errors over
  the shared layers, the API and the contract generator. The list is `pyproject.toml`'s
  `[tool.mypy]` `files` block and nowhere else — a **new shared layer joins the ratchet with the
  spec that creates it**: added later it is a baseline to argue about, added now it is free.
- **Never `tofu apply` from a laptop.** The deploy role is GitHub-OIDC-only and the local CLI
  identity is an IAM *user* that is on no data bucket's policy allowlist, so tofu reads those
  buckets as **absent** and plans to destroy and recreate them (measured: `25 to add, 3 to change,
  13 to destroy`). The same isolation is why `get-object` on the user-space bucket returns
  `AccessDenied` from a laptop — that is the model working, not a fault.
- **Adding a new AWS resource type to `infra/`** trips a recurring set of deploy-role IAM traps
  (self-grant propagation, non-scopable actions, refresh deadlocks, unknown-ARN-in-list). Read
  [`infra/info/deploy-role-iam.md`](../../infra/info/deploy-role-iam.md) **first**, and treat the IAM
  expansion as in-scope work for the spec.
- **Adding or rewiring a Lambda** has its own split — Terraform owns the function, CI owns the code
  and which image it runs — and its own deploy-time traps:
  [`lambdas/info/deployment.md`](../../lambdas/info/deployment.md).
