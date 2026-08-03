# Spec: Username Directory — Browser Data Layer & Typeahead Combobox

**ID:** SPEC-147
**Status:** Draft
**Last Updated:** 2026-08-03
**Depends On:** SPEC-146 (the published document and the portal role's read grant), SPEC-028 (`Input`), SPEC-095 (`Menu` — the repo's existing keyboard-popover precedent, and why a combobox is *not* built on it), SPEC-045 (the `vitest-axe` suite this component must satisfy)

> **Reference:** second of the username-directory arc (146 → **147** → 148).
>
> **Browser-side only: no new IAM, no new AWS resource, no new Lambda, no new env var.** SPEC-146 shipped the grant; the object's location comes from the existing `userSpaceBucket()` helper.
>
> **What 147 ships:** the service that reads the document, the hook that caches it, the search index, and two components — `UsernameCombobox` (single-value typeahead) and `UsernameChipsField` (the multi-value composition around it). **No existing dialog is changed** — SPEC-148 does that. Shipping the primitives first is deliberate: a shared input that lands alongside its first two consumers gets shaped by them, and this one must serve both without becoming a union of their quirks.
>
> **Two mechanisms in this repo do not work the way a reader would expect, and both bite this spec.** `Modal` has **no `closeOnEscape` prop** — only `dismissible` — and `useEscapeKey` is an **unconditional `document` keydown listener** that inspects neither `defaultPrevented` nor any stop flag. `Drawer.closeOnEscape` exists but is a caller-supplied opt-out, not something a leaf component can reach. So "the first Escape closes the suggestion list, the second closes the dialog" is not free; FR-004 specifies the mechanism and puts a fallback change to `useEscapeKey` **in scope** rather than assuming one.
>
> **Rulebooks:** `docs/best-practices/react/react.md` and the accessibility rulebook, routed via `docs/best-practices/INDEX.md`. The combobox pattern is prescriptive — read the a11y section before writing markup, not after.

## Overview

SPEC-146 publishes a sorted list of usernames. This spec makes it searchable and puts components around it.

Two design calls are worth stating. The first is the **index**. The published artifact is a flat sorted array precisely so the browser can choose its own structure; the browser builds a character **trie** from it once, memoised for the session, and every keystroke walks it. For prefix matching that is the right shape — a walk proportional to what was typed, plus the results collected — and it stays right as the organisation grows. There is no dependency to add; a trie is a plain object keyed by character with a terminal marker.

Prefix matching alone is not enough, though: someone looking for `bob_smith` may well type `smith`. So the search returns prefix matches first, then substring matches. **The substring band is honestly linear** — no structure built in a single pass over the input answers arbitrary substring queries sub-linearly, and pretending otherwise would set up a performance claim the code cannot keep. FR-003's cost bound therefore constrains the prefix band and caps the substring band by short-circuiting once the result limit is reached.

The second call is that the component **never blocks a name it does not know**. The directory is up to a day stale, misses users not yet provisioned, and is not the authority on who exists — the control plane is, and it already reports unknown names by notification. A combobox that refused an unlisted name would convert a stale cache into a hard failure in the exact flow whose current behaviour is at least permissive. So: suggestions are suggestions, free text always commits, and an unlisted-but-valid name is committed with a quiet note rather than an error.

---

## Scope

### In Scope

- **`userDirectory.service.ts`** — read and validate the document; never throws; missing or corrupt reads as an empty directory.
- **`useUserDirectory()`** — a TanStack Query hook with a long `staleTime`, exposing the search index and a directory **status** consumers can branch on.
- **`usernameTrie.ts`** — pure: build the index, search it, rank results.
- **`parseMemberInputDetailed`** in `features/shared-spaces/memberInput.ts` — the reporting variant `UsernameChipsField`'s paste handling needs. It lands here, not in SPEC-148, because this spec's Phase 4 depends on it.
- **`UsernameCombobox`** — an accessible single-value typeahead, in the shared `components/` tier because it has consumers in two features.
- **`UsernameChipsField`** — the multi-value composition (combobox + committed chips), with a caller-supplied chip label so both consumers keep their existing wording.
- **The Escape mechanism**, including a change to `useEscapeKey` if the propagation approach does not hold.
- **Full keyboard and screen-reader support** per the ARIA combobox pattern, with `vitest-axe` assertions.
- **Responsive behaviour** at mobile, tablet and desktop on one tree.

