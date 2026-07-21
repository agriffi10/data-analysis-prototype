# Data-quality feature (`apps/portal/src/features/data-quality/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `enqueueQualityCheck(req)` | `dataQuality.service.ts` | The browser's only data-quality write: FIFO-sends the SPEC-109 envelope to `VITE_DATA_QUALITY_QUEUE_URL`; `MessageGroupId` = SHA-256 of `{bucket}/{location}` (a hash, because SQS caps group ids at 128 chars and S3 keys reach 1024), dedup = `requestId` (SPEC-109). |
| `useDataQualityCheck()` | `useDataQualityCheck.ts` | `{start, isPending}` — mints the request id, enqueues, and reports the outcome ONLY as a toast (success, or `toUserMessage` on failure) so it can be reused with no dialog mounted. Ref-guarded against re-entry (SPEC-113). The toast stops at "started" because the *result* arrives as a notification carrying the report link (SPEC-114). |
| `DataQualityDialog` | `DataQualityDialog.tsx` | Read-only-check confirmation on the shared `ConfirmDialog`: names the target space-relative, states plainly that nothing is modified, locks while in flight; closes either way (SPEC-113). |
| `getQualityReport(bucket, space, requestId)` | `dataQualityReport.service.ts` | Reads `{space}/_data-quality-reports/{requestId}/report.json`; a missing or structurally-invalid document is a typed failure, never an empty "clean" report. Also exports `reportKey` (SPEC-113). |
| `useDataQualityReport(space, requestId)` | `useDataQualityReport.ts` | Resolves the `:space` segment (own username wins; shared names only when it differs), then fetches. Never fetches for an unreachable space, and waits for the connections list so it can't cache a wrong-bucket read. Also exports pure `resolveSpace` (SPEC-113). |
| `DataQualityReportPage` | `DataQualityReportPage.tsx` | The `/data-quality/:space/:requestId` view: verdict banner, summary tiles (2×2 → 4-up), top issues, columns table→cards (`useIsMobile` mount-gated), cross-file disagreements, qualifier callouts, metadata footer. Every approximate/skipped/not-computed figure renders with its reason (SPEC-113). |
| `DataQualityReport` + figure types | `dataQuality.types.ts` | The report shape, mirroring `dqcommon/report.py` byte-for-byte, plus the `isSkipped`/`isNotComputed`/`isUnmeasured`/`isTypedColumn` narrowing helpers that keep "could never apply" and "tried and failed" from collapsing (SPEC-113). |
| `asSentence`, `isApproximateIssue`, `sourceFolderPrefix`, `formatRatio`, `locationLabel` | `dataQuality.format.ts` | Report presentation helpers: sentence-case a Lambda-authored reason fragment, classify a top-issue line as exact vs approximate (pinned to `report.py::top_issues` wording by test), reduce a file key to its parent folder, percentages that distinguish none from rounds-to-none (SPEC-113). |
| `csvReport()`, `parquetReport()` | `reportFixtures.ts` | Report fixtures whose shapes **and wording** are copied from `dqcommon/report.py`, so the "approximate is always qualified" assertions test against real text rather than invented text (SPEC-113). |

