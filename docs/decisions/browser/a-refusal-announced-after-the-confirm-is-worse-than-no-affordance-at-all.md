---
type: Decision
title: "A refusal announced after the confirm is worse than no affordance at all"
description: "An action that can never succeed is refused at the control through `Button.disabledReason`, so no confirm is reachable; `busy` stays natively `disabled`, because in flight is not a refusal."
---

`fileBrowser.service.ts` always refused deleting `saved_queries/` — but only after the user read
*"Delete the folder "saved_queries" and everything inside it? … This can't be undone."* and pressed
Delete. The most alarming confirm in the app, shown for an action that was never possible.

`undeletableSelectionRefusal` feeds `Button.disabledReason` (SPEC-172's `aria-disabled` affordance),
and because `Button` swallows the click, **"no confirm is reachable" falls out of the mechanism**
rather than needing a second guard. `ConfirmDialog` gained `confirmDisabledReason` on the same
pattern for the refresh dialog's opt-in — `busy` still wins and stays natively `disabled`, because
an operation in flight is not a refusal.

The test asserts **`alertdialog`**, not `dialog`: the confirm carries the former, so querying for
the latter would have passed whatever happened. A negative assertion has to name the thing it is
denying.

## History

### 2026-08-14

- **Settled:** entered the register.
