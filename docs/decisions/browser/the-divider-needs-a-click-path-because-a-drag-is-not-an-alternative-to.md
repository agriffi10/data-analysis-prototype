---
type: Decision
title: "The divider needs a click path, because a drag is not an alternative to itself (SPEC-209)"
description: "**A drag is not an alternative to itself.** WCAG 2.5.7 wants a *single-pointer, non-dragging* path; a keyboard is not one and **no axe rule detects the absence**, so a drag-only control regresses it in silence — and a pointer path that only *resets* to a default is not one either, because it restores neither the chosen value nor the drag's functionality. Sizing the replacement is its own trap: the root font is **14px**, so `rem` spacing lies about the 24px minimum — write an absolute threshold in an absolute unit. jsdom can measure no target at all, which is why `target-size` is **disabled rather than trusted** and a static sweep covers what a class name can answer."
---

The separator is a focusable widget with arrow/`Home`/`End` operation, so **2.1.1 Keyboard** holds,
and the step buttons are drawn at the **2.5.8 Target Size** minimum. That minimum is in **CSS px and
the app's root font-size is 14px**, so Tailwind's rem spacing lies about it: `h-6` is 21px, not 24,
and the buttons shipped that way until it was measured in a browser. They are sized in px now and the
band is tall enough to hold them. jsdom reports axe's `target-size` rule as a **pass** because it has
no layout. Be exact about what that rule was: not a limitation, a **vacuous guard** — an enabled rule
advertising coverage it cannot provide, which is worse than a disabled one, because the suite reads
as checking something it never checks.

**Superseded on the last clause, 2026-09-01:** the rule is now **disabled** with its reason, and a
static sweep covers the part a class name can answer. "Nothing can catch this automatically" no longer holds
for a control sized from the spacing scale (the sweep is a Vitest test, so it is the pre-push run
that catches it now, not CI — `docs/process/ci-and-deploy-traps.md`) — it does still hold for one whose height is its line box
plus padding, and for whether the spacing exception covers a small target. See
*An axe rule that cannot measure is disabled, and what replaces it* in
[`docs/decisions/gates-and-tests/`](../gates-and-tests/).

Neither of those answers **2.5.7 Dragging
Movements**, which asks for a *single-pointer, non-dragging* alternative specifically — keyboard
support is not one, and no axe rule detects the absence, so nothing in CI would have said so.

**The retired `EditorLayoutControl` was that alternative:** three `onClick` buttons setting the split
three ways. So this surface met 2.5.7 before the spec, and a drag-only divider would have *caused* a
regression rather than inherited one. That distinction is the whole reason the divider carries a pair
of step buttons — they were added mid-build, on a user decision, and they are the only new product
surface in the spec.

**`ColumnResizeHandle` is the other case and stays open.** Be exact about what it does offer, because
"no pointer path at all" is wrong and was asserted here before it was checked: a **double-click
resets** the width to its default (`onDoubleClick` → `onReset`, wired in both grids since SPEC-064).
That is a single-pointer, non-dragging action, but it restores a default rather than *choosing* a
width — so it is not an alternative to the drag's functionality, 2.5.7 is still unmet, and the result
grids are a standing gap this spec neither widens nor closes. Do not read the two
as one finding: one was a regression to prevent, the other is somebody else's spec.

**The buttons are the separator's SIBLINGS, not its descendants — and both of the obvious
alternatives fail in ways that look fine.** Nesting them inside is invalid: a focusable separator is
a widget, and a widget may not contain focusable content. Nothing about the rendered result says so;
axe's `nested-interactive` failing the route check is what caught it. Filtering instead — guarding
the separator's handlers with `e.target !== e.currentTarget` so a button click cannot start a drag —
is *worse* than invalid, because it is wrong at exactly the point users aim: the visible grip is a
**child** of the separator, so the guard ignores a grab on the grip while every test that grabs the
band still passes. Siblings in a plain wrapper band answer both at once, and need no filtering at
all.

## History

### 2026-09-01

- **Settled:** SPEC-209.
- **Changed:** axe's `target-size` rule, a vacuous guard under jsdom, was disabled with its reason, and a static sweep covers what a class name can answer.