### Out of Scope

- **Wiring into any dialog** — SPEC-148. If this spec edits `AddMembersDialog.tsx` or `TableShareDialog.tsx`, it has gone wrong.
- **Changing `parseMemberInput`'s behaviour or signature.** The new variant sits beside it; the original's silent drop is relied on by shipped callers and by their tests.
- **Shared-space names.** The components search usernames. `TableShareDialog` also accepts space names; SPEC-148 keeps that entry on its existing free-text path.
- **Server-side search or pagination.** The whole document is fetched once. If the directory outgrows a client-side index, FR-002's cap is where it announces itself.
- **Fuzzy or edit-distance matching.** Prefix and substring only.
- **Recency, frecency or "people you have shared with before".** Ranking is deterministic and stateless.
- **Any write.** The browser never modifies the directory.

---

## Functional Requirements

### FR-001: Reading the document

#### Description

The same forgiving-read shape every other JSON-from-S3 service in this repo uses: a missing object and a corrupt object are both the empty state, not an error, because the only honest thing to do with an unavailable suggestion list is offer no suggestions.

#### Acceptance Criteria:

- [ ] `getUserDirectory()` reads `_directory/usernames.json` from `userSpaceBucket()` via `withCredentialRetry(getS3Client, …)` and a `GetObjectCommand`.
- [ ] A `NotFound` (per `isNotFound`) returns `{success: true, data: {usernames: [], generatedAt: null}}`.
- [ ] A `SyntaxError` from `JSON.parse` returns the same empty success.
- [ ] A document whose `version` is not `1` returns the empty success and logs a `console.warn` naming the version — a shape the browser does not understand is not a shape it should guess at.
- [ ] A document whose `usernames` is not an array of strings returns the empty success.
- [ ] Every entry is filtered through `CATALOG_IDENTIFIER_RE` on read. The producer already guarantees this; the consumer re-checks because this array is rendered into the DOM and used to build keys, and a producer guarantee is not a runtime guarantee.
- [ ] Any other error returns `toServiceError(err, 'Failed to load the user directory')`.
- [ ] The service returns `ServiceResult<UserDirectory>` and never throws.
- [ ] The bucket name is read at **call time**, not module load.

### FR-002: The hook, its cache, and the status consumers branch on

#### Description

SPEC-148 needs to distinguish *loading* from *unavailable* from *loaded-but-this-name-is-absent*, and the components need it too. A single nullable index cannot express that, so the hook exposes an explicit status and the components take it as a prop.

#### Acceptance Criteria:

- [ ] `useUserDirectory()` uses `useQuery` with a key from a new `userDirectoryKeys` factory — never a hand-built array.
- [ ] `staleTime` is one hour and `gcTime` longer, because the document changes at most once a day. Refetch-on-focus stays off (the app-level default).
- [ ] `retry: false` — a missing document is the empty state, not a transient failure worth retrying.
- [ ] The hook returns `{status, search, generatedAt}` where `status` is `'loading' | 'ready' | 'unavailable'` and `search` is a **stable callback** `(query, limit?) => UsernameSearchResult[]`. Returning a callback rather than the index resolves the lazy-build tension: the index is built on the first call and memoised behind the callback, and no consumer ever holds a half-built structure.
- [ ] `status` is `'unavailable'` when the fetch errored **or** succeeded with an empty list — from a consumer's point of view those are the same situation, and collapsing them here means no consumer has to remember to handle both.
- [ ] `search` returns `[]` while `status` is not `'ready'`.
- [ ] The index is built at most once per fetched document; a test asserts it is not rebuilt on an unrelated re-render, and that the `search` identity is stable across renders.
- [ ] A **cap of 20,000 usernames** is applied at index-build time; beyond it the index is built from the first 20,000 and `console.warn` names the overflow. The cap exists so that the day this outgrows a client-side index, it says so instead of quietly becoming slow.

