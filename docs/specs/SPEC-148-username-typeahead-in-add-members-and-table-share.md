# Spec: Username Typeahead in Add Members & Table Share

**ID:** SPEC-148
**Status:** Completed
**Last Updated:** 2026-08-03
**Depends On:** SPEC-147 (`UsernameCombobox`, `UsernameChipsField`, `useUserDirectory`, `parseMemberInputDetailed`), SPEC-053 (`AddMembersDialog` and `useManageMembers`), SPEC-075 (the member roster this dialog sits over), SPEC-093 (`TableShareDialog` and its recipient chips)

> **Reference:** third and last of the username-directory arc (146 → 147 → **148**). This is the only spec in the arc a user can see.
>
> **Browser-side only: no new IAM, no new AWS call, no new Lambda change, no new env var, no request-contract change.** Both dialogs enqueue exactly the messages they enqueue today; only the way the names are collected changes.
>
> **The scope fence that matters:** this spec replaces two *inputs*. It does not change what either dialog submits, what either pipeline validates, or what happens to a name the pipeline does not recognise — which, importantly, is **not** silence: `add_members.py` notifies the owner by name and table-share reports unresolved recipients. See the Overview.

## Overview

Two dialogs in this app ask a user to name other users, and both ask by free text. Adding members to a shared space is a `<textarea>` with a comma-hint placeholder; sharing a table is an input with an Add button and removable chips. Both run `parseMemberInput`, which lowercases, dedupes and **silently drops** anything failing the catalog-safe pattern.

What happens to a name that is well-formed but wrong is better than the code's own comments suggest. `add_members.py` catches `UserNotFoundException` and queues a notification to the space owner naming the user it could not add; `TableShareDialog`'s help text already tells users that unknown names come back as a notification. So the typo is reported. But it is reported **late, asynchronously, and only to the owner** — the round trip through the control plane takes minutes, the person you were adding still is not in the space, and if you were not the owner you never find out at all. That is the cost this arc removes: with the directory in place, the browser can flag the name as you type it.

This spec wires `UsernameChipsField` into `AddMembersDialog` and `UsernameCombobox` into `TableShareDialog`'s user-kind entry.

It also surfaces something `parseMemberInput` has been swallowing since SPEC-053. Silently dropping `Bob Smith` is the wrong behaviour in a component that can now afford to say something, so under the new field an invalid token stays in the input with the standard rule sentence instead of vanishing.

The two dialogs stay different where they genuinely are. `TableShareDialog` can target a **shared space** as well as a user, space names are not in this directory, and its chips are one **combined** list mixing both kinds with badges. So its kind toggle keeps working, the space entry keeps its free-text path, and the combined list stays a single list — which is why it takes the combobox rather than the chips field.

---

## Scope

### In Scope

- **`AddMembersDialog`** — the `<textarea>` is replaced by `UsernameChipsField`; the live help line, the existing-member exclusion and the disabled-until-valid Add button are preserved in behaviour.
- **`TableShareDialog`** — the `user`-kind entry becomes `UsernameCombobox` feeding the dialog's **existing** combined chip list; the `space`-kind entry keeps its current free-text input with no suggestions.
- **Invalid tokens surfaced rather than dropped**, via SPEC-147's paste rule.
- **The "not in the directory" note** on a committed unlisted name, per SPEC-147 FR-005 — non-blocking, and absent while the directory is loading or unavailable.
- **Help & guides content** — the first user-visible change in the arc, so SPEC-074's sweep lands here.
- **Responsive and a11y passes** on both dialogs at 400px, including the three-Escape order in the live composition.

### Out of Scope

- **A space-name directory or space suggestions.** `TableShareDialog`'s space kind stays free text. A shared-space directory is a plausible follow-up from bucket 2's prefixes plus the registry, and it is a different list with different membership semantics.
- **`parseMemberInputDetailed`** — SPEC-147 adds it; this spec only consumes it.
- **Any change to what is enqueued.** Both dialogs send the same message shapes with the same fields.
- **Any change to how unknown users are handled server-side.** The existing notifications stay exactly as they are. Improving them is a separate decision.
- **Validating a name against the User Pool from the browser.** The portal role has no Cognito grant and should not get one for this.
- **The `CreateSharedConnectionDialog` space-name field**, `CreateViewDialog`, `CreateTableDialog`, or any other `CATALOG_IDENTIFIER_RE` input. They name new things, not existing users; a suggestion list would be actively wrong.
- **Backfilling suggestions into the roster or member-management displays.** Read-only lists are unaffected.

---

## Functional Requirements

### FR-001: `AddMembersDialog` collects members as chips with suggestions

#### Description

The bigger change of the two, because it is not currently a chips field at all. Everything the dialog does today has an equivalent under `UsernameChipsField`; the criteria enumerate them so none is lost in translation.

#### Acceptance Criteria:

