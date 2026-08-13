# Component Inventory — router

Where the **reusable** building blocks live, so a spec can find what to reuse without re-reading
every delivery doc. This file is the cheap always-loadable router; **read only the row(s) you need**.

**Rule of thumb:** building anything → read `foundations` + `shared-components`. Working inside a
feature → also read that feature's file. Never read them all.

**Keep it current:** when a spec adds a reusable service / hook / component / type / utility, add a
one-line row to the matching file below (completion-ritual step 4). Add a *new row here* only when a
whole new area appears.

> Convention reminders (see `CLAUDE.md`): services return `ServiceResult<T>` and never throw; all S3
> calls go through service files; clients are instantiated in `src/lib/`, never in components; server
> state goes through TanStack Query. These files list the *public surface* — the code is the source
> of truth; verify signatures before relying on them.

## Shared (read when building anything)

| Area | File | What's in it |
|---|---|---|
| Foundations | `component-inventory/foundations.md` | `src/lib/` — AWS clients, credentials, `ServiceResult` adapters, `toUserMessage`, FIFO enqueue skeleton, query client |
| Shared components | `component-inventory/shared-components.md` | `src/components/` — Modal, ConfirmDialog, Drawer, Pager, Menu, MobileActionBar, Button/Input/Badge/Banner, ErrorBanner, Toast |
| Shared types | `component-inventory/shared-types.md` | `src/types/` |
| Shared hooks | `component-inventory/shared-hooks.md` | `src/hooks/` |
| UI primitive utility | `component-inventory/ui-primitive-utility.md` | `src/lib/` styling/primitive helpers |
| Test utilities | `component-inventory/test-utilities.md` | `src/test/` — `renderWithProviders` |

## Features (read the one you're working in)

| Feature | File |
|---|---|
| File browser | `component-inventory/file-browser-feature.md` |
| Catalog (shared by Query + Data Explorer) | `component-inventory/catalog-feature.md` |
| Saved queries (shared `.sql` store) | `component-inventory/saved-queries-feature.md` |
| Data Explorer | `component-inventory/data-explorer-feature.md` |
| Query | `component-inventory/query-feature.md` |
| Connections | `component-inventory/connections-feature.md` |
| Notifications | `component-inventory/notifications-feature.md` |
| Shared spaces | `component-inventory/shared-spaces-feature.md` |
| Data quality | `component-inventory/data-quality-feature.md` |
| Table builder | `component-inventory/table-builder-feature.md` |
| File send | `component-inventory/file-send-feature.md` |
| Archive | `component-inventory/archive-feature.md` |
| Help | `component-inventory/help-feature.md` |
| Auth | `component-inventory/auth-feature.md` |
| User directory | `component-inventory/user-directory-feature.md` |
| Table share | `component-inventory/table-share-feature.md` |
| Feature flags | `component-inventory/feature-flags-feature.md` |
