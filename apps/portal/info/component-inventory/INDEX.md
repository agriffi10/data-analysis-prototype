# Component Inventory — index

Where the **reusable** building blocks under `apps/portal/src/` live, so a spec can find what to
reuse without re-reading every delivery doc. This file is the cheap always-loadable router; **read
only the row(s) you need**.

**Rule of thumb:** building anything → read `foundations` + `shared-components`. Working inside a
feature → also read that feature's file. Never read them all.

**Keep it current:** when a spec adds a reusable service / hook / component / type / utility, add a
one-line row to the matching file below (completion-ritual step 4). Add a *new row here* only when a
whole new area appears — and the row belongs in the file matching the component's **path**, so a
`features/query/` addition goes in `query-feature.md` and nowhere else. CI reads every File cell
against the tree and every Symbol cell against what those files export, and refuses a table without
a File column and a row that names source but no symbol; `_inventory_row_problems` in
`scripts/validate_docs.py` says which forms a cell may take. A row that outlives its file, or a
name that leaves the file its row points at, fails the build.

> Convention reminders (see `CLAUDE.md`): services return `ServiceResult<T>` and never throw; the API
> is reached only through service files, never from a component, and no `@aws-sdk/*` package may be
> added; server state goes through TanStack Query. These files list the *public surface* — the code is the source
> of truth; verify signatures before relying on them.

**Adding a configuration key** is not an inventory question and has its own checklist — a key is
wired in five places and a missed one stops the container starting:
[`../runtime-configuration.md`](../runtime-configuration.md).

## Shared (read when building anything)

| Area | File | What's in it |
|---|---|---|
| Foundations | [`foundations.md`](foundations.md) | `src/lib/` — the API client, the ID token, `ServiceResult` adapters, `toUserMessage`, JSON documents, runtime config, query client |
| Shared components | [`shared-components.md`](shared-components.md) | `src/components/` — Modal, ConfirmDialog, Drawer, Pager, Menu, MobileActionBar, Button/Input/Badge/Banner, ErrorBanner, Toast |
| Shared types | [`shared-types.md`](shared-types.md) | `src/types/` |
| Shared hooks | [`shared-hooks.md`](shared-hooks.md) | `src/hooks/` |
| UI primitive utility | [`ui-primitive-utility.md`](ui-primitive-utility.md) | `src/lib/` styling/primitive helpers |
| Test utilities | [`test-utilities.md`](test-utilities.md) | `src/test/` — `renderWithProviders` |

## Features (read the one you're working in)

| Feature | File |
|---|---|
| File browser | [`file-browser-feature.md`](file-browser-feature.md) |
| Catalog (shared by Query + Data Explorer) | [`catalog-feature.md`](catalog-feature.md) |
| Saved queries (shared `.sql` store) | [`saved-queries-feature.md`](saved-queries-feature.md) |
| Data Explorer | [`data-explorer-feature.md`](data-explorer-feature.md) |
| Query | [`query-feature.md`](query-feature.md) |
| Connections | [`connections-feature.md`](connections-feature.md) |
| Notifications | [`notifications-feature.md`](notifications-feature.md) |
| Shared spaces | [`shared-spaces-feature.md`](shared-spaces-feature.md) |
| Data quality | [`data-quality-feature.md`](data-quality-feature.md) |
| Table builder | [`table-builder-feature.md`](table-builder-feature.md) |
| File send | [`file-send-feature.md`](file-send-feature.md) |
| Archive | [`archive-feature.md`](archive-feature.md) |
| Help | [`help-feature.md`](help-feature.md) |
| Auth | [`auth-feature.md`](auth-feature.md) |
| User directory | [`user-directory-feature.md`](user-directory-feature.md) |
| Table share | [`table-share-feature.md`](table-share-feature.md) |
| Feature flags | [`feature-flags-feature.md`](feature-flags-feature.md) |
| Feedback | [`feedback-feature.md`](feedback-feature.md) |

Sibling tree: [`../best-practices/INDEX.md`](../best-practices/INDEX.md) for the React and
accessibility rulebooks — consult those *before* writing a component, this index for what already
exists to reuse.