- [ ] The `<textarea>` is replaced by `UsernameChipsField` with `label="Usernames"` and `listLabel="Members to add"`, in its default `renderChips` mode.
- [ ] The dialog's **existing** `existing` prop — which `ManageMembersDrawer` populates with `members.map(m => m.username)` and which **already includes the owner** — is passed straight through as `exclude`. Excluded names neither appear as suggestions nor commit as chips, and the refusal reason says the user is already a member.
- [ ] This is a like-for-like translation of today's filter, not a new restriction: the drawer is owner-only and already filters against that same set client-side. The criterion exists because the *reason* is easy to misattribute to the pipeline's `normalize_members`, which drops the owner for its own reasons and is not what the dialog relies on.
- [ ] The live help line is preserved in substance — the count and names of what will be added — and may be simplified where the chips now carry that information. It must still read exactly `No valid new usernames yet.` in the empty state, because that sentence is what tells a user their input did not take.
- [ ] The **Add** button stays disabled until at least one chip is present.
- [ ] The dialog's busy-lock, non-dismissible-while-submitting and `Modal` composition are unchanged.
- [ ] The enqueued `{action: 'add_members', payload: {members}}` message carries **the same fields with the same values** for the same set of names, `requestId` aside — the service mints a fresh `crypto.randomUUID()` per call, so byte-identity is not achievable and is not the claim. A test written against the pre-spec expectation asserts the field-by-field equality.
- [ ] `vitest-axe` reports no violations in the empty, populated and submitting states.

### FR-002: `TableShareDialog` takes the combobox, keeps its own chip list

#### Description

This dialog renders **one** `<ul aria-label="Recipients">` mixing user and space chips with kind badges. Handing chip rendering to `UsernameChipsField` would produce a second list beside it, so the user-kind entry takes the single-value `UsernameCombobox` and the dialog keeps rendering its own list exactly as it does now.

#### Acceptance Criteria:

- [ ] When the kind toggle is `user`, the entry field is `UsernameCombobox`; `onCommit` and `onCommitMany` both add to the dialog's existing recipient state.
- [ ] **The user entry stays a bulk field.** Today it runs `parseMemberInput(entry)` and its placeholder is `e.g. bob, cara`, so `bob, cara` in one go must still produce two chips — that is what `onCommitMany` is for (SPEC-147 FR-004). A test pins it.
- [ ] **The Add button is kept**, for both kinds. Enter-to-commit is added, not substituted: the button is the discoverable affordance and removing it would be a silent UX regression in a dialog this spec is only meant to be improving.
- [ ] When the kind toggle is `space`, the existing free-text `Input` + Add behaviour is used unchanged, with **no suggestions and no unlisted-name note**.
- [ ] The **combined** chip list stays a single list with its kind badges, its `font-mono` names, and its `Remove {kind} {name}` control labels — all unchanged.
- [ ] Switching the toggle does not clear already-committed recipients of either kind; today's per-kind dedupe is preserved.
- [ ] The current user is **not** excluded — sharing a table to your own database is a legitimate action the pipeline allows, and the field must not invent a restriction the control plane does not have.
- [ ] The `Table name for recipients` field and its `CATALOG_IDENTIFIER_RE` validation are untouched.
- [ ] The enqueued `TableShareRequest` carries the same fields with the same values for the same recipients — asserted by a test.
- [ ] `vitest-axe` clean for both toggle states.

### FR-003: Invalid tokens are surfaced, not swallowed

#### Description

A deliberate behaviour change, small and worth stating. Today `parseMemberInput` drops `Bob Smith` and `alice@corp.com` without comment, so the user watches half their paste disappear.

#### Acceptance Criteria:

- [ ] Pasting or typing a list into either field commits every valid token and leaves the invalid tokens in the input, joined by a space.
- [ ] The field shows the existing `CATALOG_IDENTIFIER_RULE` sentence as the reason, from its single source in `features/query/query.constants.ts`. No new wording is written.
- [ ] `parseMemberInput` is unchanged and its existing tests pass unmodified — SPEC-147 added the detailed variant beside it, and `TableShareDialog`'s space path keeps using the original.
- [ ] A test covers a paste mixing valid names, an invalid name, a duplicate and an excluded name, asserting each lands in the right place.

### FR-004: Directory states behave at the dialog level

#### Acceptance Criteria:

- [ ] While the directory status is `'loading'`, names commit normally and **no note is shown** — a note appearing a second later, after the name was accepted, reads as a delayed rejection.
- [ ] When the status is `'unavailable'` — the fetch errored, or the document is empty — both dialogs behave exactly as they do today: free text, no suggestions, no note, no error banner. A test asserts a rejected directory fetch leaves both dialogs fully functional.
- [ ] The note never disables Add, Share, or any control.
- [ ] A test asserts a valid unlisted name can be committed and submitted in both dialogs, in all three statuses.

### FR-005: Help and guides

#### Acceptance Criteria:

