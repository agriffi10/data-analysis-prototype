---
type: Decision
title: "A table's LOCATION is read recursively, so the space root is not a data folder (2026-08-19)"
description: "**A table's `LOCATION` is read recursively**, so the space root is not a data folder — and **both planes that build one over a user's folder refuse it**, table-builder on a create and data-quality on a check. Excluding the app-managed sub-trees from the plane's LISTING does not help, which is the trap: the manifest is what the plane knows about, the location is what Athena reads. A single FILE at the root is not this case — its queries carry a `\"$path\"` predicate, **decided once, by inspect-source, and carried on the state**: a verb that re-reads the manifest re-decides, and the manifest is an object that can change between two reads."
---

AWS is explicit: "Athena reads *all* data stored in the Amazon S3 folder that you specify." A table
built at a space root therefore covers `athenaresults/`, `saved_queries/`, `user_settings/`,
`shared_files/`, `shared_tables/` and `archive/` as well as the user's own data. It does not fail —
it **succeeds**, and every later read returns the portal's own bookkeeping mixed into the answer.
Succeeding is what makes it worth blocking rather than warning about.

Refused on the control with its reason (`createTableRefusal`, on `writeLockRefusal`'s
predicate-with-its-words precedent) and in `validate-authorize` as `location_is_space_root`. A
refusal rather than a hidden control: the button is where a user standing at the root looks for it,
and a control that vanishes teaches nothing about where to go instead. **Creates only** — a refresh
reads the location the table already has, so refusing one would strand any root table already in a
catalog with no way to repair it.

> **Extended (2026-09-15) — the rule was one plane short.** A data-quality check builds an external
> table over its target too, and its validator explicitly ALLOWED the root ("a legitimate, if broad,
> folder target") while the dialog offered it as the DEFAULT. So the numbers a user got for "check
> my whole space" counted the space's own `system_settings/athenaresults/` — including the running
> check's own output, which lands inside the table it is reading — plus archive receipts and
> shared-table copies. The listing already skipped those and it changed nothing, because the
> manifest is not the location. Now refused under its own reason, `location_is_space_root`,
> re-declared in `dqcommon.messages` rather than shared: the planes are independent, so **a change
> to this rule belongs in both validators**. A single file at the root stays allowed — its queries
> carry the `"$path"` predicate, so its numbers are its own — and the picker exempts a selected
> file from the folder gate for exactly that reason.
>
> **The validator's refusal is not the only route to a root table, and the second one is easy to
> miss.** `_location` promotes a SINGLE-file target to its parent folder, so a `single_file_path`
> answering "one file" for a target that is not one turns a folder ONE LEVEL BELOW the root into a
> table over the root — measured, not reasoned. The containment assertion in `_location` cannot
> catch that: the space root is inside the space. What catches it is the negative control on
> `single_file_path`, which is the only test in the fleet that plant fails. Of the exemption's two
> failure modes only one is a leak — a MISSING predicate widens the read to the whole space, a
> wrong escaper (the quoting fence) makes it match NOTHING, a zero-row report. Presence is
> pinned both ways now; the escaper is pinned by nothing, and an apostrophe is legal in an S3 key.
>
> **Fixed (2026-09-16) — the exemption was decided twice, from an object a caller could write.**
> create-temp-tables promoted the table and start-profile-query attached the predicate, and EACH
> called `single_file_path` over the manifest it had just loaded — one definition, two reads. The
> manifest key is a function of the caller's own request id and the API's object routes took writes
> under `_data-quality-reports/`, so a two-file list written between the verbs left the table over
> the root and the queries unnarrowed. A create RETRY re-read it too, so moving the call into create
> alone would still have been once per attempt rather than once per run. Now inspect-source decides
> over the list it holds in memory and carries `pathFilter`; each verb that reads that value refuses a
> state without it rather than default to "a folder". Two guards narrow what a replaced manifest
> can still do. The manifest loader refuses any file outside the checked location — byte-scan GETs
> each listed key under a role that reads both buckets whole, so a forged list was also another
> tenant's bytes — and that holds whoever wrote the object. The object routes refuse the reports
> folder (`protected.is_in_reports_folder`), and so does the file-ops plane, the other writer a
> member reaches: it judged a copy or move by its destination prefix alone, so moving a nested
> `_data-quality-reports/` folder to the root wrote there and deleting a report was accepted. It now
> refuses each item's derived key and the folder as a delete or move source, with no role Deny
> behind it by choice — [where each item lands](../storage/an-item-copied-into-itself-is-refused-per-item-where-a-containment.md).
> **Closed 2026-09-16:** a request id reused past the dedup window shared the temp table, whose
> create is `IF NOT EXISTS`, so a folder check could inherit a running root-file check's table and
> query it unnarrowed, held off only by the shared Athena tokens. One execution now claims the id
> before anything is named from it — [the claim](../control-planes/a-data-quality-request-id-is-claimed-by-one-execution-before-anything.md).
>
> **Extended (2026-09-16) — the report page offered a Re-run the server refuses.** A report written
> before the refusal can name the top of a space, and its **Re-run check** sent that location
> straight back, to be refused by notification after the click. The button now carries the picker's
> own sentence as its disabled reason, through `rerunRefusal` beside `CHECK_AT_ROOT_REFUSAL` in
> `dataQuality.format.ts`, which mirrors the server's check on `isAtRoot` as `createTableRefusal`
> does. A report written then stored its location in the server's normalised form, without the
> slash, so the location gains a trailing slash before the comparison; a single file at the root stays re-runnable, for the predicate's reason above.

## History

### 2026-09-16

- **Changed:** The single-file exemption is decided once by inspect-source and carried as `pathFilter`; the object routes and file-ops refuse the reports folder.
- **Changed:** A data-quality request id is claimed by one execution, closing a reused id's inherited temp table.
- **Changed:** The report page disables Re-run for a location at the top of a space, with the picker's sentence as its reason.

### 2026-09-15

- **Changed:** The space-root refusal extended to data-quality, whose validator had allowed the root.

### 2026-08-19

- **Settled:** entered the register.
