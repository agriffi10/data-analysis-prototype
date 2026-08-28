# Spec: Shared-Space Suggestions from the Local Cache

**ID:** SPEC-158
**Status:** Completed
**Last Updated:** 2026-08-09
**Depends On:** SPEC-147 (`UsernameCombobox`, whose data source this generalises), SPEC-148 (`TableShareDialog`'s current wiring), SPEC-051/052 (the per-user shared-connections cache this reads), SPEC-093 (the dialog's combined recipient list)

> **Browser-only. No Lambda, no published document, no IAM, no env var, no new AWS call** — the
> data is already in the browser, fetched by `useConnections` for the Connections page and the
> Query rail.
>
> **This is a small spec on purpose,** and it exists for one reason that is not its size: it
> changes the contract of a shared component two features already depend on.

## Overview

`TableShareDialog`'s **Shared spaces** entry is free text. SPEC-148 left it that way deliberately
— space names are not in the username directory, so there was nothing to suggest.

There is something to suggest, and it costs nothing to reach: the signed-in user's own shared
spaces are already in the browser. `useConnections` fetches the per-user connections cache for the
Connections page and the Query rail, so the names are sitting in TanStack Query when the dialog
opens.

**What this deliberately does NOT do is publish a directory of every space.** Sharing a table to a
space does not require membership — `test_recipient_space_membership_not_required` pins that any
*active* space is a valid target — so a complete list would be strictly more useful. It would also
disclose every space name in the organisation to every authenticated user, which has no existing
equivalent: today a non-member learns a space exists only by colliding with its name at create
time, and space names are user-chosen and often descriptive. That trade was put to the user on
2026-08-05 and **declined in favour of suggesting only what the user can already see**. A space the
user does not belong to stays typeable, exactly as today.

So the user-visible change is small. The structural change is that `UsernameCombobox` stops being
the only shape of suggestion field this app can have.

## Scope

### In Scope

- **Lifting `UsernameCombobox`'s data source to a prop**, so a caller supplies the suggestions.
- **A thin `useUsernameSuggestions()`** preserving today's behaviour for both existing consumers,
  so neither changes.
- **`TableShareDialog`'s space entry** becomes the same combobox, fed from `useConnections`.
- **Help content** for the space suggestions and their limit.

### Out of Scope

- **Publishing any shared-space directory.** Declined above; do not add "for symmetry with
  SPEC-146". The absence is a decision with a recorded reason.
- **Suggesting spaces the user is not a member of.** That is the same decision.
- **Any change to what `TableShareDialog` submits**, to the combined chip list, to the kind
  toggle, or to the username side.
- **Filtering what a user may target.** Free text still commits; the pipeline is still the
  authority (SPEC-089 re-validates every recipient).
- **Renaming `UsernameCombobox`.** It still suggests catalog-safe identifiers and its consumers
  are usernames and space names, both of which satisfy `CATALOG_IDENTIFIER_RE`. A rename would
  touch every call site to buy a word.

---

## Functional Requirements

### FR-001: The suggestion source becomes a prop

#### Description

`UsernameCombobox` calls `useUserDirectory()` internally. That was a deliberate SPEC-147 deviation
— its spec's prose said the status should be a prop, its API contract declared no such prop, and
with one data source the contract was the right reading. **A second source is exactly the trigger
to revisit it**, and this spec does, rather than adding a near-duplicate component.

#### Acceptance Criteria:

- [ ] `UsernameComboboxProps` gains `status: UserDirectoryStatus` and
      `search: (query: string, limit?: number) => UsernameSearchResult[]`, both required. The
      component makes **no** hook call of its own and imports nothing from `features/user-directory`.
- [ ] Every FR-004/FR-005 behaviour of SPEC-147 is unchanged: the ARIA pattern, the three-Escape
      order, the unlisted-name note shown only when `status === 'ready'`, and the imperative
      `{commit, focus}` handle. The existing suites pass **unmodified apart from supplying the two
      new props** — a behaviour they pinned that this spec did not intend to change must fail loudly.
- [ ] `UsernameChipsField` grows the same two props and passes them straight through.
- [ ] A test asserts the component renders with a `search` that is a plain stub — i.e. it is
      genuinely source-agnostic and needs no provider beyond the ones its chrome uses.

### FR-002: `useUsernameSuggestions()` keeps both existing consumers identical

#### Acceptance Criteria:

- [ ] `useUsernameSuggestions()` returns `{status, search}` by delegating to `useUserDirectory()`,
      and lives in `features/user-directory`.
- [ ] `AddMembersDialog` and `TableShareDialog`'s user entry call it and spread it into the field.
      Their enqueued payloads are unchanged, asserted field-by-field by the existing tests.
- [ ] The `user-directory` component-inventory row is updated; `useUserDirectory` remains the
      public hook and is not wrapped away.

