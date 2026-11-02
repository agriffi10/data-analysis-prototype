---
type: Decision
title: "Data-quality report view (SPEC-113)"
description: "The report route carries the space: the actor's own username wins over a same-named shared space, and an unreachable space renders the denied state without issuing any S3 request."
---

The report is read at `/data-quality/:space/:requestId` — **the space is in the route, not derived**, because `requestId` alone cannot say which space holds `{space}/_data-quality-reports/{requestId}/report.json`. Resolution precedence: the actor's **own username always wins**; shared-space names are consulted only when the segment differs (SPEC-114's link builder pins the same rule). An unreachable space renders the friendly denied state and **issues no S3 request** — no existence oracle. The SPA's report types mirror `dqcommon/report.py` byte-for-byte; the banner **warns on `hasIncompleteFigures`** and only softly qualifies on `hasApproximateFigures`, which is true on every report the arc can produce. Detail: `spec-delivery/SPEC-113`.

> **Fixed (2026-09-16) — a folder's report named it without its slash, so Open folder opened the
> parent.** SPEC-112 and SPEC-123 both specify `"location": "alice/sales/"` for the report and the
> runs-index entry, but validate-authorize normalises the location with `posixpath.normpath`, which
> drops the slash, and every verb threaded that form — so the report, the completion notification and
> the runs row all named a folder the way a file is named, and `sourceFolderPrefix` reduced it to its
> parent. The code never met the contract; the browser's fixtures and assemble-report's own
> test event were written to the contract, which is why nothing caught it. `assemble-report` now
> spells the location from the `pathFilter` inspect-source carries — a folder target has none — and
> threads that form onward, so one fix corrects all three places the location is shown. It reads the
> value through `carried_path_filter` and refuses a state without it, like the two verbs before it.
> **Reports written before the fix keep the slash-less form, and Open folder on one still opens the
> parent** — a known limit, decided, with no browser fallback.

## History

### 2026-09-16

- **Changed:** `assemble-report` now spells a folder's location with its slash, so Open folder opens the folder; older reports keep the limit.

### 2026-07-21

- **Settled:** SPEC-113.
