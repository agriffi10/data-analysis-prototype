---
type: Spec
id: SPEC-154
title: "Frontend Journey Coverage — Testing the Wires Between Tested Halves"
description: "Adds portal journey tests that wire together separately tested pieces (sign-in and sign-out, collisions, uploads, table share from its menu, results paging) and moves hand-rolled test providers onto the shared harness."
spec_status: Completed
depends_on: [SPEC-045, SPEC-078, SPEC-093, SPEC-150]
arc: audit-remediation
arc_order: 5
---

**Dependency notes:** SPEC-045 (`vitest-axe` and the a11y assertion practice), SPEC-215-era test rework (`src/test/renderWithProviders.tsx`, the harness this spec finishes adopting), SPEC-078 (the run scopes whose keyboard entry points SPEC-150 FR-010 covers and this spec builds on), SPEC-093 (table share, the feature with no integration coverage), SPEC-150 (whose FR-010 fixes the Monaco mock this spec's script tests depend on)
> **Reference:** from the 2026-08-05 codebase audit. The frontend suite is in better shape than its size suggests — 168 files, 1301 tests, and almost none of the anti-patterns you would look for first. **Verified absent:** snapshot tests, `toBeTruthy()` on a render, zero-assertion `it` blocks, tautological mock-return assertions, and `data-testid` in source (zero occurrences). All 13 `*.service.test.ts` mock the **SDK client**, never the service under test.
>
> **So this spec is not a cleanup.** It closes one specific structural gap: **a hook tested with `renderHook`, a component tested with a stub callback, and nothing testing the wire between them.** Both halves are green; the wire is what breaks in production. Table share is the clearest case — three separate test files cover its pieces and not one drives its only user flow.
>
> **`vi.mock('./x.service')` is the mandated pattern, not a smell.** `react.md:246` says so explicitly: "✅ `vi.mock('./x.service')` … Render the real tree." The 48 files doing it are correct. What §21 forbids is mocking the feature's **own hooks or child components** (`:247`), and there is exactly **one** real violation in the tree.
>
> **The model already exists in the repo.** `QueryWorkspace.test.tsx:892-1010` (SPEC-145's refresh coverage) drives rail menu → dialog → submit → service → toast, including the link-borne opt-in and four rejection cases. `ConnectionsPage.test.tsx` does the same for create, add-member, leave and delete. Hold new tests to that standard rather than inventing one.

## Overview

The portal's test suite is integration-style by policy: render the real tree, mock only at the AWS service boundary, and assert what a user sees. Where that policy is followed the tests are genuinely good — the query workspace suite covers batch runs, stop-mid-batch, error mapping, tab restore, CSV export with its overwrite path, and the whole refresh-table flow shipped in SPEC-145.

The gap is uneven adoption. Several features were built with their pieces tested individually and the assembly never tested at all. Table share has a hook test, a dialog test and a menu test, and no test that opens the dialog from the menu and watches a request reach the service — so a dialog that never mounts, a wrong `source`, or a dropped `onSubmit` all pass green. Sign-in and sign-out are never clicked anywhere in the suite. A file-collision prompt is never resolved through the UI on any path; resolution is invoked directly on hook internals. An upload is never watched from queued to Uploaded. Results pagination cannot be tested at all, because the fixture hard-codes `nextToken: undefined`.

Alongside that, roughly a third of the suite predates the shared harness and hand-rolls its own providers — four of those leave TanStack retries **on**, which makes a failed assertion wait for a backoff instead of failing fast. And ~45 assertions use Tailwind class strings as a proxy for behaviour, in a jsdom environment that applies no media queries, so they prove nothing and break on any equivalent CSS.

The outcome is that each flow a user can actually perform has at least one test that performs it.

---

## Scope

### In Scope

- **End-to-end journey tests** for: table share, sign-in/sign-out, collision resolution, upload to completion, results pagination, remove-member, populated partition keys, notification link navigation, and the dev-unauth bypass.
- **Harness adoption** for the files that hand-roll providers, prioritising the four with retries left on.
- **Removing the one real §21 mock violation.**
- **Replacing class-string assertions** with the accessible contract, where one exists.
- **Opportunistic `fireEvent` → `userEvent`** in files this spec already touches.
- **Fixing the duplicated validator** inside `useCopy.test.ts`'s mock factory.

### Out of Scope

- **Any production code change.** This spec is tests only. If a journey test cannot be written without changing a component, that is a finding to file — not a licence to change behaviour here. The one exception is a component that must expose an accessible name or role to be testable at all; such a change is additive, must not alter appearance, and is recorded.
- **A blanket `fireEvent` → `userEvent` migration** across all 50 files. §21 scopes its rule to "new/reworked tests"; converting files this spec does not otherwise touch is churn.
- **The Monaco keybinding mock and the three run-scope tests** — SPEC-150 FR-010. This spec's multi-statement script coverage assumes that landed.
- **Raising coverage thresholds.** SPEC-150 FR-002 owns the floors. Coverage will rise; the floors move in their own PR.
- **E2E/browser-driver tests.** Everything here is Vitest + RTL in jsdom.
- **Python tests** — SPEC-153.

---

## Functional Requirements

### FR-001: Table share is driven end to end

#### Description

`QueryWorkspace.tsx:291,1717` wires `useTableShare` → `TableShareDialog`. `QueryWorkspace.test.tsx:89` mocks `enqueueTableShare` and never opens the dialog or asserts the mock. The three fragments each test a stub: `TableShareDialog.test.tsx:94` asserts a `vi.fn()` prop, `useTableShare.test.ts:18` is a bare `renderHook`, `DatabaseNode.test.tsx:151` asserts `onShareTable` was called.

#### Acceptance Criteria

- [ ] A test opens the share item from the schema rail's table menu, fills the dialog, submits, and asserts `enqueueTableShare` received the correct `source` (database **and** table), `tableName` and `recipients`.
- [ ] The success toast is asserted, and the dialog closes.
- [ ] A service failure renders the mapped user message — asserted as rendered text, not as a `toUserMessage` call.
- [ ] The share item's absence for a `VIRTUAL_VIEW` is asserted at the workspace level, not only in `DatabaseNode.test.tsx`.
- [ ] The test mirrors the structure of the SPEC-145 refresh block at `QueryWorkspace.test.tsx:892-1010`.

### FR-002: Authentication controls are exercised

#### Description

`Header.tsx:104` renders `onClick={() => void signOut()}` and no test clicks it. The `role="alert"` auth-error banner at `:121` is never rendered by any test. Coverage today is three spy-count assertions inside the provider's own test plus a synthetic probe button. The cause is `vi.mock('../features/auth')` in three layout tests, which the harness's `auth` option makes unnecessary.

#### Acceptance Criteria

- [ ] `components/Header.test.tsx`, `RootLayout.test.tsx` and `ProtectedLayout.test.tsx` drop `vi.mock('../features/auth', …)` and inject auth via `renderWithProviders(ui, {auth: authenticated('alice')})`, as `LandingPage.test.tsx` already does.
- [ ] A test clicks **Sign out** and asserts the auth action ran and the resulting UI state.
- [ ] A test renders the auth-error banner and asserts its `role="alert"` and message.
- [ ] A test clicks **Sign in** from the landing page and asserts the sign-in action ran.
- [ ] `ProtectedLayout`'s prefetch tests assert the observable outcome (the bell showing an unread count without a spinner) rather than `expect(mockPrefetch).toHaveBeenCalledWith(...)`, and the `vi.mock('../features/notifications')` barrel mock is replaced with the service-boundary mock the sibling tests already use correctly.

### FR-003: A collision is resolved through the UI

#### Description

`FileBrowser.test.tsx:394-403` asserts the collision prompt appears and ends there. Resolution is invoked on hook internals — `useCopy.test.ts:105`, `act(() => result.current.copyCollision?.onOverwriteAll())`. So the retry-with-`overwrite: true` round trip is never observed by a user-driven test, on a flow CLAUDE.md flags as non-atomic and collision-prone.

#### Acceptance Criteria

- [ ] A test drives an upload collision to **Overwrite** through the rendered prompt and asserts the retry call carries `overwrite: true`.
- [ ] A test drives the same collision to **Rename** and asserts the new key.
- [ ] A test drives a **batch** copy/move collision to "Overwrite all" through `BatchOverwritePrompt` and asserts the resulting calls.
- [ ] A test cancels a collision and asserts no further request is made.
- [ ] Each asserts the user-visible result (the summary banner text) as well as the service call.

### FR-004: An upload is watched to completion

#### Description

The most-used flow in the app has one UI-level test whose only assertion is `expect(mock.uploadFile).toHaveBeenCalled()` (`FileBrowser.test.tsx:406-414`). Above it, `UploadList.test.tsx:8` mocks the context the provider supplies, so every visible state is asserted against hand-fed items; below it, `UploadQueueProvider.test.tsx` tests the reducer via `renderHook`. Nothing spans them.

#### Acceptance Criteria

- [ ] A test renders a **real** `UploadQueueProvider` behind a **real** `UploadList`, enqueues a file, and asserts the visible progression: queued → uploading (progress shown) → Uploaded.
- [ ] A failing upload shows the Failed state with the mapped message.
- [ ] Cancelling an in-flight upload aborts the request and marks it **Cancelled**; cancelling a
  **queued** upload removes it outright. *(Corrected during the build: this AC originally read
  "removes it", which the app does not do and should not — `UploadQueueProvider` transitions an
  in-flight cancel to a terminal `cancelled` row and drops only a queued one, so the user gets
  confirmation the cancel took rather than a row that silently vanishes. Both halves are asserted.)*
- [ ] The concurrency gate is observable at this level, or the test records why it is not and leaves the provider-level test as its home.
- [ ] Multipart internals stay out of scope — the SDK ctor args are already correctly pinned at `fileBrowser.service.ts`'s service test.

### FR-005: Results pagination and the controls that share its seam

#### Description

`'Next'` does not appear in `QueryWorkspace.test.tsx`, and the fixture cannot enable it — `:160` sets `nextToken: undefined`. Coverage is hook state (`useQueryResults.test.ts:63`) plus a prop spy (`QueryResultsTable.test.tsx:100`). The same split leaves rows-per-page, column widths across tab switches, and editor layout presets with no user path.

#### Acceptance Criteria

- [ ] The workspace fixture supplies a `nextToken`, and a test clicks **Next**, asserts the fetch carried the token, and asserts page 2 renders.
- [ ] **Previous** returns to page 1.
- [ ] Changing **rows per page** re-fetches and renders the new size, and the setting persists across result tabs within the session.
- [ ] A column width set on one tab survives a switch away and back.
- [ ] An editor layout preset applies and persists per its spec. *(Subject retired by SPEC-209 — the presets are gone; the equivalent guard is now the divider's drag-and-remount case.)*
- [ ] Where an existing hook test now duplicates one of these, it is reduced to the state derivation it uniquely covers rather than left asserting the same thing twice (§21: don't test the same logic at two levels).

### FR-006: The remaining unwired flows

#### Acceptance Criteria

- [ ] **Remove-member**: `ConnectionsPage.test.tsx` drives removal through `ManageMembersDrawer` to `enqueueSharedSpaceRequest`, asserting the correct space name — the `managing.name` closure is what goes wrong here.
- [ ] **Partition keys**: a populated partition-key array is carried from the `CreateTableDialog` wizard through to `enqueueTableBuild`, asserted field-by-field. `CreateTableButton.test.tsx:47`'s index-based target selection (`getAllByRole(...)[1]`) is replaced with a stable accessible query.
- [ ] **Notification link**: a test clicks a notification's link and asserts the report page renders, pinning link shape to route shape. The links are Lambda-authored, so today's `toHaveAttribute('href', …)` assertion cannot catch a route rename.
- [ ] **Dev-unauth bypass**: tests using `vi.stubEnv('VITE_S3_DEV_UNAUTH', 'true')` assert the bypass works in DEV **and** that it does not apply when `import.meta.env.DEV` is false. This is security-relevant and currently has zero coverage.

### FR-007: The harness is adopted where it was hand-rolled

#### Description

§21: "🔴 Don't hand-roll a `QueryClientProvider` + `MemoryRouter` wrapper per file." 31 files do. Four leave retries **on** by constructing a bare `new QueryClient()`: `useCopy.test.ts:32`, `useMove.test.ts:23`, `useDelete.test.ts:23`, `useFileUpload.test.ts:23`.

#### Acceptance Criteria

- [ ] The four retry-on files are converted to `renderHookWithProviders` first, since a mocked rejection there currently waits for a backoff.
- [ ] Remaining hand-rolled wrappers are converted where the harness supports the case; any file that genuinely needs a bespoke tree (e.g. a router test asserting route composition) keeps its own with a one-line reason.
- [ ] Bare `renderHook` from `@testing-library/react` is replaced by `renderHookWithProviders` wherever the hook reads Query, router or auth.
- [ ] No test's meaning changes — this is a mechanical conversion, and any behavioural difference it surfaces is a finding to report, not to paper over.

### FR-008: The §21 mock violation and the duplicated validator

#### Acceptance Criteria

- [ ] `fileBrowser.a11y.test.tsx:14`'s bare `vi.mock('./useFileBrowser')` is removed and the a11y assertion runs against the real tree. §21 names that exact hook in its 🔴 list, and the guarantee is currently asserted against a hand-built result rather than what a user gets.
- [ ] `vi.mock('./uploadQueueContext')` in the same file is likewise removed or justified in one line as a genuine heavy-global exception.
- [ ] `useCopy.test.ts:14-20`'s mock factory stops re-implementing `validateFolderName` — it currently claims to "reuse the real validation rules" while **omitting the control-character rule entirely** and using different messages. Replace with `importOriginal`.
- [ ] `vi.mock('./SqlEditor')` is **kept** — it is the sanctioned Monaco exception and carries a written reason.

### FR-009: Class-string assertions give way to the accessible contract

#### Description

~45 assertions use Tailwind class strings as behaviour proxies. jsdom applies no media queries, so a `tablet:`/`desktop:` class assertion proves nothing about what a user sees while failing on any refactor to equivalent CSS.

#### Acceptance Criteria

- [ ] `RefreshTableDialog.test.tsx:139-164`'s `describe('at a narrow viewport')` — which **never changes the viewport** — is either given a real viewport change or rewritten to assert the behaviour it names.
- [ ] Where an accessible assertion already sits beside a class assertion (e.g. `DatabaseNode.test.tsx:217-218`, where `toBeDisabled()` precedes `animate-spin`), the class assertion is removed as redundant.
- [ ] Assertions reaching through `.parentElement` / `.closest('div')!.parentElement!` chains (`ConnectionsPage.test.tsx:309,327`) are replaced with role or label queries.
- [ ] A class assertion may remain **only** where it pins a documented responsive contract with no accessible equivalent, and then with a one-line reason.
- [ ] No test's coverage decreases: each replacement asserts at least as much as what it replaced.

---

## Implementation Phases

Phases are independently landable; each should be its own PR.

### Phase 1: The harness and the violation

- FR-007 (retry-on files first), FR-008. These make every later phase easier and are pure mechanical work.

### Phase 2: Table share and auth

- FR-001, FR-002. The two flows with the largest gap between "has tests" and "is tested".

### Phase 3: File operations

- FR-003 (collision resolution), FR-004 (upload to completion).

### Phase 4: Query surfaces

- FR-005 (pagination and its neighbours), plus the multi-statement script scopes now that SPEC-150 FR-010 has made the Monaco mock honest.

### Phase 5: The remainder

- FR-006 (remove-member, partition keys, notification link, dev-unauth).

### Phase 6: Assertion quality

- FR-009, and opportunistic `fireEvent` → `userEvent` in every file touched by Phases 1–5.

### Phase 7: Completion

- Completion ritual per `CLAUDE.md`. Tests only, so expect no `decisions/` entry and no component-inventory row; the delivery doc records the coverage delta and any finding filed under FR-007's "report, don't paper over" clause.