### FR-003: The trie, the ranking, and the honest cost

#### Description

Pure functions in their own module, tested directly. The ranking rules are ordinary but must be *specified*, because "the right person was third in the list" is the complaint this feature will generate.

#### Acceptance Criteria:

- [ ] `buildIndex(usernames: string[]): UsernameIndex` builds a character trie plus the flat ordered array the substring band scans, in one walk of the input.
- [ ] `search(index, query, limit)` returns at most `limit` usernames (default 8), ordered: exact match first if present; then prefix matches, ascending alphabetically; then substring matches, ascending alphabetically. A username appears at most once.
- [ ] The query is lowercased and trimmed before searching; a query containing a character that cannot appear in a username still searches (matching nothing) rather than throwing.
- [ ] An empty query returns an empty result — the component does not open a menu of everyone on focus.
- [ ] A single-character query is searched normally. There is no minimum length: in a small directory one character is a useful filter, and a minimum is a rule users have to discover.
- [ ] **The prefix band walks the trie and never scans the full list** — a test asserts the number of trie nodes visited is bounded by the query length plus the size of the matching subtree it enumerates, not by the directory size.
- [ ] **The substring band is a linear scan and is documented as such** in the module's JSDoc. It **short-circuits** as soon as the result limit is reached, and it is skipped entirely when the prefix band already filled the limit — so the common case (a real prefix) never pays for it.
- [ ] `search` is deterministic — the same index and query always give the same order.
- [ ] Tests cover: exact-before-prefix; prefix-before-substring; alphabetical within each band; the limit truncating the lowest band first; the substring band skipped when the prefix band fills the limit; no duplicates when a name matches two ways; an empty index; and a 20,000-entry index searched under a performance assertion for both a prefix-heavy and a substring-only query.

### FR-004: `UsernameCombobox` — the ARIA pattern and the Escape mechanism

#### Description

This is the part where guessing produces something that looks fine and is unusable with a screen reader. The repo's `Menu` primitive is `role="menu"` with arrow-key roving, correct for a menu and **wrong** here: a combobox keeps focus in the text input and moves a virtual cursor with `aria-activedescendant`. Reusing `Menu` would be the easy mistake.

Escape needs its own mechanism, because the enclosing dismiss handlers are `document`-level listeners the component cannot reach. The approach is to `stopPropagation` from the input's React handler, which prevents the event reaching `document` — but that rests on React's root-level delegation and must be **verified, not assumed**. If it does not hold, the fallback is to give `useEscapeKey` a guard on `defaultPrevented` and have the combobox call `preventDefault`. That change is in scope for this spec.

#### Acceptance Criteria:

- [ ] The input carries `role="combobox"`, `aria-expanded`, `aria-controls` pointing at the listbox, `aria-autocomplete="list"`, and `aria-activedescendant` set to the highlighted option's id when one is highlighted and absent otherwise.
- [ ] The suggestion list is `role="listbox"` with `role="option"` children, each with a stable id and `aria-selected` on the highlighted one.
- [ ] **Focus never leaves the input** while the list is open. A test asserts `document.activeElement` is the input after `ArrowDown`.
- [ ] `ArrowDown` / `ArrowUp` move the highlight and wrap; `Home` / `End` jump to first and last.
- [ ] `Enter` commits the highlighted option. With no highlight it commits the typed text — **through `parseMemberInputDetailed`, not verbatim**, so a comma- or whitespace-separated entry commits every valid token via `onCommitMany` and leaves the invalid ones in the input. `TableShareDialog`'s user entry is a **bulk** field today (`parseMemberInput(entry)`, placeholder `e.g. bob, cara`), and a single-value-only combobox would silently remove that shipped capability.
- [ ] `onCommitMany` is optional; when a consumer omits it, a multi-token entry commits only its first valid token through `onCommit`. `AddMembersDialog` never sees this path because `UsernameChipsField` always supplies it.
- [ ] `Escape` **with the list open** closes the list, does not clear the input, and does **not** reach the enclosing dismiss handler. `Escape` with the list closed is not intercepted at all and dismisses the enclosing surface normally.
- [ ] The mechanism is verified by a test rendering the combobox inside a **`Modal` inside a `Drawer`** — the real composition SPEC-148 produces (`ManageMembersDrawer` renders `AddMembersDialog`) — asserting that the first Escape closes only the list, the second closes only the modal, and the third closes the drawer.
- [ ] **The test must reproduce the drawer's `closeOnEscape` gate, not a bare nesting.** `Drawer.closeOnEscape` defaults to `true` and both `Modal` and `Drawer` register **document-level** listeners through `useEscapeKey`, so with a bare `Modal` inside a bare `Drawer` one keydown closes both and the stated order is unreachable. The shipped order exists only because `ManageMembersDrawer` passes `closeOnEscape={!addOpen && !removing}`. The fixture therefore mirrors that gating, and a comment says why — otherwise the test is written, fails, and the combobox gets blamed for something it does not control.
- [ ] If `stopPropagation` does not prevent `useEscapeKey`'s `document` listener from firing, `useEscapeKey` gains a `defaultPrevented` guard and the combobox calls `preventDefault`. Either implementation satisfies the criterion above; **no other consumer of `useEscapeKey` changes behaviour**, asserted by its existing tests passing unmodified.
- [ ] `Tab` closes the list and commits nothing, leaving the typed text in the input.
- [ ] Clicking an option commits it; clicking outside closes the list.
- [ ] A live region announces the result count on change (`"{n} matches"` / `"No matches"`), politely, debounced so a fast typist is not read a queue of counts.
- [ ] The component builds on the shared `Input` (SPEC-028) for its field chrome, label and error state rather than restyling one.
- [ ] `vitest-axe` reports no violations in the closed, open-with-results and open-with-no-results states.

### FR-005: An unlisted name is always accepted

#### Description

The single most important behaviour in this spec, and the one most likely to be "improved" into a validation gate later.

#### Acceptance Criteria:

- [ ] Text passing `CATALOG_IDENTIFIER_RE` is committable whether or not it appears in the directory. Enter commits it; there is no state in which a valid unlisted name cannot be entered.
- [ ] When `status` is `'ready'` and a committed name is absent from the directory, the component surfaces a **neutral, non-blocking note** — that the name was not found in the directory and will be checked when the request is sent. Not styled as an error; disables nothing.
- [ ] When `status` is `'loading'` or `'unavailable'`, **no note is shown and no suggestions appear.** A note that arrives a second after a name was accepted reads as a delayed rejection; and telling a user their colleague "was not found" because a background fetch failed is worse than saying nothing.
- [ ] Text failing `CATALOG_IDENTIFIER_RE` is rejected with the existing `CATALOG_IDENTIFIER_RULE` wording, from its single source in `features/query/query.constants.ts`. No new wording is written.
- [ ] A test asserts an unlisted valid name commits successfully in all three statuses.
- [ ] A comment on the component records that the directory is advisory, that the control plane is the authority, and that the control plane **already notifies on an unknown name** — so an unlisted name is a slower path, not a lost one.

### FR-006: `UsernameChipsField` — the multi-value composition

#### Description

Both consumers in SPEC-148 collect several names, but they render them differently: `AddMembersDialog` will own its list outright, while `TableShareDialog` keeps one **combined** list mixing user and space chips with kind badges. So this component owns chip rendering by default and can hand it back.

#### Acceptance Criteria:

- [ ] Committed names render as removable chips in a `<ul>` with a caller-supplied `aria-label`, each chip carrying a remove control whose label comes from a caller-supplied `chipRemoveLabel(name)` defaulting to `Remove {name}` — so `TableShareDialog` can keep its shipped `Remove {kind} {name}` wording.
- [ ] A `renderChips={false}` mode suppresses the internal list entirely, leaving the caller to render committed values in its own list. This is what lets `TableShareDialog` keep one combined list rather than growing a second.
- [ ] Duplicates are silently ignored on commit — committing a name already present is a no-op, not an error.
- [ ] The caller may supply an `exclude` set whose names are filtered **out of the suggestions** and rejected on commit with a caller-supplied reason.
- [ ] `Backspace` on an empty input removes the last chip, in the default mode only. A test covers it — it is the one keyboard behaviour users expect from chip inputs and never see documented.
- [ ] Pasting a comma- or whitespace-separated list uses **`parseMemberInputDetailed`**: valid tokens commit, invalid tokens are **left in the input** joined by a space with the `CATALOG_IDENTIFIER_RULE` sentence as the reason. Surfacing them is a deliberate departure from `parseMemberInput`'s silent drop, and it is why the detailed variant lands in this spec.
- [ ] `parseMemberInputDetailed(raw): {valid: string[], invalid: string[]}` is added to `features/shared-spaces/memberInput.ts`. `parseMemberInput`'s signature, behaviour and existing tests are **unchanged** — asserted as a criterion.
- [ ] The committed value is exposed to the caller as `string[]`; the component owns no submission logic.
- [ ] `vitest-axe` clean with zero, one and many chips, and in `renderChips={false}` mode.

### FR-007: Responsive

#### Acceptance Criteria:

- [ ] One tree, `tablet:` / `desktop:` only (SPEC-095). No `*Mobile` twin.
- [ ] At 400px the suggestion list is width-constrained to the field, scrolls internally at a bounded max-height, and does not overflow the enclosing `Modal` or bottom-sheet.
- [ ] Options and chip remove controls meet the touch-target floor.
- [ ] The list positions below the field and flips above it when there is not room — with **no positioning dependency added**; a bounded max-height plus the flip is sufficient and a floating-UI library is not in the Tech Stack.

### FR-008: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run test` and `npm run lint` pass.
- [ ] Tests are integration-style via `renderWithProviders` — render the real hook and children, mock only the S3 boundary.
- [ ] Coverage includes every FR-003 ranking and cost case, every FR-004 keyboard interaction, the Modal-inside-Drawer Escape case, all three statuses for FR-005, the FR-006 paste, exclude, `renderChips={false}` and chip-label behaviours, and axe assertions in every listed state.
- [ ] `useEscapeKey`'s existing tests pass unmodified whether or not it gained a guard.
- [ ] **No new dependency is added.** If the implementation reaches for a combobox or positioning library, stop — that is a Tech Stack change and `CLAUDE.md` requires it be noted first.

---

## Data Model

