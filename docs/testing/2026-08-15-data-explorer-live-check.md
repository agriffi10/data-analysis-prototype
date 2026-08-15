# Live-check session — 2026-08-15 (Data Explorer arc, SPEC-186 dialogs, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `88caf54`) as
`agriffith_three`, in **Chrome at 1400×730**. Safari waived for behavioural checks by user
decision — see the amendment at the head of `data-explorer-e2e.md`.

## How executions were counted

**The network panel could not carry these assertions.** `read_network_requests` reports URL,
method and status only — every Athena call is a `POST` to the same host, so it cannot separate
`StartQueryExecution` from `GetQueryExecution`/`GetQueryResults`. Executions were counted by
patching `window.fetch` and reading the **`x-amz-target`** header, with request bodies captured via
`Request.clone().text()` to compare `QueryString` against the disclosed SQL.

**Two instrument traps, both hit and both worth knowing:**

- `read_network_requests` **silently stops capturing after a page navigation**. It reported zero
  Athena *and* zero `cloudfront` requests for a freshly loaded page. A negative from it is
  worthless without a positive control — the same shape as the archive script's trail-is-off
  warning. Every negative below was taken with a positive control in the same window.
- A patched `window.fetch` **does not survive a full page load**. Client-side nav (nav-tab clicks,
  `pushState` + `popstate`) preserves it; `navigate` does not.

## Data Explorer (`data-explorer-e2e.md`)

Fixture `explorer_fixture`: 30 rows, columns `id/region/owner/qty` all **string** (CSV ⇒ all-string
as decided), three `O'Brien` rows, one empty `qty` rendering as *(empty)*.

| Check | Executions | Result |
|---|---|---|
| Open the table | 1 | PASS |
| §1 apply is a new execution + new figure | 1 | PASS — 568 B → 1.1 KB, rows 1–7 |
| §3 cache hit — clear the filter | **0** | PASS — "Loaded from an earlier run in this tab — nothing more scanned", total held |
| §3 cache hit — re-apply the same filter | **0** | PASS — total held |
| §4 `O'Brien` against the real engine | 1 | PASS — rows 1–3, `WHERE "owner" = 'O''Brien'` |
| §5 failed apply | 1 (+retry) | PASS — mapped banner, previous rows kept, toolbar kept |
| §5 history Back | **0** | PASS |
| §5 Forward onto the failed step | **0** | PASS — exact wording + *Run it anyway* |
| SPEC-182 grouping | 1 | PASS — rows 1–4; south 8 / west 7 / east 8 / north 7 |
| SPEC-182 step 4 byte-identity | — | PASS — `identical: true` |
| SPEC-182 percentage absent from SQL, header says `(THIS PAGE)` | — | PASS |
| SPEC-182 Calc | **0** | PASS — across 3 function toggles and 2 reselections |
| SPEC-182 step 6 leaving grouping drops the sort | 1 | PASS — no `ORDER BY "count_all"` |
| SPEC-183 save | 1 PUT | PASS — after a HEAD on the exact key; no sidecar |
| SPEC-183 round trip | — | PASS — reopens with filters + ORDER BY, not a bare `SELECT *` |
| SPEC-179 deep-link refusal | **0** Glue, **0** Athena | PASS — only one S3 read of the user's own space list |

The grouped counts match the fixture exactly, which is what makes the GROUP BY result meaningful
rather than merely present.

## SPEC-186 FR-007 — dialog widths

Root font-size is **14px**, so `max-w-md` (28rem) is **392px** — a checker expecting 448px would
read every pass as a fail. All measured at a 1400px viewport with `max-w-md` present rather than
lost to `w-full`:

CreateFolderDialog, RestoreArchiveDialog, RenameDialog, CreateSharedConnectionDialog,
SaveQueryDialog (normal), CreateViewDialog, FilterValueDialog, AddMembersDialog — **8 of 9 at
392px, PASS**.

**Owed:** `SaveQueryDialog`'s second instance (the "There's nowhere to save this query" state),
which needs the personal space to be unavailable and cannot be staged from the UI.

**Beware:** `Drawer` also carries `role="dialog"`. Measuring `querySelector('[role="dialog"]')`
with a drawer open returns the **drawer** (440px, no `max-w-md`), not the modal. Select by title.

## SPEC-186 FR-003 — suggestion listbox containment

| Surface | `listbox.bottom` vs `dialog.bottom` | Cap | Result |
|---|---|---|---|
| Add members | 527 = 527, overhang **0px** | 113px | PASS |
| Share table / **Users** | −61px (headroom) | 114.25px | PASS |
| Share table / **Shared spaces** | −135px (headroom) | 114.25px | PASS |

Every cap is a measurement, not the old fixed `max-h-60` (240px); all three scroll, and arrow-key
navigation scrolls the active option into view (`scrollTop` 0 → 81.5) while containment holds.

**Do not misread the visible count.** Three of eight options are visible — the same number the
SPEC-158 failure reported — but the cause is now the opposite: then it overhung the panel by 97px,
now it is capped to fit. The Shared-spaces list offered exactly one option (`livecheck_186`, the
user's own space), which is SPEC-158's "no published directory of spaces" working.

## Saved queries (`saved-queries-e2e.md`) — check 1, personal half

PASS, byte-exact. Delete and Move both `aria-disabled="true"` with `disabled` **false** and
`tabIndex 0`, so the reason is in the tab order:

- Delete — `Saved queries live in this folder, so it can’t be deleted.`
- Move — `Saved queries live in this folder, so it can’t be moved or renamed.`

Clicking Delete opened **zero** dialogs and **zero** alertdialogs; the folder survived. The control
passed too: an ordinary folder shows both controls enabled with no reason, so the refusal is
specific rather than a generic failure.

**Owed:** the shared half, and check 2 (the bucket-policy Deny, CLI-only).

## Findings

1. **`EXPLORATION_PAGE_SIZE` is 100, so the script's ">25 rows" fixture cannot page.** Both pagers
   render disabled at 30 rows and §2 is unrunnable. Script corrected to ask for 150.
2. **The suspended state is per-mount.** Leaving `/explore` and returning loses the `useRef` set in
   `useExplorationQuery`, so the failed statement is re-submitted and the error banner shows
   instead of "Nothing has been run". **Accepted, not fixed** (user decision) — the promise is
   scoped to history navigation, Athena rejects the statement at `StartQueryExecution` so nothing
   is billed, and persisting the set would add a second writer to the tab's `sessionStorage` key
   that SPEC-181 deliberately kept to one.
3. **A failing apply issues TWO `StartQueryExecution` calls ~1.1 s apart.** This is `retry: 1` in
   `lib/queryClient.ts`, **not** a double-subscribe. Established by applying once with **no**
   navigation and watching it stop at exactly two and stay there for 20 s — an initial diagnosis
   blaming two subscribers was wrong and was withdrawn. It also proves Athena rejects this SQL at
   submit rather than failing it later, so no execution is created.
4. **Create view refuses through a toast**, not `Button.disabledReason` — the button reports
   `aria-disabled: null` and is genuinely enabled. Worth knowing when auditing FR-002 affordances.
   `Button.disabledReason` *is* in use on the file toolbar and the Explorer toolbar
   ("There are no filters, expressions, sorts or grouping to clear.", "Select some cells first.").

## Also created during this session

`livecheck_186` (shared space, owner `agriffith_three`) and `agriffith_three.explorer_fixture`
(table over `test_fixture_one/`). Both are live-check fixtures and can be deleted once the arc's
remaining checks are run.