- [ ] The shared-spaces guide and the table-share guide describe suggestions: that typing suggests existing usernames, that the list is refreshed daily, and that a name not in the list can still be entered and will be checked when the request is sent.
- [ ] The guides state what already happens to an unrecognised name — that the request reports it back **as a notification**, and for a shared space that the notification goes to the **owner**. This is existing behaviour that the shared-spaces guide has never documented; `TableShareDialog`'s own inline help already says it, and the two should agree.
- [ ] **`AddMembersDialog`'s inline copy is corrected in the same pass.** It currently renders `Unknown usernames are ignored.` — the same false claim SPEC-146 fixed in two docstrings, and the only place a *user* reads it. It is replaced with wording matching `TableShareDialog`'s: unknown names are reported back as a notification. This lands here rather than in 146 because 146 does not touch this component and this spec rewrites the field directly above the sentence.
- [ ] Only shipped, wired behaviour is documented (SPEC-074 FR-005).

### FR-006: Responsive and the Escape order

#### Acceptance Criteria:

- [ ] Both dialogs reflow on one tree with `tablet:` / `desktop:` only.
- [ ] At 400px, in `AddMembersDialog` inside `ManageMembersDrawer` — a field inside a **Modal** inside a **Drawer** — the suggestion list stays within the panel, the panel scrolls rather than the page, and the confirm control remains reachable with several chips committed.
- [ ] The Escape order holds in the live composition: the first Escape closes the suggestion list, the second closes the dialog, the third closes the drawer. SPEC-147 FR-004 specifies the mechanism and tests it in isolation; this criterion verifies it in the real tree, where `ManageMembersDrawer` also gates `closeOnEscape` on `!addOpen && !removing`.

### FR-007: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run test` and `npm run lint` pass.
- [ ] Tests are integration-style via `renderWithProviders`, mocking only the S3 boundary and the enqueue services.
- [ ] Coverage includes: both dialogs' enqueued payloads field-by-field unchanged; the `exclude` set in `AddMembersDialog` including the owner; the current user **not** excluded in `TableShareDialog`; the kind toggle switching suggestions off and the combined chip list surviving; the FR-003 mixed paste; all three directory statuses in both dialogs; the FR-006 Escape order; and axe assertions in every state listed above.
- [ ] The existing `AddMembersDialog` and `TableShareDialog` suites are updated rather than replaced, so any behaviour they pinned that this spec did not intend to change fails loudly.

---

## Data Model

No new types, and no change to either request shape:

```ts
// features/shared-spaces — the enqueued body is UNCHANGED:
//   {schemaVersion, requestId, action: 'add_members', actor, space,
//    payload: {members: string[]}, idToken}
//   `requestId` is a fresh crypto.randomUUID() per call, so tests assert
//   field-by-field equality rather than byte-identity.

// features/table-share/tableShare.types.ts — UNCHANGED
//   ShareRecipient = { kind: 'user' | 'space'; name: string }
```

---

## API / Interface Contract

No new exports. This spec consumes SPEC-147's:

```ts
import { UsernameChipsField } from '@/components/UsernameChipsField';   // AddMembersDialog
import { UsernameCombobox } from '@/components/UsernameCombobox';       // TableShareDialog
import { useUserDirectory } from '@/features/user-directory';
```

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/features/
├── shared-spaces/
│   ├── AddMembersDialog.tsx            # textarea → UsernameChipsField
│   └── AddMembersDialog.test.tsx       # updated, not replaced
├── table-share/
│   ├── TableShareDialog.tsx            # user-kind entry → UsernameCombobox;
│   │                                   #   combined chip list and space kind unchanged
│   └── TableShareDialog.test.tsx       # updated, not replaced
└── help/
    └── helpContent.ts                  # + suggestion behaviour and the existing
                                        #   unknown-name notification, in both guides
```

## Implementation Phases

### Phase 1: `AddMembersDialog`

- Swap the textarea for `UsernameChipsField`, passing the existing `existing` prop as `exclude`; preserve the help line, its empty-state sentence and the disabled-until-valid rule.
- **Tests:** the field-by-field payload assertion; the exclusion including the owner; the empty-state sentence; axe in three states.

### Phase 2: `TableShareDialog`

- Replace the user-kind entry with `UsernameCombobox` feeding the existing recipient state; leave the space kind and the combined chip list alone.
- **Tests:** the payload assertion; the toggle switching suggestions off; per-kind dedupe, badges and `Remove {kind} {name}` preserved; axe in both states.

### Phase 3: Directory states, responsive, closing out

- The FR-004 loading and unavailable behaviours in both dialogs.
- Responsive pass at 400px and the FR-006 Escape order in the live tree.
- Help content (FR-005).
- Completion ritual for the spec **and the arc**: `INDEX.md` statuses, delivery doc, component-inventory rows for the changed dialogs, and confirmation that SPEC-146's two `decisions.md` entries — the S3-not-Cognito source and the accepted all-users disclosure — are in place with their one-line `CLAUDE.md` rows, then prune `CLAUDE.md`'s Current-work block of everything the arc made stale.
