---
type: Decision
title: "Building a table is desktop-only, and that was decided rather than discovered (2026-09-04)"
description: "The create-table control is deliberately absent below 900px and Help says a wider screen is needed; the limit is on the control, not the capability, and any mobile path goes in the selection toolbar."
---

Removing the Data Explorer picker's "Create table from a folder…" section left no create-table
**control** below 900px, and nothing in the change said so. `CreateTableButton` is mount-gated
`!isMobile` on the Files toolbar and `MobileActionBar` carries only Restore, New folder and Upload;
`SourcePicker` had no width gate at all and `/explore` sits in the mobile nav drawer, so the deleted
section was the phone path.

**"The only way to create a table" is the claim to avoid here, and three things falsify it.**
`CreateTableButton` is the only caller of `enqueueTableBuild`, which is a narrower fact and the one
worth writing. Beyond it: `CREATE TABLE` typed into the Query editor runs through the same Athena
path as a `SELECT` (`athena.service.ts` does not inspect the query type), and the table-share plane
issues its own `CREATE EXTERNAL TABLE IF NOT EXISTS` server-side. The editor is desktop-only for an
unrelated reason — `QueryMobileView` is browse-first with no editor — but a **saved** query holding
DDL runs from the phone through the same submit path, and Help tells phone users their saved queries
are "ready to run", so that path is documented rather than obscure. The honest statement of the
limit is therefore about the CONTROL, not about the capability.

A review frame found it; the user accepted the limit rather than either of the two fixes offered.

**Why the fixes were declined, recorded so the option is not re-litigated as an oversight.** Moving
the control to the selection toolbar — where every other selection-driven action lives, and where
this one arguably belongs, since it builds from the SELECTED folder — is not width-gated and would
have fixed both layouts at once, at the cost of moving a control off the primary Files toolbar on
desktop, which nobody asked for. Adding a fourth control to the mobile bar leaves each about 81px at
375px — (375 − 28 − 21) / 4, with `px-4` and `gap-2` resolved against this project's **14px** root
rather than the 16px one a rem figure invites you to assume — so it needs an overflow affordance: more new mobile design than the batch that prompted it.

**What the decision obliges.** The Help step now says a wider screen is needed, because the previous
wording sent a phone user to a button that is not rendered — a guide pointing at an absent control
is the same failure the gated-surface registry exists to prevent, arriving through prose. If a
mobile create path is ever wanted, the selection toolbar is where it goes, and the `!isMobile` gate
on the Files toolbar is the thing to delete rather than duplicate.

## History

### 2026-09-04

- **Settled:** entered the register.
