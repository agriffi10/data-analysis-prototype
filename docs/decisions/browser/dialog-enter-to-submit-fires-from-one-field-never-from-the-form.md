---
type: Decision
title: "Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)"
description: "**Dialogs:** Enter submits from **one** field, not implicitly; Escape dispatches by **tree depth** through one registry, and a busy modal swallows it. `cx()` returns `undefined`, never `''` — `??` does not fall back on the empty string, and that cost nine dialogs their width. **The one irreversible surface refuses the affordance that would fire it.** The archive dialog is built on the confirm dialog *because* the form dialog has Enter-to-submit — focus sits on Cancel, Enter cancels — and it never says \"this can't be undone\", which would be its one false sentence."
---

`FormDialog` (SPEC-155 FR-002) turned eleven hand-written dialog chromes into one. Its body is a real
`<form>` with a `type="submit"` primary button — but **the browser's implicit submission is
suppressed on purpose**, and Enter submits only from the field named by `submitOnEnterRef`
(defaulting to `autoFocusRef`).

Adopting the form naively is the trap: implicit submission fires from *every* text input in a form.
The dialogs being consolidated each had exactly one field that submitted on Enter; handing it to all
of them filed a table build from a partition-key row the user was still editing — **measured before
the fix, not hypothesised**. A radio group is the same shape: arrow keys move a choice, Enter would
commit one the user never made.

A child that already handled the key wins over both, so a combobox's Enter-to-commit still works
inside a dialog.

The archive dialog is built on the confirm dialog *because* the form dialog has Enter-to-submit: focus sits on Cancel, Enter cancels, and it never says "this can't be undone", which would be its one false sentence.

## History

### 2026-08-06

- **Settled:** SPEC-155.
