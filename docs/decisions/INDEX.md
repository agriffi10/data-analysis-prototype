# Key Decisions — the register

The settled architectural decisions, in full. **Don't re-litigate these.** Each area file opens
with its **Fences** — the one-line reminders that used to be `CLAUDE.md`'s always-loaded digest,
the traps that apply green and fail later — and carries beneath them the reasoning, the
constraints, and the explicit "do NOT build" entries. `CLAUDE.md` keeps only a table pointing at
each area's Fences; a path-scoped rule under `.claude/rules/` points there too when the area's code
is read.

This file is a **router**. One file per area, one `##` heading per entry, and each file opens with its
own Contents — so a lookup is one hop and never a whole-register read.
[`docs/architecture.md`](../architecture.md) → *Architecture Decision Record* indexes the subset of
these that decide the system's **shape**, and links back here.

| Area | File | What it settles |
|---|---|---|
| Identity, access and the name that ties them together | [`identity-and-access.md`](identity-and-access.md) | Cognito, the one shared role and its principal tags, the API's verifier and credential planes, the username that is also a prefix and a database name |
| Storage, and the fact S3 is not a filesystem | [`storage.md`](storage.md) | filesystem UX over a store with no move or rename, the file-send and file-ops rules, saved queries, the settings document |
| Control planes — one pattern, seven planes, and the traps are shared | [`control-planes.md`](control-planes.md) | the shape every privileged pipeline follows, the ASL and notification fences, the layer split, structured logging |
| Analytics, the catalog, and two SQL dialects | [`analytics.md`](analytics.md) | the Athena/Glue/Lake Formation workspace, TBAC table creation, the two escaper axes, refresh and the data explorer |
| Archive and restore — the only place a mistake is unrecoverable | [`archive-and-restore.md`](archive-and-restore.md) | the GLACIER vault, the commit gate, the destination guard that runs twice, and the surface built to refuse its own affordance |
| The browser | [`browser.md`](browser.md) | state split, dialogs, the shared-layer import rule, the measured palette, grid geometry, error wording |
| Infrastructure, IAM and delivery | [`infrastructure.md`](infrastructure.md) | OpenTofu layout, the deploy role, CSP and caching, the runtime configuration document, the container platform |
| Gates, scanners and tests | [`gates-and-tests.md`](gates-and-tests.md) | what a gate blocks on, why "did not run" is never clean, the `ACCEPTED_` tripwires, declared floors |

## The areas are a closed set

The eight above are the rows of `CLAUDE.md`'s Key Decisions table, and `scripts/validate_docs.py`
enforces that the two agree — one file here per table row, in the same order, each opening with
its Fences, and one pointer rule per row under `.claude/rules/`. The register used to be one file ordered by spec number, which made a set of settled fences
read as a changelog of things that had happened. **An entry belongs to the area a reader would look
in, not to the arc that produced it.**

A decision that fits no area means the table needs a new row. Add the row, the file with its
Fences, and the rule together rather than filing the entry loose.

## Writing an entry

When a spec settles a *new* decision: the full entry lands **here first**, then one clause in the
same file's Fences (completion-ritual step 5) — a fence is never the only home of a fact.

- One `##` heading per entry, in the area file, its label matching the bold label of its Fences
  clause, listed in that file's Contents.
- A decision that changes the **shape of the system** also gets a row in
  [`docs/architecture.md`](../architecture.md) → *Architecture Decision Record*. That row is an index
  entry — title, one-line context, a short note — and points back here for the reasoning.
- When a decision **reverses an earlier one**, update the old entry in place *and* add a superseded
  marker (a short blockquote: what changed, which spec, where the full entry lives) at every other doc
  site still stating the old claim — `ARCS.md` arcs, `architecture.md` sections.
