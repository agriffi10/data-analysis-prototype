---
type: Decision
title: "Both homes of a moving folder are admitted before either is written to (SPEC-219)"
description: "**A rule that builds its prefix from a PARAMETER is invisible to the app-managed-path sweep** — two were — so it owes a pair test instead. And **a pair test asserts which folder the refusal NAMES, not just its reason code**: once the parent prefix joins the same list, a rule that learned one home still refuses the other, same code, different rule. A pair test can also be structurally vacuous — where every second home is a descendant of a prefix already in the list, no key distinguishes the two builders, and only saying so keeps the test honest. What breaks a move of that folder is **depth**, not spelling: a `{root}{name}/` rule stops matching at depth two and denies nobody. `archive` is **three facts** and only the receipt folder moved; the vault segment and `arcommon.plan.PREFIX` stay, pinned equal by an `ACCEPTED_` tripwire."
---

> **The window this opened is CLOSED (SPEC-220, 2026-09-09).** Each folder has one home again: the
> objects moved, the old prefixes are proved empty and their statements are gone, so nothing below
> describes the current tree. It is kept because the SHAPE is the reusable part — admit additively,
> move, then narrow — and because the narrowing found what admitting additively could not: the
> builders carried every root-anchored rule and none of the six that scan segments. Read the
> [SPEC-220 entry](the-folders-moved-and-six-deny-mirrors-did-not-move-with-them.md) for what is true now.

Relocating an app-managed folder relocates two things at once: the IAM Deny keyed on its literal
path, and every rule that compares a key to that same path. The window between them is one in which
the data is writable and nothing fails, so this spec opened the destination first and left the
writes where they were.

**One PLURAL builder per tree beside the singular one.** `app_managed_prefixes` /
`appManagedPrefixes` return every root-anchored location a folder may occupy — two for a member of
the moving set while both homes are admitted, one for anything else. Every rule whose answer depends
on DEPTH goes through it; a rule that already reaches any depth by segment keeps the singular and is
asserted at the new home instead. The singular, which is where a write goes, is untouched.

**Both elements are literals, and neither is derived from the singular.** That duplication is the
whole mechanism: derived, moving the write would drag every rule's second home to a third location
that holds nothing. The invariant is not visible in any value — a derived home and a literal one
agree exactly while the singular is depth-one — so it is guarded directly: Python monkeypatches the
singular and asserts the plural is unmoved, TypeScript reads the function's own body, because a spy
cannot intercept an in-module call.

**A folder that is not moving gets exactly one location.** No phantom home: nothing treats
`{root}system_settings/user_settings/` as the settings folder. What refuses a paste or an archive
beneath the new prefix is the prefix's own membership of the reserved lists, by that name.

**Two acceptance criteria could not both hold, and the mechanism changed rather than the goal.**
Naming the reserved folder before anything beneath it, and naming `archive` for a key inside the
receipt folder's new home, are incompatible under one first-match loop. Splitting the direct and
beneath arms from the ancestor arm into two passes satisfies both, and the name is appended last
everywhere. In the browser the item loop stays outermost — hoisting it inside the passes lets a
later item's direct hit outrank an earlier item's ancestor hit, changing a shipped message, and
exactly one test stands between the two shapes.

**Traps this paid for.** A pair test can be structurally vacuous rather than under-specified: once
the parent prefix joins the same list, every second home is a strict descendant of it and no key
distinguishes the two tuples through `startswith` — the test proves the list membership and cannot
prove the re-pointing. And adding the parent to a list gives every rule a neighbour that refuses the
same fixture with the same reason code, so a pair test must assert which folder the refusal NAMES.

A rule that builds its prefix from a parameter is invisible to the app-managed path sweep, and two were, so such a rule owes a pair test instead.

## History

### 2026-09-09

- **Changed:** SPEC-220 closed the window: each folder has one home again, the old prefixes are proved empty and their statements are gone, so the entry describes the reusable shape rather than the current tree.

### 2026-09-06

- **Settled:** SPEC-219.
