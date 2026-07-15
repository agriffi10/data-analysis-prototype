# ── Dedicated Athena workgroup (SPEC-108 FR-003) ─────────────────────────────
# Every data-quality query (the profile query, the raw-line ragged check, the duplicate
# count) runs here — NOT in the shared portal workgroup. Three properties of this
# workgroup are load-bearing; each is a correction from an adversarial review of the v3
# architecture draft (data-quality-architecture.md §0.1), and each is easy to "fix" back
# into a broken state.
#
# 1. bytes_scanned_cutoff_per_query is UNSET (see below).
# 2. enforce_workgroup_configuration = false — the result location is per QUERY.
# 3. There is NO workgroup query-timeout field. Do not look for one.

resource "aws_athena_workgroup" "data_quality" {
  name = local.athena_workgroup_name

  configuration {
    # OFF on purpose: each StartQueryExecution supplies its own
    # ResultConfiguration.OutputLocation so results land in the REQUESTING SPACE's
    # athenaresults/ prefix. A workgroup has exactly ONE static result location, so
    # per-space routing is impossible any other way. Mirrors the portal workgroup
    # (modules/analytics/athena.tf) — do not "harden" this to true.
    enforce_workgroup_configuration    = false
    publish_cloudwatch_metrics_enabled = true

    # Pin engine v3 explicitly (not "AUTO") so engine upgrades are a deliberate,
    # reviewed change rather than silent — same discipline as the portal workgroup.
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    # bytes_scanned_cutoff_per_query is DELIBERATELY NOT SET.
    #
    # The disaster this prevents: the portal workgroup carries a 10 GiB scan cutoff as a
    # cost guardrail (modules/analytics/athena.tf). A data-quality check runs over sources
    # up to 250 GB — 25x that ceiling — so copying the existing module's shape would make
    # EVERY REAL CHECK FAIL with "bytes scanned limit exceeded". Setting any cutoff here
    # re-breaks the feature.
    #
    # Stated plainly: this removes the project's only cost guardrail on its most expensive
    # operation, deliberately. Athena bills ~$5/TB scanned and this pipeline scans the
    # source MORE THAN ONCE (profile query + raw-line ragged check + duplicates), so a
    # 250 GB check is roughly $2.50-$3.75, and nothing caps how many checks a user runs.
    # Revisit before real users arrive (data-quality-architecture.md §10).

    result_configuration {
      # DEFAULT/fallback only. Every real query supplies its own OutputLocation (above);
      # anything that ever omits one writes to the admin-only bucket, never to a
      # user-readable place. Same fallback-results/ prefix convention as the portal
      # workgroup, so the admin bucket's expire-admin-results lifecycle rule covers it.
      output_location = "s3://${var.admin_bucket_name}/fallback-results/"
    }
  }

  # NOTE — THERE IS NO WORKGROUP QUERY-TIMEOUT SETTING. The DML query timeout is an
  # ACCOUNT/REGION SERVICE QUOTA ("DML query timeout"), 30 minutes by default and
  # raisable to 240 minutes only via a quota-increase request (a support ticket, not
  # Terraform). That quota — not Athena's throughput and not any field here — is the real
  # ceiling on this feature: a check that cannot finish inside it fails as a terminal
  # query_timeout. Nobody should go looking for a Terraform field for this.
  # Status: deliberately NOT raised yet (user decision, 2026-07-14) — the arc is in
  # testing/concept, where the 30-minute default is sufficient; request the increase when
  # real 250 GB sources arrive.
}
