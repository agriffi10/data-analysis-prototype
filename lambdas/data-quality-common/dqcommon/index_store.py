"""The per-space runs index (SPEC-123 fills this in).

Stubbed namespace (SPEC-108 skeleton). Will append one small entry per completed check to
{space}/_data-quality-reports/index.json under OPTIMISTIC ETAG CAS — the same lost-update
fix SPEC-082 applied to the shared-space registry, needed here because checks of
DIFFERENT locations run in parallel (the queue's MessageGroupId is the hashed location,
so only same-location checks serialize).

Why an index exists at all: without it the dashboard would have to list the reports prefix
and GET every report to build a row, and S3 lists lexicographically by key — so ordering
by requestId (a UUID) gives NO chronology at all. The index makes the dashboard one GET.

The index is a CONVENIENCE, NEVER A DEPENDENCY: an exhausted CAS is logged and swallowed —
the report still lands and the notification still fires; the run is merely missing from the
dashboard. The report is the artefact.
"""
