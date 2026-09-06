# Completed Spec — SPEC-219: Admit `system_settings/` Additively

## What was completed?

Nothing a user can see, and no path a write produces changed. Three folders — `athenaresults/`,
`archive/` (the receipt folder) and `shared_tables/` — are moving under a real `system_settings/`
prefix. For two of them what makes the folder uneditable **is** an IAM Deny keyed on the literal
path, and for all three what stops a paste, a delete or an archive is a rule comparing a key to that
same path. Relocating the prefix relocates all of it at once, and the gap between the two is a
window in which the data is writable and nothing fails. This spec closed the window before it
opened: every statement and every rule learned the new location as a second, equally protected home,
while every write still goes to the old one.

- **The IAM templates** (PR 1) — every space-bucket statement naming a moving folder gained a
  sibling naming the same folder under `system_settings/`, across the nine templates
  `SPACE_BUCKET_POPULATION` pins, plus six guards over them.
- **The results-conversion plane** (PR 1b) — its execution role gained a Deny on
  `*/system_settings/*` itself in both buckets. Not a sibling of anything: it names the folder the
  three move *into*, and it was forced by that plane holding its refused set against the browser's
  picker — an equality when this spec started, an inclusion plus an enumerated difference by the
  time it finished, because SPEC-222 gave the equality up on purpose. Either shape demands the
  Deny.
- **One PLURAL builder per tree** (PR 2) — `app_managed_prefixes` / `appManagedPrefixes`, beside the
  singular one. Every root-anchored rule goes through it — ten call sites in the fleet, four in the
  browser — while the rules that already hold at any depth were asserted against the new home rather
  than re-pointed, and data quality's first-segment rule was **extended by list** instead, since
  reaching any depth was never its problem. FR-002 enumerates all three sets; a count here would rot
  the next time a plane lands, which is exactly what happened to this spec's own template count
  mid-build.
- **`system_settings` joined the reserved sets** on both sides: never a paste target, never
  deletable or renamable, never an archive source, never a data-quality target, never a conversion
  destination.

## What changed from the spec as written?

**Two acceptance criteria could not both hold, and the mechanism changed rather than the goal.**
FR-002 asked for `system_settings` FIRST in the reserved list so the folder itself would be named
before anything beneath it; FR-003 asked for `{root}system_settings/archive/` to be named `archive`.
Under one first-match loop, prepending names `system_settings` for *every* key under the prefix.
Splitting the direct and beneath arms from the ancestor arm into **two passes** satisfies both, so
FR-002's ordering clause was amended and FR-003's naming clause was delivered as written. The name
is appended last everywhere. Verified behaviour-preserving for today's inputs: the ancestor arm can
only fire for the space root, which matches no folder's direct arm.

**A plane that did not exist when the spec was authored** joined the population mid-build
(results-conversion, `2a526959`). It cost an extra PR and two spec amendments, and it is the second
time this arc has paid for a template landing between authoring and delivery.

**Scope added mid-build**: the cross-tree mirror guard. `focommon/config.py` said in prose that a
test held its protected-folder lists equal to the browser's; no such test existed in either tree,
and this spec appends to both lists. It exists now, with a three-shape resolver, and `ci.yml`'s
scope patterns grew the file it reads — without which a PR touching that file skips the portal suite
and reports green.

## Rollback

**The empty change.** Reverting the rule PRs leaves the sibling statements inert: nothing is written
under `system_settings/`, so a Deny naming it refuses nothing and an Allow grants access to an empty
prefix. Reverting the templates PR is a plan that removes statements matching nothing. The state
this spec produced *is* the rollback for SPEC-220, which is the whole reason it is separate.

## What is owed

The route-layer half of FR-004: a `PUT /v1/objects/content` under `{root}system_settings/archive/x`
must be refused by the **route layer** with the same code as under `{root}archive/x`. It needs a
signed-in session, so `e2e.md`'s API table carries the recipe beside its `{root}archive/` twin and
`owed.md` §1 carries the obligation. It is not proxied by an offline test: the predicate is unit
tested at both homes, which says nothing about whether the route consults it. The IAM half is
discharged in `owed.md`, measured before and after the apply — the before column is the evidence.