### FR-003: Space suggestions from the connections cache

#### Description

The same ranking the username directory uses, over a much smaller list. `usernameTrie`'s
`buildIndex`/`search` are already pure and take a `string[]` — they were never username-specific.

#### Acceptance Criteria:

- [ ] `useSpaceSuggestions()` builds its index from `useConnections`, filtered to
      `kind === 'shared'` and `isConnectionUsable`, mapped to the space name. It reuses
      `buildIndex`/`search`; no second ranking implementation.
- [ ] `status` is `'loading'` while connections are loading, `'unavailable'` when the fetch failed
      **or** the user belongs to no shared spaces, and `'ready'` otherwise — the same collapse
      SPEC-147 FR-002 made, for the same reason.
- [ ] The index is rebuilt only when the connection list changes, asserted by counting
      `buildIndex` calls through a spy (a timing budget over a handful of names proves nothing —
      the SPEC-147 lesson).
- [ ] `TableShareDialog`'s space entry uses `UsernameCombobox` with these suggestions, keeping its
      `Add` button, its placeholder, and its per-kind dedupe. The **user** entry is untouched.
- [ ] **A space name absent from the suggestions still commits**, with the same neutral note the
      username side shows — and the note's wording says the space may exist and simply not be one
      of yours. It must not imply the name is wrong: targeting a space you are not a member of is
      permitted, and the note is the one place a user could be misled into thinking otherwise.
- [ ] The current user's personal database is **not** suggested: `TableShareDialog`'s space kind
      targets shared spaces, and the personal database is reachable as a user recipient.

### FR-004: Help and a11y

#### Acceptance Criteria:

- [ ] The table-share guide says space suggestions cover the spaces you belong to, and that you
      can still type the name of any other space. Only shipped behaviour is documented (SPEC-074).
- [ ] `vitest-axe` clean for the space kind with the list open, closed, and with recipients
      listed — checked on the **driven container**, never a fresh render of the element, or the
      open-state case silently checks the closed one (the SPEC-147 review's finding).
- [ ] The three-Escape order still holds in the live tree.

### FR-005: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run lint`, `npm run build` and `npm run test` pass.
- [ ] Coverage includes: the FR-001 prop lift with both existing suites otherwise unmodified;
      FR-003's status collapse, single index build, and the unlisted-space note; both dialogs'
      payloads unchanged; and the axe states above.
- [ ] **No new dependency, no new AWS call.** A test asserts the space path issues no S3 request
      of its own — the data comes from a query the app already made.

---

## API / Interface Contract

```ts
// features/user-directory/useUsernameSuggestions.ts — NEW, thin
export function useUsernameSuggestions(): {
  status: UserDirectoryStatus;
  search: (query: string, limit?: number) => UsernameSearchResult[];
};

// features/shared-spaces/useSpaceSuggestions.ts — NEW
export function useSpaceSuggestions(): {
  status: UserDirectoryStatus;   // the same three-state vocabulary, reused deliberately
  search: (query: string, limit?: number) => UsernameSearchResult[];
};

// features/user-directory/UsernameCombobox.tsx — the two additions; everything else unchanged
export type UsernameComboboxProps = {
  status: UserDirectoryStatus;
  search: (query: string, limit?: number) => UsernameSearchResult[];
  // … label, value, onChange, onCommit, onCommitMany, exclude, excludeReason,
  //   suppress, placeholder, disabled, id, describedBy — all as SPEC-147/148 shipped
};
```

## File & Folder Structure

```
apps/portal/src/
├── components/
│   ├── UsernameCombobox.tsx            # data source lifted to props
│   └── UsernameChipsField.tsx          # passes them through
└── features/
    ├── user-directory/
    │   └── useUsernameSuggestions.ts   # NEW — preserves today's behaviour
    ├── shared-spaces/
    │   └── useSpaceSuggestions.ts      # NEW — from the connections cache
    ├── table-share/TableShareDialog.tsx
    └── help/helpContent.ts
```

## Implementation Phases

### Phase 1: Lift the data source

- The two props, `useUsernameSuggestions`, and both existing consumers rewired.
- **Tests:** the existing combobox, chips-field and both dialog suites pass with no change beyond
  supplying the props. This phase must be behaviour-neutral, and the way to prove it is that
  nothing else in those suites moved.

### Phase 2: Space suggestions

- `useSpaceSuggestions`, `TableShareDialog`'s space entry, the unlisted-space note.
- **Tests:** FR-003 in full, plus the axe states.

### Phase 3: Closing out

- Help content, `INDEX.md`, delivery doc, component-inventory rows for the changed component and
  the two hooks, and a `decisions/` entry recording **why no space directory was published** —
  the disclosure trade, so the question is not reopened without the reasoning.
