---
type: Decision
title: "An app-managed path is built by one function per tree, and a sweep refuses a second (SPEC-218, superseded in part by SPEC-219)"
description: "**An app-managed path is BUILT by three functions per tree** — the SINGULAR builder is where a write goes, the PLURAL one is every root-anchored comparison, and the SEGMENT one is every any-depth scan. The plural spelled both homes as literals while a moving folder had two, so that moving the write could not drag every comparison to a third place; with one home left it delegates, and each tree guards the delegation directly because no VALUE can tell a derived prefix from a literal one. A CI sweep refuses a declaration or construction outside the owners, and **no builder normalizes** (the FIFO group id digests one)."
---

Three folders the app fills for the user — `athenaresults/`, `archive/` (the receipt folder) and
`shared_tables/` — are moving under a real `system_settings/` prefix over three specs. The obvious
hazard is spelling: the names appeared as literals in four browser modules and eleven fleet modules.
The real hazard is **depth**. Nearly every rule about those folders was anchored at depth one, as
`` `${rootPrefix}${name}/` `` in the browser and `f"{root}{name}/"` on the planes, and at depth two
each comparison stops matching **silently** — a Deny-mirroring predicate that offers a write IAM
refuses, an exclusion that stops excluding, a reserved-root check that lets the folder be archived
and then deleted. `fscommon.authz` had already written the warning into its own docstring.

**The decision: the unit is a builder per fact, not a constant per name.** `lib/appManagedPaths.ts`
and `cpcommon/app_managed.py` declare the names and own the one depth-one anchor (`appManagedPrefix`
/ `app_managed_prefix`, with per-fact wrappers); every anchored construction calls it, so the move is
one edit per tree. Membership lists keep their members and only spell the moving names through the
owner — this changed how a path is *built*, never who is in a list, because the lists answer
different questions on purpose.

> **SUPERSEDED BY SPEC-219 on both counts.** There are now **two** builders per tree: the singular
> one is where a WRITE goes, the plural `app_managed_prefixes` / `appManagedPrefixes` is what every
> root-anchored COMPARISON calls, and ten fleet call sites plus four browser ones moved to it — so
> the move is no longer one edit per tree. And the membership lists **did** gain a member:
> `system_settings` joined five fleet lists and three browser ones, because the prefix the folders
> move into is itself reserved. See *Both homes of a moving folder are admitted before either is
> written to*.

**No builder normalizes.** Each is a pure string over what it is handed, and each caller keeps its own
`normalize_root`. The reason is the API's FIFO group id, which digests the vault prefix: a builder that
normalized would answer 500 on an empty space name the contract admits, and re-key the id for a
slash-carrying one. Byte identity was proved by comparing thirteen before/after strings, the FIFO
digests for empty, slash-carrying and ordinary names among them.

**`archive` is three facts, and exactly one moves.** The receipt folder (`RECEIPT_FOLDER`, space
bucket, moves) and the Glacier vault's key segment (`VAULT_ARCHIVE_SEGMENT`, archive bucket, hashed
into FIFO ids, stays) live in `cpcommon` because two packages each need them. The admin bucket's
control-plane scratch prefix stays as `arcommon.plan.PREFIX`: one consumer, pinned by its own layer
against the IAM grant and the lifecycle rule, and a domain layer owns its constants. An `ACCEPTED_`
tripwire pins all three equal today and says *revisit when the receipt folder moves — do not delete*.

**The population is pinned, not derived.** `test_app_managed_template_population.py` spells the
IAM templates naming a moving folder in a space bucket — eight when this was written, nine since the
results-conversion plane joined the trunk during SPEC-219 — per file, per folder **and per anchoring
segment** (so a path replaced in place reddens it, not only a file joining), and separately the two
naming the admin bucket's `archive/*` that must never gain a sibling. The asymmetry it records
decides the next spec's shape: shared-space Denies are `*/athenaresults/*` and an S3 `*` matches
`/`, so they keep matching after the move; personal ones are anchored at the principal tag and stop
— the unprotected window at cutover is personal-space-only.

**A sweep, not a review, holds it.** `scripts/validate_app_managed_paths.py` refuses a new declaration
or construction outside the owners: Python by AST (a folder-name constant, an f-string or
concatenation building the prefix — from a literal or from an imported name — a module-level
`"archive"`, or `"archive"` beside another managed name in a collection), TypeScript by regex over
comment- and regex-literal-stripped source. It is scoped to **construction**, never to the word:
`archive` is also a mode, a service name and dozens of user-facing sentences, and a bare `'archive'` in TypeScript
is refused only beside another managed name or as a module-level `const`. Its fixture corpus asserts
the *reason* each rule reports and silence on the shapes it must not flag, and every rule and the CI
wiring were mutation-tested. Do **NOT** widen it to the word, and do **NOT** union the membership lists.
What shipped, module by module: `docs/spec-delivery/SPEC-218-one-builder-per-app-managed-path.md`.

An app-managed path is built by three functions per tree: the singular builder is where a write goes, the plural one is every root-anchored comparison, and the segment one is every any-depth scan. With one home left the plural delegates to the singular, and each tree guards the delegation directly because no value can tell a derived prefix from a literal one.

## History

### 2026-09-06

- **Settled:** SPEC-218, superseded in part by SPEC-219.
