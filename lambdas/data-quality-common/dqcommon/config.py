"""Data-quality domain configuration (SPEC-108 FR-003).

Config style for this arc, settled here:

- **Per-deployment values** (queue URLs, the workgroup name, bucket names, the Cognito
  pair) are ENV VARS validated at import — and they live in ``cpcommon.config``, whose
  ``_require`` fail-fast runs at cold start for every verb that attaches the layer
  (SPEC-083 FR-001 / SPEC-107 FR-001). Do not re-declare them here.
- **``DQ_*`` tuning caps are MODULE CONSTANTS here.** They are product decisions, not
  deployment knobs: changing one changes what the report means, so it should be a
  reviewed code change rather than a per-environment env var somebody can drift.

The constants below are declared in the foundation so the later specs share one source;
each is consumed by the spec named against it.
"""

# SPEC-110 — source inspection caps.
# Max objects under the target location. Mirrors tscommon's SHARE_MAX_OBJECTS. There is
# deliberately NO max total size: that ceiling was a Lambda artefact, and Athena — not a
# Lambda — reads the data now.
DQ_MAX_OBJECTS = 1000

# SPEC-111 — the profile query's column ceiling.
# Athena caps a query STRING at 262,144 bytes. Four TRY_CASTs plus a null-ratio and a
# sample aggregate per column approaches that on a very wide table, so a source wider
# than this is rejected with a clear message rather than emitting an unparseable query.
DQ_MAX_COLUMNS = 200

# SPEC-112 — the byte-scan budget, PER REQUEST (never per file).
# Divided across the files in the manifest; every encoding figure is labelled sampled
# with its coverage percentage. v3 bounded this PER FILE (256 MiB x up to 1000 files
# ~= 276 GB through one 1024 MB Lambda in 300 s ~= 920 MB/s sustained, against a
# real-world ~60-100 MB/s) — it would have passed on a three-file fixture and timed out
# in production. That is the exact error class this arc's re-architecture exists to
# eliminate, so the budget is per REQUEST.
DQ_SCAN_TOTAL_BYTES = 2 * 1024**3  # 2 GiB