```ts
// apps/portal/src/features/user-directory/userDirectory.types.ts — NEW

export type UserDirectoryDocument = {
  version: number;
  generatedAt: string;
  count: number;
  usernames: string[];
};

/** What the service returns. */
export type UserDirectory = {
  usernames: string[];
  /** null when the directory is unavailable or empty. */
  generatedAt: string | null;
};

/** What consumers branch on. 'unavailable' collapses "errored" and "empty". */
export type UserDirectoryStatus = 'loading' | 'ready' | 'unavailable';

export type UsernameSearchResult = {
  username: string;
  match: 'exact' | 'prefix' | 'substring';
};

/** Internal to usernameTrie.ts. Consumers never hold one — the hook hands out a
 *  `search` callback instead, which is what makes the lazy build invisible. */
export type UsernameIndex = {
  root: TrieNode;
  ordered: readonly string[];  // the substring band's scan target
  size: number;
  truncated: boolean;
};

type TrieNode = { children: Record<string, TrieNode>; terminal: boolean };
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/user-directory/userDirectory.service.ts
export async function getUserDirectory(): Promise<ServiceResult<UserDirectory>>;

// apps/portal/src/features/user-directory/useUserDirectory.ts
export function useUserDirectory(): {
  status: UserDirectoryStatus;
  /** Stable identity across renders. Builds the index on first call, then memoises.
   *  Returns [] unless status === 'ready'. */
  search: (query: string, limit?: number) => UsernameSearchResult[];
  generatedAt: string | null;
};

// apps/portal/src/features/user-directory/usernameTrie.ts — pure, no React, no AWS
export function buildIndex(usernames: string[]): UsernameIndex;
export function search(
  index: UsernameIndex,
  query: string,
  limit?: number,           // default 8
): UsernameSearchResult[];
// The prefix band walks the trie. The SUBSTRING band is a linear scan over
// `ordered`, short-circuited at `limit` and skipped when the prefix band filled it.

// apps/portal/src/features/shared-spaces/memberInput.ts — extended, not replaced
export function parseMemberInput(raw: string): string[];              // UNCHANGED
export function parseMemberInputDetailed(
  raw: string,
): { valid: string[]; invalid: string[] };                            // NEW

// apps/portal/src/components/UsernameCombobox.tsx
export type UsernameComboboxProps = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  onCommit: (username: string) => void;
  /** Bulk commit for a multi-token entry or paste, split by parseMemberInputDetailed.
   *  Optional, but TableShareDialog's user entry is a bulk field today and depends on it. */
  onCommitMany?: (usernames: string[]) => void;
  exclude?: ReadonlySet<string>;
  excludeReason?: (username: string) => string;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
};

// apps/portal/src/components/UsernameChipsField.tsx
export type UsernameChipsFieldProps = {
  label: string;
  /** aria-label for the chip list — the caller names the noun. */
  listLabel: string;
  value: string[];
  onChange: (next: string[]) => void;
  /** false ⇒ the caller renders committed values itself (TableShareDialog's
   *  single combined list of user AND space chips). Default true. */
  renderChips?: boolean;
  /** Defaults to `Remove {name}`; TableShareDialog supplies `Remove user {name}`. */
  chipRemoveLabel?: (name: string) => string;
  exclude?: ReadonlySet<string>;
  excludeReason?: (username: string) => string;
  disabled?: boolean;
};
```

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/
├── features/
│   ├── user-directory/                       # NEW
│   │   ├── index.ts
│   │   ├── userDirectory.service.ts
│   │   ├── userDirectory.service.test.ts
│   │   ├── userDirectory.types.ts
│   │   ├── userDirectoryKeys.ts
│   │   ├── useUserDirectory.ts
│   │   ├── useUserDirectory.test.ts
│   │   ├── usernameTrie.ts
│   │   └── usernameTrie.test.ts
│   └── shared-spaces/
│       ├── memberInput.ts                    # + parseMemberInputDetailed
│       └── memberInput.test.ts               # + the variant; original's cases untouched
├── hooks/
│   └── useEscapeKey.ts                       # possibly + a defaultPrevented guard (FR-004)
└── components/
    ├── UsernameCombobox.tsx                  # NEW
    ├── UsernameCombobox.test.tsx
    ├── UsernameCombobox.a11y.test.tsx
    ├── UsernameChipsField.tsx                # NEW
    ├── UsernameChipsField.test.tsx
    └── UsernameChipsField.a11y.test.tsx
```

## Implementation Phases

### Phase 1: The pure index

- `usernameTrie.ts` — build, search, rank, with the short-circuiting substring band.
- **Tests:** the full FR-003 list including both performance assertions. Written first; this module has no dependencies and every later phase rests on it.

### Phase 2: Service and hook

- `userDirectory.service.ts`, `userDirectoryKeys.ts`, `useUserDirectory.ts` with its status and stable `search` callback.
- **Tests:** every FR-001 read path; the status collapse; the stable callback identity; the single index build; the cap.

### Phase 3: The combobox and the Escape mechanism

- `UsernameCombobox` with the full ARIA pattern.
- Verify `stopPropagation`; add the `useEscapeKey` guard if needed.
- **Tests:** every keyboard interaction; the Modal-inside-Drawer three-Escape case; all three statuses for FR-005; axe in three states; `useEscapeKey`'s existing tests unmodified.

### Phase 4: Chips, paste, responsive, closing out

- `parseMemberInputDetailed`; `UsernameChipsField` including exclude, `renderChips` and the chip label.
- Responsive pass at 400px.
- **Tests:** FR-006 in full; axe with zero, one and many chips and in `renderChips={false}`.
- Completion ritual: `INDEX.md` status, delivery doc, and component-inventory rows in `shared-components.md` (`UsernameCombobox`, `UsernameChipsField`), `shared-spaces-feature.md` (`parseMemberInputDetailed`) and a new area file for the `user-directory` service, hook and trie. **No help-content change** — nothing is reachable by a user until SPEC-148.
