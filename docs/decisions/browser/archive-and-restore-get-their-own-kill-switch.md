---
type: Decision
title: "Archive and restore get their own kill switch (SPEC-246)"
description: "`archive` is one default-on, presentation-only kill switch over archive and restore: off, the controls and guide leave the UI, while the routes stay live and the notifications remain."
---

`archive` is the eighth key and the second kill switch, over the one surface where a mistake cannot
be undone: an archive copies files into a Glacier vault and deletes the originals. It earns a key for
the reason `asyncFileOperations` did — the only other way to withdraw either gesture was
`files: false`, which removes the whole file browser — and publishing it needs no app build. Default
**on**, so an unreadable document never withdraws it.

**One key covers both directions.** Archive and restore run on one state machine, so a defect found
in it can reach either, and hiding Restore delays data that already takes hours to return rather
than losing any. Two keys would ask an operator to diagnose which half is at fault before throwing
either.

**Presentation only.** Off, the Archive and Restore controls leave the file browser — the selection
toolbar, both details panels, the primary toolbar and the mobile action bar — and the archive guide
leaves Help. The `archive.archive` and `archive.restore` routes stay live and ungated, and a
hand-built request still enqueues: a flag never authorizes (the `identity-and-access` fences), and
stopping the plane itself is an operator action on the infrastructure. An execution in flight
finishes, and an open session keeps the controls until it next reads the document —
`apps/portal/info/runtime-configuration.md` says when.

**What it leaves alone.** Archive and restore notifications and their `/files` links are not gated:
the record of what happened outlives the surface that started it. That has one visible consequence,
accepted rather than engineered around — an archive notification tells its reader to choose
**Restore Archived Data** and enter the id, and while the switch is thrown that control is absent.
The switch is an incident measure, and the id stays in the receipt folder, `system_settings/archive/`,
which stays listed and write-locked. The "Rename, move, copy, or delete" guide names Archive in
passing and stays visible.

**One surface, two flags, two rows.** The `files` gate in `FileBrowser.tsx` stays, so each entry
point is registered under both flags — one row per (surface, flag), because either gate can be
deleted alone, on the precedent of `Explore data`. A registry name keys the walking test's recipes
and must be unique, so the `archive` rows carry descriptions (`Archive in the selection toolbar`)
whose recipes query the accessible names the `files` rows carry, and `GatedSurface.name` now says a
name may be either. The folder details panel and the mobile action bar are not rows; they are
asserted in `archiveJourney.test.tsx` and `FileBrowser.test.tsx`.

## History

### 2026-09-26

- **Settled:** SPEC-246.
