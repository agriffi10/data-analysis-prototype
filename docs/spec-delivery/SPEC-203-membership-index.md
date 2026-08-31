# Completed Spec — SPEC-203: The Membership Index

## What was completed?

A per-user projection answering *which shared spaces is this caller in*, and the seam that lets the
credential-minting path read it instead of the Cognito claims.

- **The index**: `s3://{admin-bucket}/memberships/{username}.json`, `{version, username, spaces:
  [{name, status}], updatedAt}`, written under ETag CAS by
  `lambdas/shared-space-common/membership_index.py`. Never deleted — a user with no spaces holds an
  empty list.
- **Six writers**, one per verb that moves a Cognito membership slot: create, add-members,
  remove-members, leave, delete, forget. A write failure **fails the run** and is notified through
  the plane's existing per-verb catcher; it does not inherit the roster fan-out's best-effort
  posture.
- **The source is a cold-start choice**: `MEMBERSHIP_SOURCE` is `claims` (default, and what every
  environment runs) or `index`. `lambdas/api/apicommon/memberships.py` holds both implementations
  behind `resolve`; an unrecognised value raises at import.
- **The read door**: `identity.membership_index_document`, on the execution role, outside
  `ROUTE_PLANES` by module identity rather than by route declaration.
- **Grants**: `s3:GetObject` on `memberships/*` plus a `s3:ListBucket` conditioned to the same
  prefix, on the API's execution role and the shared-space orchestrator.

Three PRs plus this one: #564 (grants), #565 (index and writers), #566 (source, read, route check).

### Deliberate deviations

- **FR-008 said "no `ListBucket`, and that is the load-bearing half."** It cannot stand beside
  FR-003: S3 answers `NoSuchKey` only to a caller that can list, so a read-only grant makes an
  **absent** index — the correct state for every user in no shared space — arrive as
  `AccessDenied`. The register's settled remedy is a *conditioned* grant scoped to the keys read,
  which is what shipped. The condition is what carries the safety, and it is asserted by pattern
  rather than by presence.
- **FR-003's "cached with the credentials under the existing key" is not constructible.** That key
  is the whole tag set, which is what the read produces. One `GetObject` per authenticated request,
  no new cache — a username-keyed one would freeze membership for the container's life, which is
  what FR-006 promises against.
- **FR-004's literal zero-AWS-calls refusal is not satisfiable under `index`.** The request has
  already read the caller's own index to have an identity at all. What is asserted is that the
  refusal itself reaches no service — no assume, no listing.
- **A delete's ordering follows SPEC-151, not FR-001's post-SPEC-205 reasoning.** `reg.delete` still
  frees the name today, so the index drops ride the member loop that runs before it. The same
  correction applies to `shared-space-forget`'s teardown path, which drops the **whole roster's**
  entries — "a failed create is single-member" does not cover a delete that failed partway.
- **`create`'s write is inside the provisioning guard**, which FR-001 did not say. Outside it, a
  failed write leaves an `active` space whose owner holds no entry and therefore, under `index`,
  can neither reach it nor delete it.
- **`router.py` changed**, which FR-011 said would not. `for_request` runs before dispatch, so an
  unresolvable identity would otherwise arrive as a bare `InternalError`. `apicommon/spaces.py`
  needed no *functional* change at all — it already reads the shared identity.
- **FR-010's `debug` level does not exist** in `cpcommon.observability`; the non-active record is
  `info`. The source and space set are also stamped **per request**, not only per mint, because
  FR-007's live check reads them back from an arbitrary request and most are warm.
- **Both catalog-rule checks are new and are index-only.** The spec's Premise 4 was not true when
  written; `_from_index` makes it true for the path where a space name becomes a principal tag
  value. The claims path cannot check it without rewriting the equivalence it preserves.
- **`MEMBERSHIP_SOURCE` is wired into no Terraform**, per FR-011. FR-007's live check therefore
  cannot be run until it is — an `owed.md` row says so.

## What changed from earlier specs?

- `apicommon/identity.py`: `memberships_from` now delegates; `identity_from` resolves through the
  configured source; `SHARED_SPACE_CLAIM` is re-exported from `memberships`. No existing test needed
  editing, which is the check that the extraction changed no behaviour.
- `apicommon/config.py` gains `admin_bucket()`; `ADMIN_BUCKET` joins the identity block.
- `apicommon/spaces.py`: docstring only. Its "reads claims and nothing else" claim went false.
- `lambdas/test_deploy_matrix.py`: `test_the_layer_copy_list_matches_the_layer_directory` and
  `test_no_unchecked_explicit_copy_list_was_added` **restored**. Both were deleted in #540 with the
  helper, the constant and two by-name citations left behind, so the shared-space layer's explicit
  module list could drift from its directory silently — a cold-start `ModuleNotFoundError` after a
  green suite and a green deploy. This spec adds a module to exactly that list.
- `lambdas/test_api_module.py`: `API_ROLE_ALLOWED_ACTIONS` widened by the two S3 actions.

## Verification

Local, on every PR: `ruff`, `scripts/validate_docs.py`, blocking `mypy`, `pytest lambdas/` (exit
code, not the printed count), `tofu validate`. CI green on each PR and on `main` after each merge.
No `apps/portal` file was touched.

Every guard whose failure would be silent was planted and reverted — the grant conditions, the
copy-list drift, the three write orderings, the verb-enumeration sweep, the denial-as-absence
tolerance, the over-cap refusal, the source fallback, the router clause, the cache bypass, and both
observability fields. One equivalent mutant is named in the code review rather than chased.

**Owed, not run:** FR-007's live parity check (needs a deployed environment with
`MEMBERSHIP_SOURCE=index`, of which there are none) and FR-009's deployed-role IAM simulation.
`docs/testing/owed.md` carries both, with the caveat that the parity comparison **cannot be re-run
after the environment moves**.
