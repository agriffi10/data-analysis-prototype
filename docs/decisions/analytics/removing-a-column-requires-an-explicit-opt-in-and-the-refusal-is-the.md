---
type: Decision
title: "Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)"
description: "A refresh that would drop a column changes nothing and fails with `columns_removed`, naming the columns; the user resubmits with `allowRemovals: true`, which is validated as a boolean, authorises that one run and is persisted nowhere."
---

A refresh that would drop a column does **nothing** and fails terminally with `columns_removed`,
naming the columns in the notification. The user re-submits with `allowRemovals: true`. Removal is
singled out because it is the one class of change that breaks things somewhere the person who ran
the refresh is not looking: every saved query, view and dashboard referencing the column starts
failing, and nothing tells them.

**Two designs were rejected, and they are the two a later reader will propose.** *A plan-then-apply
pair* — run one writes a plan artifact into the user's prefix, notifies, the user clicks Apply, run
two references the plan. The textbook shape, and it costs a new artifact, a new index, a new view, a
new IAM surface and two async round trips for what the user experiences as one button. *A
browser-side preview* — the browser can already read the table's Glue columns and list the folder,
but it **cannot infer types**: that needs polars over a bounded Parquet footer or CSV head, which is
why `infer-schema` exists and needs polars, which was a 240 MB layer until SPEC-213 put it in the fleet image. A preview showing guessed types would be a
preview of something other than what the apply does.

**What the chosen design guarantees, stated honestly:** the *specific columns* are named to the user
in a durable notification before any removal happens. It does **not** guarantee they read it —
SPEC-145's dialog requires an explicit tick with explicit consequence copy, and names the columns
when it can via the notification's link. Do not overclaim this as consent.

**Three things about the mechanism are load-bearing.** (1) **`allowRemovals` is validated, not
coerced** — a non-boolean is refused, because truthiness reads the string `"false"` as opting *in*,
on the one flag that authorises data loss. (2) It is **persisted nowhere** — not on the table, not in
a registry, not in an index; a test greps the Lambda tree for it. The flag authorises one run, and a
stored copy would carry that authorisation into a refresh nobody opted into. (3) **The notification
link is the only channel that names the columns to the browser**, and its column names are
**percent-encoded** — column names are NOT catalog-safe (`infer-schema` reads them verbatim from a
file header and nothing validates them), so `Order ID` puts a raw space in a URL and `&` invents a
query parameter. SPEC-145 must not re-validate them as identifiers: `CATALOG_IDENTIFIER_RE` rejects
`id`, `ts` and `Amount`, which would discard the whole link for most real tables.

> **Superseded in part by SPEC-149 (2026-08-04): the apply is no longer a DROP + CREATE.** It is a
> single in-place `glue:UpdateTable`, so the metadata loss described below no longer happens and the
> reason codes named in it are gone. Everything above this line — the opt-in, the refusal-as-warning,
> the three load-bearing mechanism points — is unchanged. See *The refresh apply replaces the
> definition in place* below.

**The apply WAS a DROP + CREATE, and what that cost is recorded in SPEC-144 FR-004** — table
identity, `Description`/`Owner` and any table-level Lake Formation grant were destroyed with the
catalog entry (column comments were carried). `ALTER TABLE ADD COLUMNS` cannot retype or remove, so it
would have covered only the easiest third. Full account:
`docs/spec-delivery/SPEC-144-refresh-table-schema-diff-and-apply.md`.

## History

### 2026-08-04

- **Settled:** SPEC-144.
- **Changed:** The apply stopped being a DROP + CREATE and became one in-place `glue:UpdateTable`; the opt-in is unchanged.
