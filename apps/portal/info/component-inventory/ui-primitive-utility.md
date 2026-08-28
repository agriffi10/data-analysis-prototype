# UI primitive utility (`apps/portal/src/lib/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `cx(...args)` | `lib/cx.ts` | Class-name join helper (filters falsy); used by all SPEC-028 primitives. No external dep. **Returns `undefined`, not `''`, when nothing is truthy** — a `className ?? default` consumer falls back on the former and not the latter (SPEC-186 FR-007). |
| `FIELD_LABEL` / `FIELD_HINT` / `SECTION_CAPTION` | `components/fieldStyles.ts` | The one home for a field's label and hint (`Input` renders both; a `<legend>` cannot use `Input`) and for the small uppercase caption over a group, rail section or table header — one spelling where three had drifted across 22 files (SPEC-186 FR-010). |
| `DIALOG_PANEL` / `DIALOG_TITLE` | `components/dialogChrome.ts` | The body chrome `FormDialog` would render, for the four dialogs that cannot use it — their footer belongs to `DestinationPicker`. The reason "cannot" is legitimate is written out in the file (SPEC-186 FR-010 pattern C). |
| `formatPageTitle(page?)` | `lib/formatPageTitle.ts` | Pure title formatter → `"{page} — S3 File Portal"` or the app name alone (SPEC-031). |

