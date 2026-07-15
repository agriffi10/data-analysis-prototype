"""Report assembly + the report schema (SPEC-112 fills this in).

Stubbed namespace (SPEC-108 skeleton). Will hold the report.json shape written to
{space}/_data-quality-reports/{requestId}/report.json — a key that is a PURE FUNCTION of
requestId, so a retry overwrites it byte-identically (this is how the pipeline is
replay-safe; no verb in this codebase does request-id idempotency checking).

The report distinguishes EXACT findings (type consistency, null ratios, row counts,
duplicates, cross-file column agreement) from APPROXIMATE ones (ragged rows over-report
when delimiters OR newlines appear inside quotes; encoding is sampled with its coverage
percentage) — and the notification says so too. An unqualified "clean" over a sampled
encoding check would be a lie.
"""
