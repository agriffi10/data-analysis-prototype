---
type: Decision
title: "Compiler and coverage defaults are declared, never inherited (SPEC-150)"
description: "Coverage floors and `\"strict\": true` are **declared, never inherited**. The floors are a flat **85**, no longer ratchets at the measured level — a ratchet fails CI on any deliberate reduction in test volume, and is bought back by testing internals. Never lower one for a regression, and never read a floor as evidence a guard exists: four mutations of production code once passed the whole suite with coverage unchanged. **Mutate the guard instead.**"
---

`tsconfig.app.json` and `tsconfig.node.json` state `"strict": true` even though TypeScript 6 already
defaults it on, and both suites carry **literal** coverage floors. Adding the `strict` key changed
**zero** errors — that is the point, and a build that finds otherwise should stop and re-derive the
premise rather than "fix" the errors.

This reverses the implicit trade-off of leaving a default alone because it happens to be correct.
`pyproject.toml`'s ruff block is the precedent and says it outright — "THE RULE SET IS CHOSEN HERE,
NOT INHERITED" — after ruff 0.16 widened its own default set from 59 rules to 413 overnight and
turned `main` red with 500 findings in files nobody had touched (#311). A default is a decision
*someone else* gets to change; strict is this project's single most important type guarantee, and it
does not ride on one.

The coverage floors are the same principle pointed at a different kind of erosion: both suites
measured coverage and neither gated on it, so deleting tests passed CI identically to keeping them.
They are hard-coded literals on purpose. Nothing computes, inherits or reads them from a file, so
changing one is a visible one-line diff in review rather than a number that drifted.

> **Superseded — the ratchet is gone; the floor is flat 85.** They were ratchets at the measured
> level (portal 91/86/89/93, lambdas 95) until the suites were rewritten around entry points rather
> than around individual functions. A ratchet at the measured level makes any deliberate reduction
> in test volume fail CI, which is the opposite of what was wanted, and it rewards adding tests
> around internals to buy back a tenth of a point. Both suites now sit at a flat **85** and stay
> there: raise it only with a reason that is not "coverage happens to be higher today", and never
> lower it to accommodate a regression.
>
> **What that costs, measured.** A coverage floor was never a measure of guard strength, and the
> review of that rewrite proved it: four separate mutations of production code — an archive
> rollback default that routed to deletion, a route minting its own AWS client, the CI watcher
> reporting a red run green, and a verb losing its `@traced` — each passed the full suite with
> total coverage unchanged to the hundredth of a point. **Mutate the guard; do not ask coverage
> whether it exists.**

**Do NOT read this as "enable strict"** — it was already on. The work is *declaring* an inherited
default, which is a much smaller and different thing.

**The typecheck gate itself is separate and already shipped** (#363): `ci.yml` runs `npm run build`
on every PR. Two traps are recorded in that file's header comment and should be read before touching
it — vitest does not typecheck, and `tsc --noEmit -p apps/portal/tsconfig.json` **exits 0 having
checked nothing**, because that config is solution-style (project references only, no
`files`/`include`). `tsc -b` is the only invocation covering the app *and* its `*.test.tsx` files.
SPEC-150 confirmed the gate empirically on a scratch PR: with the #361 defect reintroduced, Lint and
Format check passed, **Build failed**, and Test was skipped.

## History

### 2026-08-05

- **Settled:** SPEC-150.
