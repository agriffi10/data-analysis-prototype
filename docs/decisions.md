# Key Decisions — full register

The settled architectural decisions, in full. **Don't re-litigate these.** `CLAUDE.md` carries a
one-line digest of each; this file carries the reasoning, the constraints, and the explicit
"do NOT build" fences. Pull the entry you need — you rarely need them all.

**Grouped by AREA — the same eight areas `CLAUDE.md`'s Key Decisions digest groups by**, and a
closed set that `scripts/validate_docs.py` enforces. It used to be ordered by spec number, which made
a register of settled fences read as a changelog of things that had happened; grouping is what the
digest was fixed by, and this is the same fix. An entry belongs to the area a reader would look in,
not to the arc that produced it.

When a spec settles a *new* decision: full entry here **first**, then one line in `CLAUDE.md`
(completion-ritual step 5) — the digest line is never the only home of a fact. One `###` heading per
entry, under its area's `##` heading, label matching the CLAUDE.md bold label, listed in the Contents.
A decision that fits no area means the digest needs a new one; add it in both places rather than
filing the entry loose. When a decision **reverses an earlier one**, update the old entry in place
*and* add a superseded marker (short blockquote) at every other doc site still stating the old claim
(`ARCS.md` arcs, architecture.md sections).

## Contents

**Grouped by AREA, matching `CLAUDE.md`'s Key Decisions digest.** Jump to the entry you
need — never read this file whole. An area's heading is a signpost, not an entry; the
entries are the `###` headings under it.

**Identity, access and the name that ties them together**

- [Auth](#auth)
- [Hosted UI = Managed Login v2](#hosted-ui--managed-login-v2)
- [No backend](#no-backend)
- [Usernames](#usernames)
- [Bucket 2 (shared-space)](#bucket-2-shared-space)
- [Member join status (SPEC-073)](#member-join-status-spec-073)
- [Member roster for members (SPEC-075)](#member-roster-for-members-spec-075)
- [Dev-unauth path](#dev-unauth-path)
- [The username directory is built from S3, not Cognito (SPEC-146)](#the-username-directory-is-built-from-s3-not-cognito-spec-146)
- [Every authenticated user can read the username directory (SPEC-146)](#every-authenticated-user-can-read-the-username-directory-spec-146)
- [No shared-space directory is published; suggestions come from your own cache (SPEC-158)](#no-shared-space-directory-is-published-suggestions-come-from-your-own-cache-spec-158)
- [A feature flag is presentation, never authorization — and it lives beside the username directory (SPEC-162)](#a-feature-flag-is-presentation-never-authorization--and-it-lives-beside-the-username-directory-spec-162)
- [Gating is by REGISTRY, not per-component opt-in (SPEC-163)](#gating-is-by-registry-not-per-component-opt-in-spec-163)
- [The roster contradicted the connections list because a fan-out list was missing one verb](#the-roster-contradicted-the-connections-list-because-a-fan-out-list-was-missing-one-verb)
- [A verification principal is read-only, or it is a back door](#a-verification-principal-is-read-only-or-it-is-a-back-door)
- [The provider block is the API's verifier configuration, and it is server-side (SPEC-192)](#the-provider-block-is-the-apis-verifier-configuration-and-it-is-server-side-spec-192)
- [Authorization lives in the router, not in an API Gateway authorizer (SPEC-193)](#authorization-lives-in-the-router-not-in-an-api-gateway-authorizer-spec-193)
- [The API is a verifier, not an OIDC client (SPEC-195)](#the-api-is-a-verifier-not-an-oidc-client-spec-195)
- [The API reads the same claims and assumes the same role with the same tag set (SPEC-196)](#the-api-reads-the-same-claims-and-assumes-the-same-role-with-the-same-tag-set-spec-196)
- [Two credential planes, declared per route, defaulting to the user plane (SPEC-196)](#two-credential-planes-declared-per-route-defaulting-to-the-user-plane-spec-196)
- [The credential cache is keyed on the whole tag set (SPEC-196)](#the-credential-cache-is-keyed-on-the-whole-tag-set-spec-196)
- [The error shape: a machine code, and operator text nobody renders (SPEC-197)](#the-error-shape-a-machine-code-and-operator-text-nobody-renders-spec-197)
- [The contract is declared in Python and the TypeScript is generated (SPEC-197)](#the-contract-is-declared-in-python-and-the-typescript-is-generated-spec-197)
- [`apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)](#apirequest-retries-nothing-and-idempotency-is-declared-per-route-spec-197)
- [Cognito tokens are held per TAB, not per browser (2026-08-27)](#cognito-tokens-are-held-per-tab-not-per-browser-2026-08-27)

**Storage, and the fact S3 is not a filesystem**

- [File ops = filesystem UX](#file-ops--filesystem-ux)
- [A partial teardown never frees the space name (SPEC-151)](#a-partial-teardown-never-frees-the-space-name-spec-151)
- [An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)](#an-unreadable-settings-document-is-quarantined-never-deleted-and-never-overwritten-spec-159)
- [The file-send plane is its own, and its front door is bounded by a chain (SPEC-164)](#the-file-send-plane-is-its-own-and-its-front-door-is-bounded-by-a-chain-spec-164)
- [A received file lands in `shared_files/{sender}/`, and one function builds every key (SPEC-165)](#a-received-file-lands-in-shared_filessender-and-one-function-builds-every-key-spec-165)
- [The file-send exclusion rule is anchored at the space root, not the listing prefix (SPEC-165)](#the-file-send-exclusion-rule-is-anchored-at-the-space-root-not-the-listing-prefix-spec-165)
- [The expansion caps are sized by memory and makespan, and the obvious models miss both (SPEC-165)](#the-expansion-caps-are-sized-by-memory-and-makespan-and-the-obvious-models-miss-both-spec-165)
- [An expected refusal is a return value, and a conflict is per item NAME (SPEC-166)](#an-expected-refusal-is-a-return-value-and-a-conflict-is-per-item-name-spec-166)
- [The transfer caps are three, and each is measured against a different budget (SPEC-166)](#the-transfer-caps-are-three-and-each-is-measured-against-a-different-budget-spec-166)
- [One producer says every per-recipient outcome, and the link carries the recipient's own root (SPEC-167)](#one-producer-says-every-per-recipient-outcome-and-the-link-carries-the-recipients-own-root-spec-167)
- [A saved query is a FILE, and the folder holding it is ordinary except in one respect (SPEC-173)](#a-saved-query-is-a-file-and-the-folder-holding-it-is-ordinary-except-in-one-respect-spec-173)
- [Every `DO_NOT_DELETE.txt` is hidden by BASENAME, and the whole arc needs no IaC change (SPEC-173)](#every-do_not_deletetxt-is-hidden-by-basename-and-the-whole-arc-needs-no-iac-change-spec-173)
- [`saved_queries/` is gated on `query`, and the gate is not the refusal (SPEC-173)](#saved_queries-is-gated-on-query-and-the-gate-is-not-the-refusal-spec-173)
- [A save chooses its space, and one KEY rule decides what that replaces (SPEC-175)](#a-save-chooses-its-space-and-one-key-rule-decides-what-that-replaces-spec-175)
- [A file operation on more than one file belongs on a plane, and the boundary is the SELECTION (SPEC-187)](#a-file-operation-on-more-than-one-file-belongs-on-a-plane-and-the-boundary-is-the-selection-spec-187)
- [The file-ops lock's loser WAITS where the table-builder's is refused (SPEC-187)](#the-file-ops-locks-loser-waits-where-the-table-builders-is-refused-spec-187)
- [An item copied into itself is refused PER ITEM, where a containment breach fails the request (SPEC-187)](#an-item-copied-into-itself-is-refused-per-item-where-a-containment-breach-fails-the-request-spec-187)
- [The source deletion removes only CONFIRMED-COPIED keys, never a prefix listing (SPEC-187, diverging from SPEC-169)](#the-source-deletion-removes-only-confirmed-copied-keys-never-a-prefix-listing-spec-187-diverging-from-spec-169)
- [The collision unit is the derived destination KEY, and that is what preserves merging (SPEC-188)](#the-collision-unit-is-the-derived-destination-key-and-that-is-what-preserves-merging-spec-188)
- [A conflict is one item's outcome, and the list is created once and carried forward (SPEC-188)](#a-conflict-is-one-items-outcome-and-the-list-is-created-once-and-carried-forward-spec-188)
- [The commit gate is per ITEM, so the graph proves less than SPEC-169's did (SPEC-189)](#the-commit-gate-is-per-item-so-the-graph-proves-less-than-spec-169s-did-spec-189)
- [The source deletion: what it removes, and what it is conditional on (SPEC-189)](#the-source-deletion-what-it-removes-and-what-it-is-conditional-on-spec-189)

**Control planes — one pattern, and the traps are shared**

- [Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)](#everything-unbounded-on-the-state-travels-by-pointer--including-the-definition-spec-161-extending-spec-090160)
- [Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)](#every-control-plane-machine-that-can-run-for-hours-declares-a-timeoutseconds-spec-161)
- [Data-quality outcome notifications (SPEC-114)](#data-quality-outcome-notifications-spec-114)
- [Control-plane DLQ drain → user notification (SPEC-126)](#control-plane-dlq-drain--user-notification-spec-126)
- [Structured-logging pipe (SPEC-127→129)](#structured-logging-pipe-spec-127129)
- [Structured-logging narrative primitives & the one-door rule (SPEC-130/131)](#structured-logging-narrative-primitives--the-one-door-rule-spec-130131)
- [The field rule — what may be logged (SPEC-130)](#the-field-rule--what-may-be-logged-spec-130)
- [Per-plane instrumentation rules (SPEC-132→137)](#per-plane-instrumentation-rules-spec-132137)
- [No ASL state decodes an error Cause (PR #252, control-plane-wide)](#no-asl-state-decodes-an-error-cause-pr-252-control-plane-wide)
- [Notifications (SPEC-058→061)](#notifications-spec-058061)
- [Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)](#every-plane-notifies-on-a-pre-verb-failure-and-failure_reason-is-the-only-decoder-spec-152)
- [A layer gate must check the copy list, not the flag map (SPEC-153)](#a-layer-gate-must-check-the-copy-list-not-the-flag-map-spec-153)
- [The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)](#the-deliberate-twins-are-discharged-one-implementation-per-cross-plane-helper-spec-156)
- [The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)](#the-copy-is-a-top-level-distributed-map-and-attribution-is-a-verb-spec-160)
- [A post-identity failure needs its own seed, and the fleet guard cannot see it (SPEC-165)](#a-post-identity-failure-needs-its-own-seed-and-the-fleet-guard-cannot-see-it-spec-165)
- [The machine's ceiling cannot notify on its own, and this plane's timeout door needs a fallback (SPEC-166)](#the-machines-ceiling-cannot-notify-on-its-own-and-this-planes-timeout-door-needs-a-fallback-spec-166)
- [The lock protocol is `cpcommon`'s, extracted ahead of its second consumer (SPEC-187)](#the-lock-protocol-is-cpcommons-extracted-ahead-of-its-second-consumer-spec-187)
- [The engine's attribution vocabulary belongs to the CALLER, not to cpcommon (SPEC-189)](#the-engines-attribution-vocabulary-belongs-to-the-caller-not-to-cpcommon-spec-189)
- [Two budgets, and both were wrong before they were computed (SPEC-189)](#two-budgets-and-both-were-wrong-before-they-were-computed-spec-189)
- [One producer, after the release, reached from BOTH of ReleaseLock's edges (SPEC-191)](#one-producer-after-the-release-reached-from-both-of-releaselocks-edges-spec-191)
- [A notification payload is bounded by BYTES, and the binding case is the PLAIN one (SPEC-191)](#a-notification-payload-is-bounded-by-bytes-and-the-binding-case-is-the-plain-one-spec-191)
- [The run's ONE sentence opens neutrally, because its residue is not all failure (SPEC-191)](#the-runs-one-sentence-opens-neutrally-because-its-residue-is-not-all-failure-spec-191)
- [A resolved space carries its own IDENTITY, not only its location (SPEC-191)](#a-resolved-space-carries-its-own-identity-not-only-its-location-spec-191)
- [`requestId` rides on every row, including a clean run's and a failed run's (SPEC-191)](#requestid-rides-on-every-row-including-a-clean-runs-and-a-failed-runs-spec-191)
- [The outcome link: destination, source, or the common folder of the items' PARENTS (SPEC-191)](#the-outcome-link-destination-source-or-the-common-folder-of-the-items-parents-spec-191)
- [The outcome wording reuses the failure bodies and is deliberately NOT a resolver (SPEC-191)](#the-outcome-wording-reuses-the-failure-bodies-and-is-deliberately-not-a-resolver-spec-191)
- [A pre-existing notifications spoofing gap, recorded and not fixed here (SPEC-191)](#a-pre-existing-notifications-spoofing-gap-recorded-and-not-fixed-here-spec-191)
- [The notifications `create` boundary is a runtime check, because IAM cannot express it (SPEC-206)](#the-notifications-create-boundary-is-a-runtime-check-because-iam-cannot-express-it-spec-206)

**Analytics, the catalog, and two SQL dialects**

- [Analytics (SPEC-032→036)](#analytics-spec-032036)
- [Query workspace has NO active database (SPEC-077)](#query-workspace-has-no-active-database-spec-077)
- [Multi-statement scripts (SPEC-078)](#multi-statement-scripts-spec-078)
- [Table Builder (SPEC-066→072)](#table-builder-spec-066072)
- [Table Share (SPEC-088→094)](#table-share-spec-088094)
- [Data-quality report view (SPEC-113)](#data-quality-report-view-spec-113)
- [Data-quality runs index + dashboard (SPEC-123)](#data-quality-runs-index--dashboard-spec-123)
- [Control-plane table creation = TBAC (SPEC-070/111 correction)](#control-plane-table-creation--tbac-spec-070111-correction)
- [Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)](#refresh-eligibility-turns-on-shape-never-on-a-marker-spec-143)
- [Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)](#removing-a-column-requires-an-explicit-opt-in-and-the-refusal-is-the-warning-spec-144)
- [The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)](#the-refresh-apply-replaces-the-definition-in-place-spec-149-supersedes-spec-144s-apply)
- [A per-table lock serializes refresh, because the catalog cannot (SPEC-157)](#a-per-table-lock-serializes-refresh-because-the-catalog-cannot-spec-157)
- [Every DDL literal goes through `literal()` (SPEC-151)](#every-ddl-literal-goes-through-literal-spec-151)
- [A generalized signature is the whole point of the second extraction, and one moved constant must not be renamed (SPEC-177)](#a-generalized-signature-is-the-whole-point-of-the-second-extraction-and-one-moved-constant-must-not-be-renamed-spec-177)
- [The renderer's signature is the rule, and the browser's first SQL value interpolation is two gates wide (SPEC-178)](#the-renderers-signature-is-the-rule-and-the-browsers-first-sql-value-interpolation-is-two-gates-wide-spec-178)
- [A space maps to ONE database, so the picker has no database step — and a deep link resolves without asking (SPEC-179)](#a-space-maps-to-one-database-so-the-picker-has-no-database-step--and-a-deep-link-resolves-without-asking-spec-179)
- [Calc computes what only the browser has, grouping computes what only Athena can, and the percentage says which page it is of (SPEC-182)](#calc-computes-what-only-the-browser-has-grouping-computes-what-only-athena-can-and-the-percentage-says-which-page-it-is-of-spec-182)
- [A saved exploration follows the flag that owns the STORE, not the one that owns the screen (SPEC-183)](#a-saved-exploration-follows-the-flag-that-owns-the-store-not-the-one-that-owns-the-screen-spec-183)
- [Results are read only at SUCCEEDED, and `isPending` is not a substitute (2026-08-16)](#results-are-read-only-at-succeeded-and-ispending-is-not-a-substitute-2026-08-16)
- [A stale result must not be served at all, so the eviction reaches the tab in front of you (2026-08-19)](#a-stale-result-must-not-be-served-at-all-so-the-eviction-reaches-the-tab-in-front-of-you-2026-08-19)
- [A column name is user data, and the renderer must be safe without it being validated (2026-08-19)](#a-column-name-is-user-data-and-the-renderer-must-be-safe-without-it-being-validated-2026-08-19)
- [Athena's two dialects need two escapers in the browser, and the second was missing (2026-08-19)](#athenas-two-dialects-need-two-escapers-in-the-browser-and-the-second-was-missing-2026-08-19)
- [A table's LOCATION is read recursively, so the space root is not a data folder (2026-08-19)](#a-tables-location-is-read-recursively-so-the-space-root-is-not-a-data-folder-2026-08-19)

**Archive and restore — the only place a mistake is unrecoverable**

- [The archive vault, and the four choices that shape the whole arc (SPEC-168)](#the-archive-vault-and-the-four-choices-that-shape-the-whole-arc-spec-168)
- [`GLACIER`, and why the other two were rejected](#glacier-and-why-the-other-two-were-rejected)
- [Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose](#retention-is-a-ceiling-not-a-worm-floor--and-the-lifecycle-rule-is-unfiltered-on-purpose)
- [The bucket the browser has no relationship with](#the-bucket-the-browser-has-no-relationship-with)
- [The key layout: the archived key carries its own origin, partitioned by space kind](#the-key-layout-the-archived-key-carries-its-own-origin-partitioned-by-space-kind)
- [One plane, one `mode` branch, and no grant this spec did not need](#one-plane-one-mode-branch-and-no-grant-this-spec-did-not-need)
- [Two things the fleet's own guards caught while this was being written](#two-things-the-fleets-own-guards-caught-while-this-was-being-written)
- [The commit gate, and the four choices that make a deletion safe (SPEC-169)](#the-commit-gate-and-the-four-choices-that-make-a-deletion-safe-spec-169)
- [The source is deleted only when EVERY object is confirmed copied](#the-source-is-deleted-only-when-every-object-is-confirmed-copied)
- [The rollback deletes what is THERE, not what it was told about](#the-rollback-deletes-what-is-there-not-what-it-was-told-about)
- [The delete grant is the one this role could not inherit](#the-delete-grant-is-the-one-this-role-could-not-inherit)
- [The request id is browser-supplied, so a reused one is refused twice over](#the-request-id-is-browser-supplied-so-a-reused-one-is-refused-twice-over)
- [An object this plane could copy but could not delete is refused, not archived](#an-object-this-plane-could-copy-but-could-not-delete-is-refused-not-archived)
- [The artifacts are ordered most durable to least, and the receipt's failure is terminal](#the-artifacts-are-ordered-most-durable-to-least-and-the-receipts-failure-is-terminal)
- [Three caps, and the one the spec does not name](#three-caps-and-the-one-the-spec-does-not-name)
- [The ceiling ships with its rule, again](#the-ceiling-ships-with-its-rule-again)
- [The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops](#the-receipts-paths-name-the-roots-and-the-expansion-keeps-what-every-other-plane-drops)
- [The restore guard, and the four choices that make it safe to start a bill (SPEC-170)](#the-restore-guard-and-the-four-choices-that-make-it-safe-to-start-a-bill-spec-170)
- [The guard is absolute, and it runs before the retrieval](#the-guard-is-absolute-and-it-runs-before-the-retrieval)
- [The bound is botocore's connection pool, not the thread count](#the-bound-is-botocores-connection-pool-not-the-thread-count)
- [The lookup reads the KEYS; the record is a cross-check it can do without](#the-lookup-reads-the-keys-the-record-is-a-cross-check-it-can-do-without)
- [The space comes from the request, and the two ids are different things](#the-space-comes-from-the-request-and-the-two-ids-are-different-things)
- [One front door, one `Validated` Pass, and two message prefixes](#one-front-door-one-validated-pass-and-two-message-prefixes)
- [This spec adds no IAM, and that is asserted rather than assumed](#this-spec-adds-no-iam-and-that-is-asserted-rather-than-assumed)
- [Review closed two holes, and one of them was a silent, unrecoverable deletion](#review-closed-two-holes-and-one-of-them-was-a-silent-unrecoverable-deletion)
- [Retrieval as the point of no return, and the four asymmetries the restore introduces (SPEC-171)](#retrieval-as-the-point-of-no-return-and-the-four-asymmetries-the-restore-introduces-spec-171)
- [The destination guard runs TWICE, because this spec turned a guarantee into a promise](#the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee-into-a-promise)
- [The retrieval Map tolerates NO failure, and the copy tolerates every one](#the-retrieval-map-tolerates-no-failure-and-the-copy-tolerates-every-one)
- [Completion is the `Restore` header, and an ABSENT header is a failure](#completion-is-the-restore-header-and-an-absent-header-is-a-failure)
- [The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane](#the-retrieval-budget-has-deliberate-headroom-and-the-ceiling-moved-for-the-whole-plane)
- [The restore's gate is the commit gate's MIRROR IMAGE, not its twin](#the-restores-gate-is-the-commit-gates-mirror-image-not-its-twin)
- [The receipt is rewritten, never re-rendered, and the counts come from the run](#the-receipt-is-rewritten-never-re-rendered-and-the-counts-come-from-the-run)
- [The metadata fix: a latent bug on all three planes, surfaced by a round trip](#the-metadata-fix-a-latent-bug-on-all-three-planes-surfaced-by-a-round-trip)
- [The archive surface: a confirm that is not a confirm, folder names as identity, and the first prefix write gate (SPEC-172)](#the-archive-surface-a-confirm-that-is-not-a-confirm-folder-names-as-identity-and-the-first-prefix-write-gate-spec-172)
- [The one dialog in this app where the confirm is not the default, and Enter does nothing](#the-one-dialog-in-this-app-where-the-confirm-is-not-the-default-and-enter-does-nothing)
- [The folder names ARE the archive ids, so the folder must stay visible](#the-folder-names-are-the-archive-ids-so-the-folder-must-stay-visible)
- [The write gate mirrors each bucket's own Deny, and averaging them gets one case wrong](#the-write-gate-mirrors-each-buckets-own-deny-and-averaging-them-gets-one-case-wrong)
- [Only three outcomes needed a producer, and one of them had to be invented](#only-three-outcomes-needed-a-producer-and-one-of-them-had-to-be-invented)
- [The restore's FIFO group id hashes the archive ROOT, not the bucket and the root](#the-restores-fifo-group-id-hashes-the-archive-root-not-the-bucket-and-the-root)

**The browser**

- [State](#state)
- [Responsive (SPEC-095)](#responsive-spec-095)
- [Help & guides (SPEC-074)](#help--guides-spec-074)
- [User-facing error messaging (SPEC-106)](#user-facing-error-messaging-spec-106)
- [`components/` may not import from `features/` (SPEC-155)](#components-may-not-import-from-features-spec-155)
- [Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)](#dialog-enter-to-submit-fires-from-one-field-never-from-the-form-spec-155)
- [Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)](#escape-dispatches-by-tree-depth-not-per-component-opt-out-spec-155-supersedes-closeonescape)
- [The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)](#the-byte-formatters-share-a-unit-ceiling-and-it-goes-to-tb-spec-155-fr-007)
- [A display page is not a listing page, and the space selector is gated (SPEC-174)](#a-display-page-is-not-a-listing-page-and-the-space-selector-is-gated-spec-174)
- [The shared layer is extracted before its second consumer exists, and the rule that guards it had to be verified by violating it (SPEC-176)](#the-shared-layer-is-extracted-before-its-second-consumer-exists-and-the-rule-that-guards-it-had-to-be-verified-by-violating-it-spec-176)
- [The key namespace moves with the module, and a prefix is not cosmetic](#the-key-namespace-moves-with-the-module-and-a-prefix-is-not-cosmetic)
- [The producer decides where a type lives, not the consumer](#the-producer-decides-where-a-type-lives-not-the-consumer)
- [`no-restricted-imports` matches the SOURCE STRING, so a sibling rule needs relative patterns](#no-restricted-imports-matches-the-source-string-so-a-sibling-rule-needs-relative-patterns)
- [What did not move, and why](#what-did-not-move-and-why)
- [Geometry is keyed by NAME, NULL is kept apart from empty, and a page nobody watched is not "no rows" (SPEC-180)](#geometry-is-keyed-by-name-null-is-kept-apart-from-empty-and-a-page-nobody-watched-is-not-no-rows-spec-180)
- [One `apply` per gesture, a numeric refusal at the INPUT, and a failure that keeps the rows (SPEC-181)](#one-apply-per-gesture-a-numeric-refusal-at-the-input-and-a-failure-that-keeps-the-rows-spec-181)
- [A palette is measured, not chosen; a link's encoding depends on where the value lands (SPEC-184)](#a-palette-is-measured-not-chosen-a-links-encoding-depends-on-where-the-value-lands-spec-184)
- [The palette is a bounded token set, because the contrast criterion is otherwise unassertable](#the-palette-is-a-bounded-token-set-because-the-contrast-criterion-is-otherwise-unassertable)
- [The URL transformer's encoding is position-dependent, and both simple rules are wrong](#the-url-transformers-encoding-is-position-dependent-and-both-simple-rules-are-wrong)
- [A rule's `scope` is a field the spec's model did not have](#a-rules-scope-is-a-field-the-specs-model-did-not-have)
- [The raw value drives everything, and the transform lives at the cell](#the-raw-value-drives-everything-and-the-transform-lives-at-the-cell)
- [A link in a grid is not a tab stop, and the app must not manufacture backtracking](#a-link-in-a-grid-is-not-a-tab-stop-and-the-app-must-not-manufacture-backtracking)
- [A hidden column is still part of the row](#a-hidden-column-is-still-part-of-the-row)
- [A stored formatting block is discarded WHOLE](#a-stored-formatting-block-is-discarded-whole)
- [Copy is the selection-shaped tool and export is the result-shaped one, and reusing the save path meant moving it (SPEC-185)](#copy-is-the-selection-shaped-tool-and-export-is-the-result-shaped-one-and-reusing-the-save-path-meant-moving-it-spec-185)
- [The two ways out divide on the line the whole arc divides on](#the-two-ways-out-divide-on-the-line-the-whole-arc-divides-on)
- [A NULL and an empty string stay apart in all six formats, and quoting is what disambiguates the WORD](#a-null-and-an-empty-string-stay-apart-in-all-six-formats-and-quoting-is-what-disambiguates-the-word)
- [A discontiguous selection copies as a rectangle, and a SQL INSERT names a placeholder](#a-discontiguous-selection-copies-as-a-rectangle-and-a-sql-insert-names-a-placeholder)
- [Reuse required a MOVE, and the move closed a live flag defect](#reuse-required-a-move-and-the-move-closed-a-live-flag-defect)
- [Every guide row before this spec lived in the section the Help page opens on](#every-guide-row-before-this-spec-lived-in-the-section-the-help-page-opens-on)
- [A default that an empty string can defeat is not a default (SPEC-186)](#a-default-that-an-empty-string-can-defeat-is-not-a-default-spec-186)
- [`??` does not fall back on `''`, and a helper returning `''` is a trap for every consumer](#-does-not-fall-back-on--and-a-helper-returning--is-a-trap-for-every-consumer)
- [A refusal announced after the confirm is worse than no affordance at all](#a-refusal-announced-after-the-confirm-is-worse-than-no-affordance-at-all)
- [jsdom has no layout, so a containment property must be arithmetic](#jsdom-has-no-layout-so-a-containment-property-must-be-arithmetic)
- [A procedure that cannot produce its claimed outcome invites a false bug report](#a-procedure-that-cannot-produce-its-claimed-outcome-invites-a-false-bug-report)
- [A persistent in-flight surface is NEW scope, with no precedent here (SPEC-190)](#a-persistent-in-flight-surface-is-new-scope-with-no-precedent-here-spec-190)
- [There is no progress percentage, and there cannot be one (SPEC-190)](#there-is-no-progress-percentage-and-there-cannot-be-one-spec-190)
- [The kill switch is a flag key, and it is the sixth (SPEC-190)](#the-kill-switch-is-a-flag-key-and-it-is-the-sixth-spec-190)

**Infrastructure, IAM and delivery**

- [IaC](#iac)
- [Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)](#deploy-role-refresh-deadlock-has-an-in-repo-lever-skip_refresh)
- [Response headers / CSP (SPEC-140)](#response-headers--csp-spec-140)
- [Static-asset caching = three prefix-scoped sync passes (SPEC-141)](#static-asset-caching--three-prefix-scoped-sync-passes-spec-141)
- [A build stamp belongs to the artefact; an environment name belongs to the environment](#a-build-stamp-belongs-to-the-artefact-an-environment-name-belongs-to-the-environment)
- [Consolidation is worth doing against a SWEEP, not against a list](#consolidation-is-worth-doing-against-a-sweep-not-against-a-list)
- [Configuration is a runtime document, and a production build has no fallback (SPEC-192)](#configuration-is-a-runtime-document-and-a-production-build-has-no-fallback-spec-192)
- [There is no NAT gateway, and the endpoints are the whole outbound story (SPEC-193)](#there-is-no-nat-gateway-and-the-endpoints-are-the-whole-outbound-story-spec-193)
- [The API function is not in the VPC (SPEC-193)](#the-api-function-is-not-in-the-vpc-spec-193)
- [The image tag is the commit sha, and `:latest` does not exist (SPEC-193)](#the-image-tag-is-the-commit-sha-and-latest-does-not-exist-spec-193)
- [The origins are admitted additively, and narrowed only at the cutover (SPEC-193)](#the-origins-are-admitted-additively-and-narrowed-only-at-the-cutover-spec-193)
- [A Fargate task volume cannot give a non-root container a writable path (SPEC-193)](#a-fargate-task-volume-cannot-give-a-non-root-container-a-writable-path-spec-193)
- [The nginx configuration reproduces CloudFront's jobs, and three are divergences (SPEC-194)](#the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are-divergences-spec-194)
- [The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)](#the-image-is-the-file-set-which-retires-a-reconciliation-pass-and-an-orphan-class-spec-194)
- [`connect-src` comes from the task definition; every other CSP directive is a property of the bundle (SPEC-194)](#connect-src-comes-from-the-task-definition-every-other-csp-directive-is-a-property-of-the-bundle-spec-194)

**Gates, scanners and tests**

- [Security scanning (SPEC-138)](#security-scanning-spec-138)
- [IAM policy scanning = the rendered plan, not the templates (SPEC-139)](#iam-policy-scanning--the-rendered-plan-not-the-templates-spec-139)
- [A scanner gate blocks on a narrowed count, never a total (2026-08-09, completes SPEC-138)](#a-scanner-gate-blocks-on-a-narrowed-count-never-a-total-2026-08-09-completes-spec-138)
- [Compiler and coverage defaults are declared, never inherited (SPEC-150)](#compiler-and-coverage-defaults-are-declared-never-inherited-spec-150)
- [`ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)](#accepted_-tripwires-what-the-project-knows-it-has-not-verified-spec-153)

## Identity, access and the name that ties them together

### Auth

Cognito User Pool → Identity Pool (ABAC) stamps the `username` principal tag from the verified token claim **server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)

### Hosted UI = Managed Login v2

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.

### No backend

Browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).

### Usernames

Usernames are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.

### Bucket 2 (shared-space)

User-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`) sharing a **`shared-space-common` Lambda layer** — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). The six Lambdas + the Step Function keep **one shared `orchestrator` role** (per-verb roles were descoped — user decision, SPEC-062 FR-005); the layer is CI-built/published (deploy-lambdas) with TF `ignore_changes=[layers]`. **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `lambdas/info/planes/shared-spaces.md`; Lambda rules: `lambdas/info/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.

### Member join status (SPEC-073)

The owner projection carries a per-member `pending`/`active` chip. Membership stays `members: string[]` (source of truth in the registry); join status is a separate `acknowledged: string[]` list — a legacy record without it reads as all-active (back-compat). A **seventh verb `acknowledge-membership`** (member-only, idempotent, same shared `orchestrator` role) flips pending→active; the browser enqueues it once/session when a member resolves a shared space (`useAcknowledgeMembership` from `FilesPage`). Display + bookkeeping only — access is still granted at add time.

### Member roster for members (SPEC-075)

SPEC-053's member-privacy stance is **reversed** — every member sees a **read-only** roster (owner tagged + first, same `Member[]` join-status projection the owner sees), via "View members" on their Connections card. `cache.write_roster_to_all` fans the roster out to the owner + every member on add/remove/leave (best-effort per member, CAS-safe); member entries now carry `members` too. No management power for non-owners; no new IAM (orchestrator already writes every user's cache). Legacy member entries backfill on the next membership change.

### Dev-unauth path

`VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

### The username directory is built from S3, not Cognito (SPEC-146)

The daily builder enumerates the user-space bucket's **top-level common prefixes**. It makes **no
Cognito call**, and a test asserts the module never names `cognito` in any import, attribute or call.

**The reasoning inverts the obvious answer, which is why it is written down.** *Today* Cognito is the
complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by
`ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate no-backend decision), so a
confirmed user who has never opened the file browser has no prefix. On that reading Cognito wins.

*After the client transition it reverses.* `transition_plan.md` §2 item 7 settles that **sign-in
provisions nothing** — the sync pre-creates every existing user's space and database, the client's own
automation creates them for new users, and `ensurePrefixMarker` is deleted outright (§6.3). At the same
time federated login makes `cognito:username` a **synthetic `identitycenter_<subject>` value** rather
than the catalog-safe username (§6.1), and users appear in the User Pool only after their first
sign-in. So S3 becomes complete and Cognito becomes both incomplete **and wrong-keyed**.

Choosing the source that is right on the far side of a migration already in flight beats the one that
is right today, particularly when today's gap is bounded: pre-production, no production users, and the
failure mode is a name missing from a suggestion list that still accepts free text.

**Do NOT add Cognito as a union "to be safe."** A second source with different completeness properties
is a second thing to reason about every time the directory looks wrong.

**The directory is advisory and is never an authorization input.** No control plane reads it; every
existence check stays `admin_get_user` against the User Pool (`shared-space-common/membership.py`,
`tscommon/cognito.py`), and an unknown name is still reported to the user as a notification. A
tripwire test fails if any Lambda outside `user-directory-build` references the path, the prefix or
the key constants.

Full account: `docs/spec-delivery/SPEC-146-username-directory-daily-builder.md`.

### Every authenticated user can read the username directory (SPEC-146)

`_directory/usernames.json` is readable by **every authenticated portal user**, through one
`s3:GetObject` statement on the portal role. That disclosure is **intended and accepted**, not
incidental, and it is recorded here rather than left implicit because the object is a single file
listing everyone in the organisation.

What makes it acceptable is that the set is already disclosed several ways: a username **is** the S3
prefix, the `username` principal tag and the Glue database name (SPEC-033); it is visible on every
shared-space roster to every member (SPEC-075); and a prefix-search feature discloses the set by
construction — a typeahead that would not confirm whether `bob` exists is not a typeahead. The
document holds **usernames and nothing else**: no display names, no email addresses. An email is not
metadata under this repo's field rule and has no place in a document every user can read.

**What was deliberately NOT granted:** no `ListBucket` widening (the portal role's grant stays
conditioned on the caller's own prefix, so `_directory/` is invisible to the file browser and the file
browser needed no change), no `PutObject`, no `DeleteObject`. The user reads; the daily builder is the
only writer.

**The builder's own `s3:ListBucket` is unconditioned**, and what that grants is stated rather than
minimised: `Delimiter="/"` is a property of the *code*, not the grant, so the role can enumerate every
object key under every user's prefix. Accepted because it holds **no `s3:GetObject` anywhere** (it can
list names and read nothing), because key names are metadata under the field rule, and because it is a
Lambda role with no user-assumable path. The obvious tightening — an `s3:prefix` condition on the
empty string — is **rejected, not overlooked**: whether botocore serialises an empty `Prefix` into a
condition key at all is an implementation detail, and if it does not the grant fails closed and the
builder's only listing call breaks. `simulate-custom-policy` would agree with whatever context key the
author supplied, so it would confirm the assumption rather than test it. If the grant ever becomes
uncomfortable, the sound fix is a separate bucket, not an unverifiable condition key.

### No shared-space directory is published; suggestions come from your own cache (SPEC-158)

`TableShareDialog`'s space entry suggests only the shared spaces the signed-in user belongs to,
read from the connections cache `useConnections` already fetches. **A complete list of every space
in the organisation would be strictly more useful, and it was declined.**

Strictly more useful because sharing a table to a space does **not** require membership —
`test_recipient_space_membership_not_required` pins that any active space is a valid target — so the
suggestions cover less than the field accepts, on purpose. The cost of closing that gap is a
disclosure with **no existing equivalent**: today a non-member learns a space exists only by
colliding with its name at create time, and space names are user-chosen and often descriptive
(`acme_merger`, `q4_layoffs`). The username directory is not a precedent — a username is already the
S3 prefix, the principal tag and the Glue database name (see the entry above); a space name a user
does not belong to is disclosed nowhere. The trade was put to the user on 2026-08-05 and **declined
in favour of suggesting only what the user can already see.**

**Do NOT add a space directory "for symmetry with SPEC-146."** The absence is the decision. What
holds the line in the UI is that a space the user does not belong to **stays typeable and still
commits**, with a note that says it may exist and simply not be one of yours — worded that way
because this note is the one place a user could be misled into thinking the target was invalid.

Two consequences worth carrying:

- **The suggestion source is a prop, not a hook call** (`SuggestionSource = {status, search}`).
  `UsernameCombobox` reaching for `useUserDirectory` itself was the right reading with one source
  and the wrong one with two; a near-duplicate component would have been the alternative. A second
  source is the trigger to revisit that kind of deviation, not to fork.
- **A second source costs no request.** The space list is a query the app already makes for the
  Connections page and the Query rail, and the ranking is SPEC-147's `buildIndex`/`search`, which
  were never username-specific. No Lambda, no published document, no IAM, no env var, no new AWS
  call — a test asserts the space path issues none.

### A feature flag is presentation, never authorization — and it lives beside the username directory (SPEC-162)

**The document is `_config/feature-flags.json` in the USER-SPACE bucket**, published by
`.github/workflows/deploy-config.yml` from `config/feature-flags.json` in git. Four flags — `files`,
`query`, `sharedWorkspaces`, `dataQuality` — a total `defaults` block and per-environment partial
overrides, resolved in the browser against `VITE_ENVIRONMENT`.

**A FLAG HIDES A SURFACE AND REVOKES NOTHING.** Turning Query off hides the tab and its entry points;
the portal role's Athena, Glue and S3 grants are byte-identical either way. This is SPEC-146's
advisory rule for the username directory applied to a second document, for the same reason: the
moment someone treats an advisory document as a boundary, it becomes one, badly. The fence is not a
convention — `featureFlags.service.test.ts` enumerates every `*.service.ts` under `features/` and
every module under `lib/` and fails if one imports the flags module. It was verified against a
deliberate violation rather than trusted; the sweep named the offending file. The realistic failure
it forbids is not exotic: `if (flags.query) return` inside a service reads like a guard and is a
client-side access control, which is no control at all.

**The document was specced into the ADMIN bucket first and moved before any code was written.** That
would have given the portal role its first grant on a bucket admin-only since SPEC-032 — and the
grant would not have worked. The admin bucket carries an explicit "never read by the browser" comment
in place of a CORS configuration, and its host is absent from the enforcing CSP `connect-src`. Two
infra gates on the exact surface SPEC-140 records breaking fresh sign-in for a day, for nothing
`_config/` beside `_directory/` does not already have. **The generalisation is the useful part: for a
browser-read advisory document, the bucket that already serves one is the cheap answer** — and it is
`_config/*`, one `s3:GetObject`, no `ListBucket` widening, no write, no deploy-role change, no CORS,
CSP or bucket-policy change. This is now the precedent for a third such document.

**"It already works" is a claim about three files this spec does not touch, so all three are
asserted.** `lambdas/test_feature_flags_config.py` checks the user-space CORS rule still allows `GET`
from the app origin, that the bucket host is still in `csp_connect_src`, and that the portal role is
still on the bucket policy's hand-maintained principal allowlist — plus the deploy role's existing
`s3:*` on `${user_space_bucket_arn}/*`, which is why the publish adds no IAM. If one of these ever
fails it is a **finding to raise, not a licence to widen infra inside this spec**.

**AN UNUSABLE DOCUMENT FALLS BACK TO ALL-ON, AND THE FALLBACK IS SILENT.** Missing, unreadable,
unparseable or a version this build has no reader for: the compiled-in defaults take over and the
hook reports `'fallback'`. No banner, no toast — the user is not the audience for that failure.
Failing closed was the alternative and is worse: one S3 blip would strip the app to Files for
everyone. **The accepted cost is stated rather than hidden: during an outage a deliberate "off" does
not take effect.**

**That silence is exactly why the read had to be made observable.** Every default is `true`, so a
permanently-blocked fetch renders *identically* to a healthy environment — no user would report it
and no screenshot would show it. Hence FR-009: a dev-only `console.debug` naming `ready` vs
`fallback` (stripped from production, as `warnIfMisconfigured` is), and a live check whose pass
condition is a **200 in the network panel**, not an app that looks right.

**Two tolerances, deliberately different.** A wrong VERSION or top-level SHAPE is refused whole —
this build has no reader for it, and guessing at an unknown shape is how a flag comes to mean
something nobody wrote. A single malformed VALUE inside an otherwise-fine document falls back **for
that key only**; one bad line must not discard three good ones. The resolver walks the compiled-in
KEY LIST rather than the document's keys, which is what guarantees all four are present and boolean
whatever the document said.

**The service is stricter than `getUserDirectory()`, and that divergence is the load-bearing part.**
There, absent and corrupt collapse into the empty state because "no suggestions" is an honest answer.
Here the equivalent answer is all-on, which is indistinguishable from success — so the distinction
has to survive the return or `'fallback'` could never be reported. A MISSING object is a failure for
the same reason: it means the publish workflow has never reached this bucket, which is a deploy
defect and not a starting state.

**The validator reads the publish workflow's matrix rather than being handed a target list.** FR-002
requires the environment/target check in both directions — a block nobody publishes, and a target
that publishes nothing but defaults — and a list passed in by the same workflow that declares it
would compare a copy of the answer with itself. `deploy-config.yml`'s `environment_name:` entries are
the single declaration; a matrix that parses to nothing is a hard error, not an empty set, because
that is how this stops checking (a rename, not a deletion). The key is `environment_name` and not
`environment` precisely so a GitHub Actions job keyword cannot masquerade as an upload target.

**The publish addresses ONE EXACT KEY — no `sync`, no `--delete`.** `_directory/usernames.json` lives
one prefix over in the same bucket; a mis-scoped reconcile would break username typeahead everywhere
(SPEC-146/147) for a feature nothing user-facing depends on yet. It is also a separate workflow from
`Deploy App` on purpose: flipping a flag must not be a rebuild, which is why the upload carries
`Cache-Control: no-cache`.

### Gating is by REGISTRY, not per-component opt-in (SPEC-163)

**`GATED_SURFACES` names every surface every flag hides — 26 rows, keyed by flag — and one test
walks it in both states.** Not a checklist and not a convention: a row carries the surface's
ACCESSIBLE NAME, and `gatedSurfaces.test.tsx` renders each twice (flag off, flag on) and asserts
by that name. A row it cannot make disappear fails; a row with no reach-recipe fails; a recipe
with no row fails; an empty registry, or a flag with zero surfaces, fails.

**THE TABS ARE THE EASY PART, AND THAT IS THE WHOLE ARGUMENT.** "Create table from this folder"
lives on a file-browser toolbar and is a *Query* feature. "Share table" lives in the Query rail
and pushes into *Shared Workspaces*. "Check quality" is a button on a file-browser selection. A
per-component pass finds three of those and ships the fourth visible — the failure mode
`process.md` records from log-forge's SPEC-033. Adding a fifth entry point is now a registry
edit rather than a discovery exercise.

**The reach-recipes live in the TEST, not in the registry.** The registry stays declarative and
reviewable by someone who has read no component; the driving (open this drawer, expand that
node, click that menu) is test business. A guard asserts the two sets are equal, so they cannot
drift.

**One sanctioned door, and it is now absolute.** `useFeature(key)` answers "is this on?";
`FeatureGate` wraps; `useFeatureSet()` serves the three consumers that genuinely cannot ask one
question — `Header` builds one predicate for two nav components, `FeatureRoute` must tell "off"
from "not known yet", `LandingPage` picks the first enabled destination. **A tripwire test fails
if any module outside `features/feature-flags/` so much as names `useFeatureFlags`.** The spec
asked that nothing else read it; enforcing it by reading the source is stronger than asking,
because the convention is exactly what an urgent change forgets. The failure it prevents is not
exotic: a consumer that forgets `'loading'` must read as OFF makes a tab flicker, or lets a page
fetch before the answer arrives.

**Hidden means REMOVED, never `hidden` and never disabled.** A visually-hidden control is still
in the accessibility tree, still focusable and still announced — so `display: none` would leave
a screen-reader user able to reach a feature the environment says is not there. `FeatureGate`
renders no wrapper element at all, and the Share-table kind toggle renders **no toggle** rather
than a single-option radio group, which is a control that asks a question with one answer and
implies the other option exists somewhere.

**A gated route keeps its path and swaps its ELEMENT.** It must still match, or a disabled
feature falls through to `*` and tells a user with a perfectly correct link that their URL is
wrong. `FeatureUnavailablePage` says "not available in this environment" — a property of the
deployment, not of them — names no reason and offers no appeal route, because a flag is
presentation and inventing one would imply a permission model that does not exist.

**`FeatureRoute` renders `LoadingState` while the flags resolve, and that is not a contradiction
of "render nothing while loading".** The rule is right for a tab and wrong for a whole viewport:
an empty frame reads as a broken page where an absent tab reads as a tab that was never there.
What actually matters is that **the page does not MOUNT** — every gated page fetches on mount,
and on `/data-quality/:space/:requestId` an optimistic render would make a disabled feature an
existence oracle for someone else's report (SPEC-113's rule, inherited).

**`components/` still imports no feature.** `PrimaryNav` and `AppNavDrawer` take an
`isPathEnabled` **predicate**, supplied by `Header` — the one place that knows both the auth
state and the flags. Required, never defaulted: a default would make an unwired caller ship every
tab while looking correct. Both nav surfaces get the SAME predicate, because a tab hidden in the
topbar and present in the mobile hamburger is a feature that is still one tap away.

**`?space=` with shared workspaces off is NOT READ, not resolved-and-refused.** `useFileSpace`
gained `ignoreSpaceParam`; routing it through the existing `fellBack` path would raise "That
shared space is no longer available", which is a false statement about a space that is fine and
that returns the moment the flag flips back. `useConnections` still resolves normally — a flag
may not touch a service (SPEC-162 FR-006).

**Shared databases in the Query schema rail joined the contract (a deliberate extension).**
Leaving `teamspace` browsable while the spaces list and `/connections` are gone reads as a bug
rather than a policy. **Filtered at the VIEW, never at the service:** `useConnections` still
fetches every space, and a saved query naming a hidden database still RUNS. Hiding a surface is
not revoking access, and the grants are untouched.

**A REACH-RECIPE THAT RE-IMPLEMENTS THE GATE PROVES NOTHING, and two of them did.** The rows for
the Files spaces rail and the Query rail's shared databases originally rendered test-local host
components carrying their own `useFeature(...) ? … : null`. Measured in review: deleting BOTH
real gates left all 1843 tests green. Recipes now render the real page, and the same mutation
fails exactly those two rows. The rule generalises — a recipe may drive the app but may never
restate the condition under test.

**The off-half must be asserted AFTER settling, never inside `waitFor`.** `useFeature` reports
`false` while the flags resolve, so a retry loop's first attempt lands at the one moment every
surface is legitimately absent — and an ungated surface that merely renders asynchronously
passes. Each recipe carries an `anchor` (something present regardless of the flag) and absence
is asserted once. The same review found the paired sloppiness: `Go to Dashboard` was matched by
`/^Go to /`, which also matches the "Go to Query" the page correctly renders with Files off.

**`useFeatureFlags` distinguishes THREE auth states, not two.** Still-resolving is `'loading'`;
**settled with no user is `'fallback'`**, because a session with no credentials genuinely has
the compiled-in defaults in force. Collapsing the two made the documented no-AWS local workflow
a permanent spinner behind every gated route — `FeatureRoute` never left its neutral state.
Going the other way (treating still-resolving as fallback) would show every gated surface and
take it away a tick later, which is the flicker FR-007 exists to prevent.

**Hiding a surface is not hiding a WRITE PATH, and the first pass missed that.** With shared
workspaces off, the spaces rail was gone but the move/copy destination picker still offered a
space selector and the data-quality start dialog still listed shared spaces — so a user could
still paste a file into `marketing_data`. Both are now filtered at the view and registered. A
row is "a way in", not "a button".

**Test-harness consequence, and it bit before it was understood.** Gating made every gated
surface wait on a fetch, so `renderWithProviders` now seeds the flags all-on by default
(`seedFeatureFlags`, opt-out) — the same answer production reaches when the document is
unreadable. **`setQueryDefaults` must run before `setQueryData`**: the test client uses
`gcTime: 0`, so an observer-less seed is evicted the instant it is written, and every gated
control that mounts LATER — inside a drawer the test has to click open — starts from a cold
pending query and reads as flagged off. It passed every first-paint assertion and failed only
behind a click.

### The roster contradicted the connections list because a fan-out list was missing one verb

For one membership, at one moment, the app stated two things: the connections row read
`livecheck_0814a | Member | Active`, and the roster one click away read `agriffith | Pending` under
*"A Pending member has been invited but hasn't signed in yet."* The reader of that sentence **was**
the member, and they **had** signed in.

Neither settled decision is wrong. SPEC-073's `acknowledge-membership` flips pending→active and
writes the **owner's** projection; SPEC-075's `cache.write_roster_to_all` fans out on
**add/remove/leave** — a list that does not include acknowledge. So every member's copy, including
the acknowledging member's own, stayed frozen at add time, and the roster is the **only**
member-facing view of who is in a space.

Closed on both sides. The verb now fans out, and **the fan-out cannot fail the run**: the registry
write is the consistency point and has already committed, so a raise would fail the execution, and
the retry would find the member already acknowledged, no-op, and never write the caches at all —
turning a recoverable stale roster into a permanent one. In the browser, `displayedMemberStatus`
renders the reader's own row `Active` regardless, and the explanatory sentence renders **only when a
row it describes is on screen**, which closes the window before the fan-out lands.

### A verification principal is read-only, or it is a back door

Two owed assertions were unmakeable by anyone. SPEC-170's is the load-bearing one — that a
`destination_occupied` refusal did **not** already initiate retrieval — and `dat-prod-archive`
explicit-denies the laptop IAM user, its execution role trusts `lambda.amazonaws.com` only, the
deploy role is GitHub-OIDC-only, and **no CloudTrail trails existed**. The script itself records
that a refusal which had already started retrieval "looks identical from the UI", so there was no
proxy, and being wrong costs 3–5 billed, uncancellable hours.

The answer is **audit-shaped, not a grant on the data path**: a trail recording the archive
bucket's object-level events (`RestoreObject` is a CloudTrail **data** event, which is why it never
appears in the console's Event history), and a role that reads the catalog back. What is
deliberately absent is the whole of its safety: no `SELECT`, no `DATA_LOCATION_ACCESS`, no
`lakeformation:GetDataAccess` (the credential vend for reading a table's *data*, easy to add "to
make `GetTable` work", which it is not needed for), no data-bucket ARN, no `Resource: "*"`, and no
`iam:PassRole` on the deploy side — nothing but a human may assume it. A test asserts each, and
asserts the role appears nowhere in `portal-role-permissions`.

**The role is trusted to NAMED principals and does not exist until one is named**, which the
plan scan is what forced. The first version delegated to the account root; `CKV_AWS_61` rejected it,
and accepting the finding would have violated the accept list's own rule — that list is for findings
with **no scopable alternative**, and naming the principal is one. `verification_principal_arns` is
empty by default. **The trail is unconditional**, because it needs no principal and is the half that
unblocks SPEC-170.

> **CORRECTED 2026-08-14 (#461): the ARNs travel as a repo variable, NOT a gitignored
> `terraform.tfvars`.** The original wording named tfvars, which implies a local apply — and no
> human identity in this account has one. The laptop IAM user is not on the data buckets' policy
> allowlists, so `tofu plan` reads `dat-prod-user-space` and `dat-prod-archive` as absent and
> proposes to destroy and recreate them: measured `25 to add, 3 to change, 13 to destroy`, both
> buckets in the replace set, before failing on `GetLFTag` for `portal-managed`. `modules/data/s3.tf`
> had already recorded this exact failure mode for the deploy role under SPEC-016 — the general
> lesson was written down and still did not reach the one variable a human was told to set by hand,
> which is the part worth carrying: **a config route that only an operator walks is not exercised by
> anything, so it is worth checking that the route exists before documenting it.**

**The trail's own status is part of the assertion.** A trail that is off returns an empty result,
which reads exactly like a `RestoreObject` that never happened — so the script confirms
`IsLogging: true` before reading an absence as evidence.

**No blanket write-Deny on the trail bucket**, and the omission is deliberate: the obvious one rests
on a condition key CloudTrail's own delivery must populate for its Allow to survive, and if it does
not, delivery fails and the record is silently empty. That is this spec's own failure mode with the
evidence rather than a scanner.

### The provider block is the API's verifier configuration, and it is server-side (SPEC-192)

`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM` — API Lambda environment
variables, provisioned by the infrastructure spec and consumed by the auth-boundary spec. **None of
it appears in the browser's document**, because the browser verifies nothing: it sends the ID token
Amplify already holds. The converse holds too — a verifier configured by reading the browser's
document has a client-supplied trust anchor.

**This is a VERIFIER, not an OIDC client.** No code exchange, no PKCE verifier, no client secret, no
redirect URI, no scope list: those belong to Amplify, in the browser, unchanged by this arc. Building
a client here is the shape of error the small field set exists to prevent.

**`OIDC_JWKS_URI` is a field, not a derivation of `OIDC_ISSUER`.** The well-known path is a
convention, not a guarantee, and hard-coding it makes the verifier provider-specific in the one place
that would fail closed and silently.

**The exclusion cuts ONE way only, and that is the whole subtlety.** A test intersects the document's
key set with the verifier's field names plus a case-insensitive substring rule over `oidc`, `issuer`,
`audience`, `jwks` and `secret`. It is guarded in **both** directions: a synthetic key set containing
`issuer` must be flagged (a checker that flags nothing passes the first case forever), and the four
Cognito values Amplify actually reads must **not** be. That third case can fail today. Adding
`clientId` to the forbidden set is the specific mistake — `cognitoUserPoolClientId` survives an
exact-match rule and dies under a substring one — and the visible result is not a failing test but a
Hosted UI round trip that never completes. `cognitoDomain` is likewise **not** a provider-block field:
Amplify POSTs the code exchange to it. The forbidden set is about *the API's trust anchors*, not about
the word Cognito.

Detail: `spec-delivery/SPEC-192`.

### Authorization lives in the router, not in an API Gateway authorizer (SPEC-193)

The API serves every path through one `$default` route and one integration. A per-route authorizer
would have to duplicate the route table before it could say anything at all — and, more decisively, it
would be a **second reader of the same token**, able to disagree with the router about the claim the
role assumption is scoped by, with no arbiter between them.

**SHIPPED (SPEC-195, 2026-08-27); the "nothing to authorize" reasoning below is past tense.** The
API resolves a principal before dispatch and refuses any undeclared route — an unidentified caller
gets 401, not 404, whatever path they ask for. The disposition is unchanged and now load-bearing:
the verifier is a module the router calls. The disposition
for `CKV_AWS_309` in `security-baseline.md` is the audit-trail wording, and it rests on the bearer
token — never on the session cookie the arc's re-scope removed.

Detail: `spec-delivery/SPEC-193`.

### The API is a verifier, not an OIDC client (SPEC-195)

**The API verifies a bearer token and performs no login flow.** No code exchange, no refresh token, no session, no cookie. Sign-in is untouched: the User Pool, Managed Login v2, Amplify in the tab and the Hosted UI round trip all stay exactly as they are. The browser already holds an ID token; from here it sends that token as an `Authorization` bearer and the API takes the username from the **verified claim**. That is the trust model the seven control planes have had since SPEC-011 — the token changed transport, from a queue message body to a header, and nothing else. An earlier draft of this spec built a backend-for-frontend with all three; that work is real and deferred, and a reader who saw it should read this entry as the correction.

**No ambient credential means no CSRF surface.** CSRF exists because a browser attaches cookies to cross-site requests automatically; a bearer header is attached only by script that can read the token, and cross-origin script cannot. A later spec introducing a cookie re-opens CSRF, `SameSite`, and the *two-origins-one-registrable-domain* constraint this design relaxes from a requirement to a preference. **CORS is still required.**

**Provider-agnosticism lives in five configuration fields** — issuer, audience, JWKS URI, username claim, required claims — and this is load-bearing rather than a convenience: `transition_plan.md` §3.3's baseline variant deletes Cognito outright, so a configuration-driven verifier is the difference between a config change and a rewrite of every auth path in the product. The JWKS URI is **explicit configuration, never derived from the issuer** in the verifier or in the API module; Cognito publishes under its issuer and Entra does not. The concatenation appears **once, at the composition root**, which already names Cognito three ways and is therefore already a site any swap edits — and no test pins the `/.well-known/` path, because pinning a fact about one provider would go red on a correct configuration for another.

**A key-retrieval fault is not an authentication failure**, and getting this wrong is user-visible. `PyJWKClientConnectionError` subclasses `PyJWKClientError`, so one broad handler folds a provider outage into "your token is bad" — a 401, which tells every user to sign in again for something no user can fix and brings a refresh storm with it. Worse, PyJWT raises that transport type for exactly two causes, so classifying by type alone left a provider answering a proxy page, a JSON array, an empty key set or failing TLS all arriving as ordinary verification failures. The classification is by **what failed**, not by exception type: a `kid` genuinely absent from a key set that *was* read is an auth failure; anything that stops the key set being read is a 5xx.

**The refusal surface is deliberately uninformative, and expiry is deliberately NOT distinguished.** Every authentication failure returns byte-identical bytes, because a body that varied per failure is a map of which check failed. Expiry is the one a builder is tempted to disclose, to let the browser skip a refresh — but the browser refreshes once and retries once on **any** 401, so a discriminator buys the client nothing and costs the oracle. The assertion that can fail is that the expired body is byte-identical to the no-token body.

**The JWKS refetch is bounded per container, and the cost is accepted.** An unknown `kid` makes `PyJWKClient` refresh the whole key set, so a stream of random `kid`s is an unauthenticated amplification against the provider from requests that will never be authorized. The bound is a **cooldown on the refetch**, not a negative cache keyed by `kid` — that design suggests itself and does not work, because it misses on every *distinct* unknown `kid`, which is exactly the traffic being bounded. The cost is bounded eventual consistency: for up to 60 seconds after a rotation this API refuses tokens signed with the new key. Cognito publishes both keys across a rotation and the window sits far inside any overlap, so no real rotation is expected to reach a user; the trade is a bounded refusal against an amplification vector, and refusal is the fail-closed direction.

**`error.stack` carries no credential, and the mechanism is PREVENTION rather than redaction (SPEC-195, extended by SPEC-196).** `log-foundry` attaches `traceback.format_exception` to every failed span. SPEC-130 examined that and **accepted** it *for file contents*, on the reasoning that `logs/` is admin-only and a stack is diagnostic metadata a failed run needs; that reasoning was never applied to a credential, and an ID token is a bearer credential for as long as it lives. `log-foundry` 0.6.0 exposes no way to turn the capture off — `max_stack_bytes` is a ceiling, not a control — so the answer is at the boundary. **What "at the boundary" means is worth being exact about, because the phrase reads like a redactor and is not one.** The exposure is not automatic: `format_exception` renders each frame's *source line*, not its locals, and the provider library's own messages carry no token material. The live route is this repo's own code putting a credential into text. So the mechanism is an AST sweep forbidding the event, the headers, a token — and, from SPEC-196, four session-material names — from appearing in an f-string, a `%`-format, a `.format()` call or a `raise` argument, paired with a sentinel test that drives a path **genuinely raising through the span** while holding a real assumed session, so the absence is asserted where a stack actually exists. **The residual is real and recorded**: a future route that interpolates a session value despite the sweep still reaches the log store. It is in `owed.md`, not implied to be closed. **The scrub's scope is credentials and nothing wider** — a scrub written against user-data-shaped strings would contradict the 2026-07-23 decision and redden its tripwire from a spec that never argued the case. If a later `log-foundry` gains an opt-out, revisit the decision; do not delete the sweep.

### The API reads the same claims and assumes the same role with the same tag set (SPEC-196)

**The equivalence is not an analogy — it is the same computation over the same input.** `identity-pool.tf` declares which claim feeds which tag: `username` from `cognito:username`, `shared_space_k` from `custom:shared_space_k`, merged into one map because there is only one per (pool, provider). AWS applies that map to the ID token the browser presents. The API is handed **that same token**, verified against the provider's JWKS on every request, and applies **the same map**. Same token, same claims, same tag names, **the same role** — which is why nothing downstream can tell the two credential paths apart, and why **not one IAM policy, bucket policy or Lake Formation grant is rewritten**. A policy sees a session tag, not who stamped it.

**The claim names are the only thing copied from the Identity Pool, and copying them is what makes the preservation provable.** Sourcing the membership tags from the shared-space registry instead would be defensible in isolation and would **break the equivalence**, turning a provable preservation into an argument. What else would break it, precisely: taking a tag value from a header, a query parameter, a body field, an unverified JWT, or a username re-derived from a path segment — and any route that accepts a username or space name and uses it to *select* credentials rather than to *scope* a call made with the caller's own.

**The tag set is the WHOLE tag set, and stamping only `username` fails silently.** Omit the ten slot tags and personal S3, personal Glue, notifications and the file browser all keep working; only shared spaces refuse — for which the app already has a "Refresh access" recovery built for a documented propagation delay, so a missing tag *presents as that delay*. **An unoccupied slot contributes NO tag**, never one with an empty value: an empty value makes a shared-space ARN resolve to the bucket followed by a bare slash, which is a live grant on every key beginning with one, and S3 permits such a key.

**The role is REUSED rather than minted, and that is the single strongest reason.** The user-space bucket policy Denies every principal whose `aws:PrincipalArn` is not on a hand-maintained allowlist that already names this role, and `aws:PrincipalArn` resolves an assumed-role request to the **role's** IAM ARN rather than the session ARN. Assuming the same role keeps the same entry valid; a new role would need a new entry, and this repo has already been bitten by a principal missing from that list.

**`DurationSeconds` is 3600 and it is a ceiling in BOTH directions.** Shorter caps every presigned download link and every multipart upload window at the shorter value — a user-visible regression with no failing test, because a presigned URL dies with the credential that signed it. Longer is refused outright: the function runs on an assumed-role session of its own, so this call is **role chaining**, which AWS caps at one hour and fails rather than clamps.

**A claim set is exactly as fresh as its token, and that is not a new defect.** A membership change takes effect on the next **token refresh** — SPEC-056's documented behaviour, unchanged, because the carrier is unchanged. If anything the new path is marginally fresher: the credential cache is keyed on the tag set, so a refreshed token whose slots changed is a cache miss on the very next request, where Amplify's own credential cache can hold the old credentials for the rest of the hour.

**Agreement between the tag key the API stamps and the key the policies expand is ASSERTED, not structural, and the reason matters.** `var.principal_tag_key` reaches only the analytics module; `portal-role-permissions.json.tftpl`, `portal-role-shared-space.json.tftpl` and `identity-pool.tf` all hard-code the literal. "One variable feeds both, therefore they cannot drift" is **false**, and threading the variable through those templates to make it true would edit templates the preservation claim forbids touching. So the guard is a read-back against the declaration AWS actually applies, plus a `validation` pinning the variable — because a default guards nothing on its own: an empty `TF_VAR` satisfies a required variable *and* overrides a default. A wrong value produces a session whose tags match no statement, which reads as `AccessDenied` everywhere and names nothing.

**The trust statement's conditions are a ceiling, never a floor, and the limit is stated rather than implied.** `ForAllValues:StringEquals` on `sts:TagKeys` bounds which keys may appear; it is satisfied by a subset **and equally by a request carrying none**, so it cannot require that `username` was stamped. It constrains keys and **not values**, and IAM offers no way to constrain a value. The unspoofability argument rests entirely on the value coming from a claim of a signature-verified token. Both actions — `sts:AssumeRole` **and** `sts:TagSession` — are required in the same statement: either alone renders, plans, applies and unit-tests green, then fails at runtime with a refusal naming neither the tag nor the missing action.

### Two credential planes, declared per route, defaulting to the user plane (SPEC-196)

> **AMENDED by SPEC-197 (2026-08-27) — the registry became a FIELD, and the guard's teeth moved.**
> `ROUTE_PLANES` is gone. The plane is declared on the route itself (`Route.plane`) in the transport
> contract, and `planes.planes_for()` derives it per call. The decision below is unchanged in every
> respect that matters — two planes, the user plane by default, the dangerous direction one-way —
> but the *mechanism* named in it is not what ships.
>
> The set-equality guard between the table and the dispatch table becomes a **tautology** once one
> derives from the other, so it is retained as a labelled regression tripwire rather than as the
> guard. What carries the guarantee instead: `plane` is a **required** `Literal` field, so a route
> cannot be declared without choosing; and a value that is neither of the two **raises at
> derivation**. That last half is one the set equality could never carry — a typo resolving quietly
> to user-only is indistinguishable from a correct user-only route, and the fail-closed guarantee
> would be gone with nothing to show for it.

**The failure mode fails OPEN, which is the whole reason this is machinery rather than convention.** A helper handing back the wrong client does not error — the call **succeeds**, against the wrong identity, returning right-looking data. There is no symptom to wait for. So: every AWS client comes from exactly one of two constructors, the **user plane** (the caller's assumed session) or the **API plane** (the execution role); the user plane is the default, because the dangerous direction is a user-scoped call escaping onto the execution role; and a route reaches the API plane only by being named in a registry whose keys are guarded for **set equality** against the router's dispatch table, because a hand-maintained list rots.

**The enumeration is an AST sweep, not review.** It forbids `boto3.client`/`resource`/`Session` and any import of `cpcommon.clients` — the second half matters as much as the first, because that module is a cache of *default-credential* clients, exactly the shape that works in every single-user test and serves the execution role's identity in production. The sweep **counts**: the package holds exactly one construction site, since "none outside the layer" is satisfied by a layer building six. It also closes the doors *around* the doors — a private import from the identity layer, and a `UserIdentity` minted anywhere but its own module, which would assume the role as somebody else and pass every test supplying a matching token. Every exemption is by **exact module path**, never a pattern: a pattern exemption silently exempts the next module named similarly.

**The route is set on the way IN, and this is the ordering that fails open when reversed.** The Python runtime does not hand each Lambda invocation a fresh context, so cleanup-on-exit is skipped by any path that does not reach the cleanup — and a route key left behind means the next request on a user-only route reaches the execution role and succeeds. The router sets a sentinel that authorizes nothing as its first statement, before even the public-route check; the exit reset is a second line, not the load-bearing one. The test that catches this is a **sequence** with the exit reset neutered, because while cleanup always runs the two are indistinguishable.

**An assume failure is a FAULT, never a denial, and the wrap is what makes that true.** STS answers `AccessDenied` when the trust policy is wrong — a missing `sts:TagSession` renders, plans, applies and unit-tests green — so an unwrapped error reaching the failure mapping carries that service code and is indistinguishable from the isolation model working. Every user would be told they lack a permission only an operator can restore. The identity layer wraps every STS failure before it leaves, which strips the service response so the failure can only be classified by what it is. **Measured**: swapping the classifier's two branches changes no outcome; removing the wrap changes two.

### The credential cache is keyed on the whole tag set (SPEC-196)

**A warm Lambda serves many callers in sequence and nothing about it is per-user.** Trace baggage is *cleared* at the start of every invocation precisely so one invocation's identity cannot leak onto the next; a credential cache deliberately **survives** the invocation, so it must be **keyed** instead — on the username *and* the ordered membership slots.

**Never the username alone**: that pins a caller to whichever membership set their first request of the hour happened to carry, turning refresh-to-propagate into refresh-and-nothing-happens. **Never nothing at all**: that serves the second caller the first caller's session, which succeeds against the wrong identity with the right-looking data. **None of this is visible to a single-user test**, which is why the assertion is a sequence in one process — request A, then B, then A again inside the margin — and why each clause is load-bearing: without the credential check a shared cache passes; without the call count a cache keyed on the request id, safe but useless, passes; without the tag check a cache that re-assumes with the previous caller's tags passes. It is measured on the access key the **client constructor** recorded, because reading it back out of the cache measures the cache rather than the thing a route can call.

**The expiry margin is the life of one REQUEST, derived from the function's own timeout** — the schedulable unit — with the longest downstream call subsumed by the same bound rather than omitted from it. No clock-skew literal is invented on top: the single forced re-assume **is** that allowance. The retry runs on a **new** client, because boto3 binds credentials at construction, so a proxy that re-assumes and re-calls the object it already holds fails again — fail-closed, but decorative, and green.

### The error shape: a machine code, and operator text nobody renders (SPEC-197)

A failure body is `{"error": {code, requestId, detail?}}` — the only wrapped shape in the API, since
a success body is the payload itself and a `{data: …}` level is one every ported service would strip
forever. `code` is drawn from a closed enum; `detail` is operator text authored at the raise site,
read in a devtools panel and in `logs/`, and **rendered nowhere**.

The browser chooses every user-facing sentence from the code, through `lib/errorMessages.ts`. An API
that returned a sentence for the SPA to display would reverse that quietly, because the sentence
would look fine in every screenshot.

**The trap is a rule written to uphold it.** `CODE_RULES` contains eight `passthrough` rules whose
whole behaviour is *return the service's message unchanged*. If the API ever returned one of those
codes, server text would reach a user through one of the rules protecting against exactly that. The
guard intersects `API_ERROR_CODES` (generated from the Python contract) with `PASSTHROUGH_CODES`
(computed from the rules) — **two derived sets, never two lists** — and covers the two codes the
client mints as a third. Verified by adding a passthrough code to the Python contract and watching
it redden.

**An unrecognised code resolves to the generic sentence, and that is the deploy-skew case rather
than a fallback nobody meets:** the API deploys before the SPA image, so an old bundle *will* meet a
new code. A missing rule is not a crash — it is the generic wording, which is right for an unknown
code and wrong for a known one, and only a guard tells them apart.

One collision surfaced on the way: `InvalidRequest` is both an API code and a code two browser
services already mint. Both resolve to the same generic sentence, so nothing changed for them — but
a **code** rule wins over an engine-message **match** rule, so a fixture sending `InvalidRequest`
with Athena text stopped reaching the column-name hint. The fixture now sends Athena's real
`InvalidRequestException`, which carries no code rule.

### The contract is declared in Python and the TypeScript is generated (SPEC-197)

Two hand-edited copies rot. A contract test both sides hand-wrote against each other compares a copy
of the answer with itself, and it agrees most confidently exactly when both were written by the same
session on the same afternoon. So `lambdas/api/apicommon/contract.py` is the single declaration and
`scripts/generate_api_contract.py` emits the TypeScript.

Python is the source rather than TypeScript because the runtime request validator and the wire types
must read **one** declaration — a validator written against a separate schema is a third copy, and
the third copy is the one nobody regenerates. The generator and the validator consume the same
`walk` of the same annotation, asserted structurally: an AST check that the generator defines no
walker of its own.

**Two gates.** CI regenerates and refuses a diff on the generated file, which catches both
directions — a Python type edited without regenerating, and the generated TypeScript hand-edited.
`npm run build` is the second: a field removed or renamed regenerates into a changed type and fails
at every call site, which no test has to be written for.

**The type vocabulary is closed and the emitter never falls back.** `str`, `int`, `float`, `bool`,
`None`, `list[X]`, `X | None`, `Literal` over strings, references to declared `TypedDict`s, and
optional keys in both spellings. Anything else **raises**. This is the requirement that can silently
succeed: a fallback type agrees with every possible value, so the day the emitter meets a shape it
cannot express is the day the contract stops being checked and nothing goes red. It never emits
`unknown` and never emits `any`.

### `apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)

Zero retries under every condition — a timeout, a 429, a 503, a network failure — asserted as a
`fetch` call count of exactly one. Retrying a 429 amplifies the condition that caused it.

**Exactly one exception, and deleting it signs every user out at the hour mark with a green suite:**
a 401 triggers one forced token refresh and one retry, and no more. That refresh is the browser's
only token-refresh path. The test that says so is a count — a 401-then-200 sequence issues exactly
two requests, and a 401-then-401 sequence issues exactly two as well.

Whether a call may be retried *above* the client is a property of the **route**, declared in the
contract and never derived from the method: a `POST` that resolves a free name is a read, and a `PUT`
that appends is not. `apiRetryPolicy(routeId)` is the only source of a TanStack Query `retry` value
for an API-backed hook, and the test enumerates the generated table so a route added later is covered
without the test being edited. The reason it is a rule rather than a habit: a failing apply in the
Data Explorer once issued **two** `StartQueryExecution` calls 1.1 s apart, because `retry: 1` had been
set on something that looked like a read and was a billed, stateful action.

**The client's timeout sits ABOVE the function's**, so the server always gives up first and a client
abort always means a genuinely dead connection. A shorter client timeout aborts requests the server
then completes, which for a write is a mutation the user believes failed. The ordering is created by
the function's 29 s against the integration's 30 s ceiling — not, as the spec's constant name
suggested, by a 29-second gateway timeout that does not exist.

### Cognito tokens are held per TAB, not per browser (2026-08-27)

Amplify's default token store is `localStorage`, so an ID token survived a browser restart and was
readable by anything running on the origin. `configureAmplify` now hands the provider the
tab-scoped store instead.

**The cost is deliberate and user-visible**, which is why it is a decision rather than a tidy-up:
there is no "stay signed in" any more, a second tab signs in again rather than inheriting the
first one's session, and a link opened in a new tab lands on the Hosted UI first. Nothing in
`helpContent.ts` promised otherwise, so no guide became untrue — but a later spec adding one must
know this is the behaviour.

**Set AFTER `Amplify.configure`, never before**: the provider resolves the pool it was configured
with, and a store installed on an unconfigured provider is discarded. Both halves are guarded, and
both guards were verified by planting the mistake.

**It touches sign-in, which a warm session cannot exercise.** The offline tests assert which store
the provider is given; they cannot drive a real authorization-code round trip, and Amplify keeps
the OAuth `state` and PKCE verifier in its own store — so the two now live in different stores.
Expected to be fine, not observed. Recorded in `owed.md`, along with the SPEC-192 fresh-sign-in
check this **re-invalidates**.

Requested by Andrew alongside SPEC-197 and shipped as its own commit, so it can be reverted without
the port.

## Storage, and the fact S3 is not a filesystem

### File ops = filesystem UX

Download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md Known Constraints.

### A partial teardown never frees the space name (SPEC-151)

`delete_objects` and `batch_delete_table` both answer **HTTP 200 with a per-item `Errors` array** — a
key or table that failed individually does not raise. Both return values were discarded, so a
partially-failed teardown was indistinguishable from a complete one, and `delete_space` went on to
`reg.delete(space)` — the line commented "LAST — the name is now free to reuse". The next space
created with that name would inherit another tenant's objects.

Both helpers now raise `teardown.TeardownIncompleteError`, and the rule is: **a teardown that could
not finish must leave the registry record intact.** The record is what reserves the name, so keeping
it is what stops reuse; the caller's existing `except` already records a terminal `failed`, and
`reg.delete` is inside the `try` it never reaches. `forget-space` inherits this for free — both verbs
share the helpers.

Three details that are decisions rather than implementation:

- **Counts, never keys.** The message reaches logs and the registry's `failed` record, and the field
  rule binds what a call site chooses to emit. "3 object(s) under `sales/` could not be deleted" is
  enough to tell a partial failure from a total one.
- **Every page is attempted before raising.** A denial on one key must not strand the rest of the
  space's objects, and the count is only meaningful whole.
- **The Glue raise lands BEFORE `delete_database`.** Dropping a database whose tables survived is how
  the catalog and the bucket start disagreeing.

This meets **SPEC-054**'s written acceptance criterion — teardown leaves "never a dangling …
half-deleted resource" — which had been recorded and never implemented. **Do NOT "improve" this by
deleting the record and reporting the failure elsewhere:** the record IS the lock.

### An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)

A `user_settings/` read-modify-write that cannot read the live body **copies it aside and then
writes**, rather than refusing forever (the previous behaviour) or committing the empty document
over it (the behaviour before that). The copy is a **precondition**: if it fails the write is
refused exactly as before. **A failed quarantine must never become a silent overwrite.**

The refusal it replaces had no way out. `user_settings/` denies `s3:DeleteObject`, the bucket is
unversioned, there is no admin UI and there never will be (out of scope) — so one unreadable
document permanently disabled saving queries and recording history for that user, and the only
honest advice was "Contact the Administrator", whose only tool is the AWS console.

**A newer schema is not corruption, and quarantining one would BE the data loss this prevents.**
The classifier (`lib/s3Json.classifyDocument`) reports three outcomes, not two, and checks the
version **before** the shape — a `version: 2` document is newer whatever else it contains, because a
newer schema is free to have renamed the field this build validates. A newer document is refused
untouched and answered with "reload the page"; only `unparseable` is ever copied.

**The quarantine key carries a random token as well as a timestamp, and that is load-bearing.**
`CopyObject` copies whatever is live at copy time and nothing binds the copy to the body that was
classified. Two tabs finding the same corrupt document in the same second, keyed on a clock alone,
would collide: the first sets the corrupt bytes aside and repairs the document, the second copies
the now-**repaired** document over the first one's quarantine object — destroying the only surviving
copy, on a folder that denies delete. The token makes the loser write a redundant object instead.
Do **not** "simplify" the key back to a bare timestamp. (The ordinary last-writer-wins race on the
document itself is untouched and still accepted; `IfMatch` writes are a separate, complementary fix
that this neither needs nor blocks.)

**No IAM change, deliberately.** Everything is `GetObject` + `PutObject` inside the user's own
prefix — which is why the quarantine key is a sibling of its source rather than a separate folder.
Two consequences follow and are recorded here rather than discovered later:

- **Quarantine objects are themselves undeletable.** They inherit the `user_settings/` delete deny,
  so neither the app nor the user can remove one — only an administrator working directly in the
  console can. Accepted: one object per genuine corruption event is a smaller problem than the
  evidence being destroyed.
- **Accumulation is not a loop.** The document written after a quarantine is one the app serialized
  itself, so a second quarantine requires a second, independent corruption.

**Rejected, and recorded in the spec so they are not re-proposed:** granting the portal role
`DeleteObject` under `user_settings/` (trades away a standing safety property for convenience, and
destroys the only copy of what the user had); "click Save again to replace" (reintroduces the loss
behind a confirmation the user cannot make informed, since they cannot see the document); repairing
the document in place (a guess presented as a recovered library); writing the copy from bytes
already in memory (carries an unbounded untrusted body out through the parse contract, and costs a
second `GetObject`); and a fixed quarantine key overwritten each time.

### The file-send plane is its own, and its front door is bounded by a chain (SPEC-164)

**Decision.** "Send these files to Bob" gets its **own control plane** — its own FIFO queue, DLQ,
Pipe, Standard state machine, execution role and `fscommon` domain layer — rather than becoming a
mode on table share's.

**Why not a mode.** The two features share an *algorithm* (`cpcommon.transfer`) and nothing else:
different request contract, different authorization question, different failure vocabulary. Folding
them together would put one queue and one DLQ under two unrelated user features, and a malformed
send would dead-letter someone's table share. The pattern is reused; the resources never are.

**The envelope is flat, and that is a contract with a shared security path.** `actor` is the raw ID
token at the **top level**, not `actor.idToken`. The spec was written nested and was amended during
the build, because SPEC-126's drain reads `body.get(token_field)` flatly and `_redacted` replaces
**top-level keys only** — a nested token would have (1) resolved no recipient on every
dead-lettered send, silently, since the drain swallows and returns, and (2) written the raw JWT to
CloudWatch, whose audience is far wider than the queue's. One envelope shape across five planes
beat teaching a shared security path a second one.

**Source authorization is about the space's status, never the member's join chip.** A `personal`
source must equal the verified username; a `shared` source needs `cpcommon.registry
.is_active_member`. The spec's original wording ("`pending`, `leaving`, absent") named a status
that does not exist and one that is a *member* concept — reading it that way would have reversed
**SPEC-073**, denying a send for files the same user can already browse, download and table-share.

**Containment is three rules, and the third was found by review.** (a) the root comparison is
trailing-slash-normalised, so `alice2/` is not inside `alice/`; (b) any `.`/`..` **path segment** is
refused, because `"alice/../bob/x".startswith("alice/")` is `True` — not exploitable against S3
today, but the same string becomes the item name in the destination key; (c) `athenaresults/` is
refused as the folder, as anything beneath it, **and as any folder that CONTAINS it**. (c) exists
because selecting the space root passes (a) and (b), and SPEC-165 expands a folder by listing its
prefix — in a shared space that is other members' query results leaving with the send. Folder keys
are normalised to a trailing slash for the same reason: `ListObjectsV2(Prefix="alice/athenaresult")`
matches `alice/athenaresults/…`. The results rule is **new for this plane**, not a reuse:
`protectedFolders.ts` keeps three deliberately divergent lists and in none of them is copying *out*
of that folder refused.

**Two caps, because there are two quantities, and the byte one is bounded by a CHAIN.**
`SEND_MAX_ITEMS` (200) bounds per-item work — two containment checks now, one `ListObjectsV2` per
folder in SPEC-165. `SEND_MAX_ITEM_BYTES` (96 KiB) bounds the serialised selection. **A count cap
cannot bound bytes**: S3 keys are arbitrary UTF-8 and JSON escaping expands `"` to two bytes and a
control character to six, so 200 items at a 1024-byte key measure 216 KB of ASCII or 1.2 MB of
`\x01`. And **a byte cap measured against the state alone is not enough either**: the browser's SQS
body carries the selection, the Pipe re-escapes that body into the record it hands to
`StartExecution`, and that input is capped at 256 KB too — so a quote-heavy selection arrives at
**twice** its measured size, and an over-limit request cannot start an execution at all. Both wrong
models shipped in review and each read as satisfied. The producer mirrors both caps (a request too
large for `StartExecution` never reaches the verb that would refuse it) and a test holds the
TypeScript numbers against the Python ones.

**Do NOT** reintroduce a single cap, and do not raise either without re-running
`test_config_fscommon`, which computes all three links.

**The failure path reads the request from the context object.** `validate-authorize`'s input is the
Pipe's JSON *array*, so its Catch has no object to merge a `ResultPath` into and the error
**replaces** the state — taking the only copy of the caller's token with it. The seed therefore
reads `$$.Execution.Input`, which survives whatever the Catch did; reading `$$` in a **Pass** state
is SPEC-157's recorded shape. Without it `NotifyFailure` takes its no-recipient branch on every
single failure — SPEC-152 satisfied on paper and silent in practice, on exactly the cold-start and
timeout failures it exists for. **Threading the request through the state instead was tried and
rejected**: the Pipe record carries the same selection again as an escaped string, so it roughly
doubles the payload for the whole run.

**FR-006 — the user-space bucket policy's allowlist is hand-maintained, and this is the shape that
rots.** An explicit resource-policy Deny beats an identity-policy Allow, so a plane whose execution
role is missing from `user-space-bucket-policy.json.tftpl` is denied by the bucket however correct
its own grants are. For a send the failure is asymmetric enough to read as a code bug: every
`space` recipient succeeds (the shared-space bucket has no bucket policy) and every `user` recipient
fails `AccessDenied`. The change is three parts — a variable in `modules/data`, the
`templatefile()` argument, root wiring — with the ARN a **constructed string**, because an
unknown-at-plan ARN inside a list silently drops the change.
`lambdas/test_user_space_bucket_allowlist.py` pins it three ways and was verified against a
deliberate omission.

---

### A received file lands in `shared_files/{sender}/`, and one function builds every key (SPEC-165)

**Decision.** Everything a sender sends lands at
`{targetRoot}shared_files/{sender}/{itemName}[/{relKey}]`, computed by a single
`fscommon.paths.destination_key`, with `shared_files` a named constant and a test sweep forbidding
any verb from composing its own.

**Why namespaced by sender.** This is what a recipient sees forever, and it is the decision with
the longest half-life in the arc — a layout is not something a later spec can quietly change, since
files are already sitting in it. Mirroring `shared_tables/{table}/` buys three things at once: two
senders sending `reports/` never collide, provenance is visible in the file browser with no
metadata lookup and no second request, and the recipient's own top level stays theirs rather than
accumulating a folder per sender's whim.

**Why the destination is keyed by ITEM NAME, and what that forces.** The alternative — preserving
the sender's path — leaks their folder structure into someone else's space and makes the
destination depend on where a file happened to live, so `alice/deep/nested/q1.csv` and
`alice/q1.csv` would arrive differently for no reason the recipient can see. Keying by name means
`a/reports/` and `b/reports/` would interleave into one folder, so that selection is a
**whole-request refusal naming the collision** — as is a selection where one item contains another
(copying the object twice and silently dropping one are both worse than a clear refusal). A
**repeated** item collapses instead: there is one right answer and no ambiguity about intent.

**A repeat is `(kind, key)`, and the key alone is not enough.** validate-authorize normalises a
`folder` key to a trailing slash and leaves a `file` key exactly as it arrived, so
`{"file","alice/reports/"}` and `{"folder","alice/reports"}` reach the expansion as one key with
two kinds. Collapsing on the key kept whichever came first: the file reading sent one zero-byte
placeholder and **none of the folder's contents**, reporting success, with the outcome depending on
the order of a JSON list. That is precisely the silent drop this rule exists to prevent, arriving
through the one part of it that was supposed to be safe.

**Why one builder.** The destination tests can only ever prove the ONE builder is right; a verb
concatenating its own would pass every one of them while writing somewhere else, and the symptom
would be files in the wrong inbox rather than an error. The sweep reads the AST for a
`shared_files` literal or an f-string composing the constant, exempting docstrings and the
declaration **by node identity** — an earlier version skipped the `Expr` and not its `Constant`
child, and flagged two module docstrings. Verified against four deliberate violations, including
one placed after a docstring.

### The file-send exclusion rule is anchored at the space root, not the listing prefix (SPEC-165)

**Decision.** `fscommon.expand` carries its own ignore predicate — folder placeholders, the prefix
marker, and `{root}athenaresults/` — and `cpcommon.s3_listing.list_data_objects` grew an optional
`ignore` parameter rather than being forked or reused as-is.

**Why not reuse `is_ignored`.** Every rule in it is anchored at the **listing prefix**. That is
right for the three analytics planes, which list a table's or a check's own folder, and wrong here:
the listing prefix is whichever item the user picked. Sending `alice/reports/` would have dropped a
user-made `alice/reports/athenaresults/` — which SPEC-164 explicitly records as an ordinary
sendable folder — and any `_drafts/`, with **no refusal and no message**. A silent drop from a send
that reports success is worse than either copying it or refusing it. The hidden-segment rule also
exists because *Athena* ignores such paths, which says nothing about a byte-for-byte file copy.

**Why a parameter rather than a second paginator.** The pagination genuinely is shared, and it is
the part a fixture proves least — the 1,000-key boundary is where a truncated listing returns a
plausible smaller number rather than an error. One paginator, and a plane whose exclusions are
anchored elsewhere says so at the call site. The default is byte-identical for the three existing
callers, held by a test in both directions.

**Two consequences, both deliberate.** A genuinely **empty file is sent** — `is_ignored` drops
every zero-byte object, and a folder placeholder is excluded by its trailing slash instead, the
shape `createFolder` actually writes — so an **empty subfolder does not survive a send**. And the
`athenaresults/` exclusion has **no live path** through the shipped front door, because
validate-authorize refuses a root selection outright; it is written anyway, for the reason SPEC-164
gave for writing that rule as containment rather than equality.

**`user_settings/` is excluded too, and it is NOT in the spec's list.** Narrowing the analytics set
to the three rules FR-001 AC4 names would have dropped it without anyone deciding to: it holds the
sender's notification inbox and shared-space connections cache, `protectedFolders.ts` hides it
everywhere in the browser, and — unlike the two rules this plane deliberately does not reuse —
anchoring it at the space root preserves the exclusion with **zero** false positives. Narrowing an
exclusion set is a decision; this one had not been made, only inherited by omission.

**The exclusions apply to a selected FILE as well as to a listing**, and applying them only to the
listing was a real defect. Nothing upstream filters a `file` item — validate-authorize normalises a
*folder* key to a trailing slash and leaves a file key untouched — so naming `{root}DO_NOT_DELETE.txt`
as a file copied the prefix marker into someone's inbox, and naming a folder *as a file* copied its
zero-byte placeholder as a file. AC4 says excluded from the copy set; it does not say "when they
turn up in a listing".

### The expansion caps are sized by memory and makespan, and the obvious models miss both (SPEC-165)

**Decision.** `SEND_MAX_OBJECTS` = 20,000 and `SEND_MAX_TOTAL_BYTES` = 1 TiB, each computed by a
test. The per-object cap and the recipient product cap are **deferred to SPEC-166**, not omitted.

**What sizes the object cap is the plan in memory, not the listing.** `inspect-source` holds the
whole plan as a list of dicts, serialises it and encodes that — three live copies at the write. At
S3's worst-case 1024-byte keys an entry is ~2.4 KB, so 20,000 objects is ~45 MB and peaks near
135 MB, against the 1024 MB in `locals.tf` **which the test reads back**: raising the cap without
raising the memory fails the build.

**And the timeout half is where a page-counting model goes wrong.** Twenty `ListObjectsV2` pages is
four seconds and reads like the whole answer. The term it drops is that a `file` item costs its own
**serial** `HeadObject`, so 200 files is 200 round trips and forty. The bound is per-ITEM plus
per-PAGE, the item half dominates, and an assertion pins that so a future reader re-derives rather
than trusts it.

**The byte cap is a makespan, not a bandwidth.** `cpcommon.transfer` hands one whole object to each
worker and part-copies serially inside one, so the denominator is
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` — 500 MB/s, not the ~4 GB/s the same
constants suggest under an aggregate reading. That is the mistake SPEC-161 found twice, in review
rounds, after it read as satisfied both times.

**Why two caps are deferred rather than guessed, and why BOTH need a tripwire.** The per-object
cap and the `recipients × bytes` product are measured against the copy verb's
`COPY_TIMEOUT_SECONDS` and the machine's top-level `TimeoutSeconds`, and this machine has neither.
The copy plan already carries every object's size, so SPEC-166 enforces both with no second listing
and still before any byte moves.

**The per-object gap is the one that undermines a passing test, and it first shipped in prose
only.** 500 MB/s is reachable only when the bytes are spread across the worker pool; ONE object is
ONE worker at 25 MB/s, so the makespan test certifies the **distributed** case and a single 1 TiB
object is **43,980 s** — four times over the ceiling it compares against. That is table-share's
recorded shape word for word ("while `SHARE_MAX_TOTAL_BYTES` was 20 GiB the bound was implicit …
raising the total to 1 TiB removed it without anything replacing it"), and this plane *starts* at
1 TiB. Both gaps carried a `hasattr` tripwire that **failed the day SPEC-166 added the cap**, and
the arithmetic was kept as an assertion so 166 inherited the size of the problem rather than
re-deriving it.

> **SUPERSEDED in part by SPEC-166.** The caps arrived — `SEND_MAX_OBJECT_BYTES`,
> `SEND_MAX_TRANSFER_ITEMS`, `SEND_MAX_TRANSFER_BYTES` — with the `TimeoutSeconds` they are
> measured against, and the `hasattr` tripwires were removed by the computed bounds that replaced
> them. Full entry: *The three transfer caps are each measured against a DIFFERENT budget
> (SPEC-166)*.

### An expected refusal is a return value, and a conflict is per item NAME (SPEC-166)

**Decision.** `check-target-absent` returns `{status, recipient, reason, detail}` for the two
refusals it expects — a recipient validate-authorize could not resolve, and a name conflict — and
its Map item's `Catch` is left for faults nobody predicted. The conflict is decided by **item
name**: one delimited listing of `{targetRoot}shared_files/{sender}/`, compared against the names
the selection would create. A taken name refuses **that recipient**; nothing is merged and nothing
is overwritten.

**Why not raise, as table-share's guard does.** A conflict has to name the colliding item, and a
`TerminalError` cannot carry one to a user: its `tokens` are deliberately kept out of the exception
message (they would corrupt `failure_reason`'s colon split) and its `detail` is operator text that
may quote raw service output, which SPEC-106 forbids rendering. Parsing a filename back out of a
Step Functions `Cause` would be fragile *and* a rule break. The collector therefore reads two
record shapes and decodes the raw `{Error, Cause}` only for the unpredicted one.

**Why a delimited listing rather than a probe per item.** Two round trips per item is 20,000 serial
calls for a full selection against a full recipient list — and a `MaxKeys=1` probe at
`Prefix={inbox}{item}` **cannot answer the question at all**: S3 orders keys lexicographically and
`/` (0x2F) is not the lowest byte a key may carry, so `notes.txt-old` sorts before
`notes.txt/part-0` and the one key returned reads as "clear" over an occupied destination. The
listing is bounded by what that sender previously sent to that recipient, not by the size of the
send.

**A name is a name whatever it holds.** A previous send of the file `notes.txt` conflicts with a
new send of the folder `notes.txt/`, because `destination_key` gives both the same base.

**Neither the guard nor the collector notifies.** Every per-recipient outcome is told to the sender
once, from the terminal summary, by SPEC-167's producer. Table-share notifies from its own guard
because it has no such producer; copying that here would send two messages about one conflict.

**Two fail-open holes, both found in review and neither visible to the suites as written.** The
guard cleared every recipient when the selection arrived empty (no names ⇒ no collisions ⇒ `ok`,
over an inbox that already held the send) — three lines from a missing *actor* that already failed
closed. And the collector reported universal success when the `transfer` block was absent, without
making a single S3 call; it is closed by an invariant already on the event, that the manifest
builder cannot report zero items while a recipient cleared the guard.

**Not closed: the guard is TOCTOU.** Two sends of the same item name from the same sender to the
same recipient, submitted close together, can both clear it. Inherent to check-then-copy with no
lock, and table-share has the same shape.

### The transfer caps are three, and each is measured against a different budget (SPEC-166)

**Decision.** `SEND_MAX_OBJECT_BYTES` **10 GiB**, `SEND_MAX_TRANSFER_ITEMS` **50,000**,
`SEND_MAX_TRANSFER_BYTES` **3 TiB**, all enforced in `inspect-source` before the plan is written,
and the two product caps measured on the **requested** recipient count.

**Each is a different budget, and using one model for all three is how table-share's own bound came
to be wrong twice.** The per-object cap is bounded by `COPY_TIMEOUT_SECONDS`, the batch verb's own
Lambda timeout — a batch is exactly one round of the worker pool and one object is one worker, so a
batch costs its slowest object. The item cap is bounded by the **memory** the two verbs either side
of the Map hold the manifest in, read back from `locals.tf`. The byte cap is bounded by the whole
run's **makespan** against the machine's `TimeoutSeconds`, at
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s and **not** the ~4 GB/s the
same constants suggest multiplied together.

**The per-object cap is the one whose absence made every other model a half-truth.** SPEC-165
recorded it as owed and kept the arithmetic: without it the worst legal case was a single 1 TiB
object on one worker — 43,980 s, four times the ceiling — while `test_a_full_size_selection_copies
_inside_the_engines_ceiling` read as satisfied. It is table-share's value exactly, deliberately:
same engine, same batch size, same timeout.

**`SEND_MAX_TRANSFER_ITEMS` deliberately diverges from table-share's 20,000.** That plane's
transfer cap equals its own object cap, so at full size it permits one recipient — fine when a
share is one table. A 2,000-file folder to a 30-person team is the ordinary case here. The computed
memory ceiling is ~150,000 items; 50,000 takes a third of it.

**Measured before the guard, on purpose.** Counting only the recipients who clear their conflict
check would let the expensive half of the work happen first, and would make a refusal depend on
what someone else's inbox happens to hold.

### One producer says every per-recipient outcome, and the link carries the recipient's own root (SPEC-167)

**Decision.** A single verb at the end of the machine turns SPEC-166's terminal summary into
messages: one to the sender per recipient outcome, one to each recipient who actually received
something — a ``user`` directly, a ``space`` through its registered OWNER, never its membership.
Its link is `/files?prefix={recipientRoot}shared_files/{sender}/`, with `?space=` as well for a
space.

**Why one producer rather than a decorator per verb.** Table share notifies from its guard, its
collector and its create verb because each is the only place its own outcome is known. Here every
per-recipient outcome reaches one flat list before anything is said, so one place can say each
thing once — and a decorator on the guard would make a conflict two messages. It is also what
lets the guard return its expected refusals as records: the colliding item name has to reach the
producer, and a `TerminalError` cannot carry one to a user. The whole-REQUEST verbs still notify
from their decorators, and must: a request that dies before this state never reaches it.

**A failed recipient is told nothing.** They have no part in the send, nothing to do about it, and
being told would leak that the sender tried.

**Why the link carries the recipient's root.** `FilesPage` keeps a `?prefix=` only when it starts
with the resolved space's `rootPrefix`, so a root-relative prefix is silently discarded and the
recipient lands at their space root — a link that looks like it worked. Two tests read the route's
gate, `rootPrefix`'s own definition and `isSafeInAppPath`'s accept rule out of the TypeScript, so
the two languages cannot drift; the first version pinned only the gate and compared against a
hardcoded value, which would have stayed green through the rename it existed to catch.

**The link is feature-gated, and that was a review finding.** With `files` off it was a live anchor
into the unavailable page; with `sharedWorkspaces` off the space link resolved the personal space
and dropped the prefix — the exact failure the full-key rule exists to prevent, reachable from flag
state alone. `NotificationRow` now gates a MAP of flag→match rather than one hard-coded prefix, with registry rows for both — and the space arm matches on `?space=`, because that variant differs in its query rather than its path.

**The double-submit guard is the in-flight ref, NOT the queue's dedup id.** FR-003 AC5 said
otherwise and was amended in build: the `requestId` is minted per SUBMIT, because it is also what
makes a retry possible — reused across a failed attempt, the second send is swallowed by the queue
and the user gets an error, presses the button again, and nothing at all happens. The trade is a
first send whose response was lost being retried as a new request, which the conflict guard then
refuses per recipient and tells the sender about.

**A refusal must be reachable to be a refusal.** The dialog's Send control stays ENABLED with no
recipients: `submitDisabled` made the inline refusal dead code where an acceptance criterion was
supposed to be, and a test asserting only "the button is disabled" passed over it. A disabled
button also explains nothing to the user who typed a name and forgot to commit it.

---

### A saved query is a FILE, and the folder holding it is ordinary except in one respect (SPEC-173)

**Decision (2026-08-11).** Saved queries move out of `{username}/user_settings/saved-queries.json`
and become `.sql` objects in `{root}saved_queries/`, a folder at a space root. The folder is
**visible, browsable, uploadable into, a valid move/copy destination and free to hold subfolders**;
individual files inside it may be deleted by anyone with access to the space. Exactly one thing is
protected: the folder **itself** cannot be deleted or renamed. It appears in
`UNDELETABLE_ROOT_FOLDERS` and in **neither** of the other two lists, and a test asserts that
absence, because `protectedFolders.ts`'s three lists answer three questions (see / paste / destroy)
and this folder is the second case that proves they are not a union. Rename is a move — S3 has
neither — so `moveFolder`'s existing refusal covers both with no new guard.

**What keeps the load list coherent is a FILTER, not a write lock.** Because anyone may drop a CSV
or a folder tree in, the store offers **top-level `.sql` files and nothing else**; that filter is a
requirement with tests rather than a precaution, and `Delimiter: '/'` is load-bearing beside it
(`saved_queries/archive/old.sql` is a file in a folder, not a saved query). The depth check is
asserted in the service too, so one-level-ness is a property of the STORE and not of one request's
parameters. A folder the user cannot treat as a folder is a folder they will fight, and a saved
query nobody can throw away is one that accumulates forever — the narrowness is the design.

**The key is the identity and the filename is the name.** There is no id and no record, because a
`.sql` file cannot carry one without a sidecar this feature deliberately does not have. The listing
returns S3's own (lexicographic) order, unmodified: sorting by last-modified across a paginated
listing is the lie SPEC-123 records about the data-quality runs index — the newest query may sit on
page nine, and a client-side re-sort of the loaded pages makes rows the user has already seen jump
between pages as later pages arrive.

**The queries in the old store are abandoned, not migrated** (user decision). The portal is
pre-production with no real users, and a migration is code with one execution and no way to test
its second run. The document is left in place (`user_settings/` denies delete) and the store's code
is **deleted**, so there is one saved-queries system in the tree and no second definition of what a
saved query is.

**Three user-visible losses, each accepted on its own reasoning.** The drawer loses its **SQL
preview**: a `.sql` object carries no body until it is read, so a preview means a `GetObject` per
row on every open — twenty-five round trips to show twenty-five one-line snippets. **Every Save now
asks for a name**, a linked tab's included, pre-filled and selected, where SPEC-043 wrote back
silently: a user about to overwrite a file should be told which file, in which space. And the
collision check moves from a case-insensitive scan of the loaded array to a **HEAD on the exact
key** inside `writeSavedQuery` — the scan stopped being sound once the list is paginated and the
target space may not be the one on screen — so `Report` and `report` are now two saved queries,
because S3 keys are case-sensitive.

**The dirty marker is a SESSION SNAPSHOT, and its gap is stated rather than discovered.** SPEC-043
compared a tab's buffer with the `sql` field on a store row; there is no such field. The workspace
keeps a `key → sql` map of what this session last saw — the body fetched when a query was opened,
or the buffer just written by a save — and marks a tab dirty against that. A tab restored from
`sessionStorage` after a reload therefore shows no marker until it is opened or saved again. The
alternative was a `GetObject` per linked tab on every mount, which is the same trade the preview
line lost.

**Do NOT build:** a sidecar metadata file beside each `.sql`; a recursive listing (a `.sql` file
the user tucks into a subfolder is a normal file, reachable from the file browser and not from the
editor); a write lock or an allowed-extensions guard on the folder's contents; a migration from the
JSON store; or an autosave of any kind — FR-010 is a tripwire test with a zero-`PutObject` count,
because the failure it guards is silent and lands in someone else's shared space.

---

### Every `DO_NOT_DELETE.txt` is hidden by BASENAME, and the whole arc needs no IaC change (SPEC-173)

**Decision (2026-08-11).** `useFileBrowser` hid one exact key, supplied by its caller. It now hides
any object whose last path segment is `DO_NOT_DELETE.txt`, at any depth, in either bucket — and the
`markerKey` parameter is **deleted**, along with the prop threaded through `DestinationPicker`,
`MoveDialog`, `CopyDialog`, `FileBrowserDialogs`, `FilesPage` and `StartQualityCheckDialog`. A
source sweep asserts no caller passes one; `DestinationPicker`'s props stopped being a union as a
result.

**The reasoning generalises further than this folder.** Both bucket policies deny
`s3:DeleteObject` on a wildcard resource ending in the marker's own basename, and `*` in an S3
resource ARN matches `/` — so *any* object with that name, anywhere in either bucket, is already
undeletable. Showing one offers an action this application's own IAM refuses, which is the
SPEC-150 FR-007 mistake waiting to happen. That same reading is what lets the whole
saved-queries-in-spaces arc ship **no `.tf` or `.tftpl` change**: the marker at
`{root}saved_queries/DO_NOT_DELETE.txt` is covered at that depth and any other, and every read,
write, list and delete the store needs is already granted by `UserPrefixObjects` /
`SharedSpaceObjects` and their listing statements.

**It is the arc's load-bearing premise, so it is pinned and it owes a live check.** A test reads
the two `.tftpl` files and asserts each `Deny` still ends in `/*/DO_NOT_DELETE.txt`, so a later IAM
edit that narrows the wildcard fails in CI rather than in production. But a passing test over a
template is not a refusal: **a real delete of a real marker, refused, is owed** (SPEC-173 FR-009),
in both a personal and a shared space. Until it is run the reading is corroborated, not discharged
— the same class of evidence that had SPEC-144 FR-001 reversed mid-build.

The saved-queries marker gets its **own body text**: `PREFIX_MARKER_BODY` says the file keeps "your
personal storage space" active, which is wrong in a shared space and wrong about what this folder
is. It reuses `PREFIX_MARKER_FILENAME` exactly, and a test says so, because the IAM protection keys
on that basename.

---

### `saved_queries/` is gated on `query`, and the gate is not the refusal (SPEC-173)

**Decision (2026-08-11).** The folder is a Query feature wearing a file-browser row, so it is a
`GATED_SURFACES.query` **registry** row — the same shape as "Create table", the row SPEC-163 calls
the one everyone forgets — and not a per-component opt-in. With the flag off it leaves the file
browser's listing **and** the destination picker together, because a destination the user cannot
see is not a destination; that is the one place the gate touches an otherwise ordinary folder
operation, and it is presentation: it removes a way of *asking* and revokes no grant.

`DestinationPicker` reads the flag **itself** rather than taking it from its four callers, so every
picker in the app inherits the rule from one place. The cost is real and accepted: the picker now
requires an auth context, which one bespoke a11y tree had to be given.

**The delete/rename refusal is unconditional, and structurally so** — `deleteFolder`/`moveFolder`
take **no flag**, so there is no state in which the gate can reach them. That is the argument, and
it is stronger than the test FR-008 AC3 asks for: a service-level test cannot render "with the flag
off" because the service never reads one. The refusal is tested directly and the structural claim
is recorded in the test's own comment. "You cannot see it" and "you cannot destroy it" are
different guarantees, and only one of them survives a stale cached flag document.

### A save chooses its space, and one KEY rule decides what that replaces (SPEC-175)

**Decision (2026-08-12).** The Save dialog asks for a **destination** as well as a name, and the
destination it opens on is **the tab's own space when the tab is linked, else the space SPEC-174
already remembers** — one memory of "the space I am working in", written on every successful save
and shared with the load surface. Two memories were the obvious alternative and are rejected: the
user has no model of a saving-space distinct from a loading-space, so two values can only ever
disagree in a way nothing on screen explains. A linked tab whose space is no longer offered falls
through the same path a stale stored id does, to personal.

**Everything that turns on "is this the same file?" goes through one predicate**,
`isLinkedSavedQuery(link, space, name)`, and it judges the **key** — not the space, and not the
name. Three behaviours read it: the dialog's promise that a submit replaces the file the tab was
opened from, the host's `overwrite` on the write, and therefore whether FR-003's Replace confirm is
raised at all. Split across two call sites each computing its own version, the dialog could promise
an in-place replace while the host wrote a new object. A different name in the tab's own space is a
different file; so is the same name in another space.

**A linked tab's unchanged re-save is confirmed ONCE.** Every save prompts — SPEC-043's silent
write-back is gone — and the prompt has already named the file and the space, so a Replace confirm
on top of it asks about the thing just answered. `SaveQueryRequest` therefore carries `{space,
name}` and **not** `overwrite`: the dialog cannot ask for a silent clobber, because the host is the
only thing that decides one.

**Choosing another space is a copy, and the absence of a delete is the decision.** One `PutObject`
into the new space, the original left alone, the tab re-linked to the new file. Moving is not
offered: a saved query a colleague may be running now must not disappear because someone copied it
elsewhere, and a move across buckets is a copy-then-delete whose second half can fail alone.

**A write failure keeps the dialog open with the destination intact.** The realistic failure is a
shared space whose membership was revoked mid-session, returning `AccessDenied` — and the user's
next move is to pick another destination, which a toast over a closed dialog takes away from them.
The message is `toUserMessage`'s, inline on the field (SPEC-106), and the space control stays
interactive.

**Validation runs on submit; `submitDisabled` does not stand in for a refusal.** SPEC-167 records
this exact failure in the send dialog — a disabled control made an inline refusal dead code, and the
test asserting "the button is disabled" passed straight over the acceptance criterion. The same
reasoning governs FR-007: with no writable space the Save control still **opens** the dialog, and
the dialog **explains itself**, rather than the toolbar rendering a mute disabled button.

**The registry gains a row, and it is not a duplicate.** FR-008 predicted none — every surface here
lives inside `/query`, which the registry gates as a route. But the dialog's destination control is
a **second instance** of the `sharedWorkspaces` choice, and the existing *Shared spaces in the
saved-queries selector* row renders the **drawer**: nothing would notice if this control stopped
being gated, and this is the worse of the two failures, because it offers a colleague's space as a
**write** target. That is SPEC-167's own precedent for the send dialog's recipient kind. The row was
**verified against a deliberate violation** — passing the ungated list reddens exactly that row and
nothing else, measured — rather than trusted.

**A typed `.sql` extension is LOWERCASED, correcting SPEC-173's `basenameFor`.** FR-002 AC4 wanted
`report`, `report.sql` and `report.SQL` to be **one** key; 173 only skipped the *appending*, so
`report.SQL` was a second object — and since `savedQueryName` strips the extension
case-insensitively, the two rendered **identically** in the load list, on the tab and in the Replace
confirm. The reachable failure is not the ambiguity but the overwrite behind it: a tab linked to
`…/report.SQL` pre-fills `report`, which resolves to `…/report.sql`, so the confirm truthfully
offers to replace `report` and **clobbers a file the user never opened** while the one they did is
orphaned. The **stem is deliberately untouched** — `REPORT` and `report` stay two names, which is the
case-sensitivity this same spec keeps — and a `.SQL` object already in a bucket still lists and
opens; only the save path normalises, so re-saving a tab linked to one is a visible Save-as rather
than a silent clobber.

**Two of this spec's tests could not fail, and a third guarded the wrong mechanism.** All three are
recorded because the pattern recurs. (1) The default-space fork (`linkedSpace ?? defaultSpace`) was
only ever exercised where the two **agree** — `onSaved` calls `selectSpace` and keeps them in
lockstep — so either operand could be deleted with the suite green; the bug it hid writes a **copy
into a shared space** and re-links the tab, with every visible cue consistent. (2) **jsdom
implements no implicit form submission**, so "Enter on the space control does not submit" passed
whatever `FormDialog` did; the guard is asserted through **`defaultPrevented`** instead, and
`FormDialog` now intercepts `<select>` as it always intercepted `<input>` — a browser submits a form
from a closed select, and `DestinationPicker` had the same exposure. (3) FR-003 AC4's "does not list
the folder" counter cannot catch the SPEC-043 regression it names, because an **in-memory scan
issues no listing**; the force comes from a test where the loaded list and S3 **disagree in both
directions**.

---

### A file operation on more than one file belongs on a plane, and the boundary is the SELECTION (SPEC-187)

An operation stays in the browser **if and only if the selection is exactly one item and that item is
a file**. It is a property of the selection, never of the operation: the same selection routes the
same way for copy, move and delete.

**The first draft of this rule was measured against the wrong quantity.** It said an operation goes
async only when it must LIST to know what it touches — coherent, and wrong: a file-only copy or move
of K files is a sequential loop of `HeadObject` + `CopyObject` + `DeleteObject`, up to 3K round trips
from the user's laptop, which is precisely the cost the plane exists to remove.

A single folder is enqueued, **including a folder rename** — forced rather than chosen, since a
rename is one `CopyObject` per contained object and cannot be bounded without listing. It is the case
a reader assumes is synchronous, so the rule's test names it.

**The empty selection is a precondition, not an answer.** Without it, "not exactly one item" routes a
zero-item selection to the plane, which refuses an empty source as a request-shape error minutes
later, by notification.

The rule has **one home**, and the sweep that enforces it counts IMPORTERS rather than parsing for
the rule: a boolean over `kind` and `length` has no recognisable syntactic signature, so an AST sweep
would fire on every legitimate branch in the file browser. That is the opposite call from SPEC-165's
key-builder sweep, where the signature *is* recognisable.

### The file-ops lock's loser WAITS where the table-builder's is refused (SPEC-187)

Both locks exist because delivery ordering is not execution ordering. They differ on what happens to
the loser, and the difference is the scope of the lock rather than a preference.

SPEC-157's lock is per **table**, and a contended refresh is a genuine conflict: two runs would
compute an identical definition from the same files, so refusing is the honest answer. This lock is
per **space** and covers all three operations — so deleting a folder in `alice/a/` and then copying
one in `alice/b/` is disjoint and entirely safe, and refusing it would produce a reliable
out-of-band refusal after the UI had already accepted the request.

So the loser **waits and retries**, with a bounded give-up that then refuses with a notification.
Three consequences that only hold together:

- **The waiter steals a stale lock itself**, on every re-acquire rather than only the first. That is
  what makes the give-up bound independent of the steal threshold.
- **The give-up bound is strictly LESS than the machine's `TimeoutSeconds`.** The naive chain is
  unsatisfiable and must not be re-derived: requiring give-up ≥ the steal threshold, with the
  threshold > the ceiling, forces give-up > the ceiling — and the waiter is a state *inside* the
  machine, so the ceiling would kill it before its refusal could fire, surfacing as a bare
  `TIMED_OUT` rather than the message the design promises.
- **Waiters are unordered, and that is accepted.** The Pipe starts executions `FIRE_AND_FORGET`, so N
  submissions against one space become N concurrent waiters polling one key with no queue discipline.
  Ordering would need a real queue; the browser's own busy gate already makes this rare from one
  session.

**A cross-space copy or move takes TWO locks, in digest-sorted order, or neither.** Keying only on
the source leaves the destination unserialized — A moves `alice/reports/` into `marketing/` while B
deletes `marketing/reports/`, different source digests, both run. Sorted order is what makes two
locks safe: unordered acquisition deadlocks when two requests cross in opposite directions. The verb
releases the first if it cannot claim the second, so a waiter never holds a lock across the `Wait`
and the give-up path has nothing left to free.

**One case can still strand a lock and is accepted rather than solved:** a fault inside the acquire
verb between the two claims returns nothing, so no tag reaches the state and the first lock is held
with nobody able to name it. The staleness steal is the recovery, and it is the same universal
recovery the top-level timeout needs — splitting the claims into two states would double the loop
and reintroduce the partial hold the design avoids.

### An item copied into itself is refused PER ITEM, where a containment breach fails the request (SPEC-187)

The plane's front door has two kinds of refusal and the split is not stylistic.

**Whole-request, raised:** a key outside the actor's own root, a dot segment, a `targetName` that is
not one usable segment, and two selected items whose derived destinations collide. These are
statements about the REQUEST — there is no sensible partial execution of one that names a key outside
the actor's space, and where two items collide neither of them is the wrong one, so there is no item
to fail and no way to choose.

**Per item, returned as an outcome record:** a protected folder, a same-key no-op, and an item whose
destination is inside its own subtree. The browser has always carried on with the rest — a select-all
delete at a space root deletes what it may and reports the folders it may not — and a whole-request
refusal would turn that into deleting nothing.

The into-itself case is the one that could have gone either way. It is per item because it is a
statement about ONE item's own pairing rather than about the request's legitimacy, which makes it a
**user-visible divergence from today's browser**, where it refuses the whole gesture.

**A collision is between two DIFFERENT items, and an exact repeat is not one.** The identity is
`(kind, key)`, never the derived key alone: the same item named twice lands on itself, which is
idempotent, while two different items landing on one key lose a file. Collapsing on the derived key
alone refuses a request that does exactly what it says — and it is the same rule SPEC-165 recorded
for file-send, arrived at from the other direction.

**The protected-location rules run FIRST, before either pairing rule.** An item the user may not
touch should be told so rather than told that nothing happened: `move alice/archive/ → alice/`
derives its own key, so a pairing-first order answers "no-op" to a request the plane actually
refuses, and two protected folders answer the same request differently depending on which list they
are on.

**The space root is refused as an item, and it is the third way to select a protected folder.** Every
protected rule matches the named folder or something below it; none looks UP. So one item of
`alice/` passes all of them while naming a subtree containing `athenaresults/`, `user_settings/`,
`archive/` and every marker — a request this plane's own IAM refuses part-way through, which is the
mismatch those rules exist to prevent. The browser cannot express it, so refusing costs nothing.

### The source deletion removes only CONFIRMED-COPIED keys, never a prefix listing (SPEC-187, diverging from SPEC-169)

Recorded here because SPEC-188 and SPEC-189 must honour it and neither is written yet.

SPEC-169's archive rollback lists the source prefix precisely so it catches objects a batch copied
before it died. **Here the same technique loses data.** An object written into the source folder
between expansion and commit — by an upload, a single-file operation, or another plane, none of which
take this plane's lock — was never copied, and a prefix-listing delete would remove it silently and
unrecoverably, with versioning off.

The accepted cost is an **orphan**: it survives, stranded in a folder the user believes moved, which
is visible and recoverable where the alternative is neither.

**It forbids LISTING THE SOURCE PREFIX at deletion time. It does not forbid re-reading the PLAN**,
which is how the keys actually arrive — the transfer engine reports counts and never keys, because a
failed-key list is the unbounded term that breaches the state limit on the Map.

**And the gate is per ITEM, not one boolean over the run.** SPEC-169's is all-or-nothing because
before per-item outcomes the planned set and the confirmed-copied set were identical. They are not
here: a skipped item is planned and not copied, so deleting plan keys would remove the user's source
file while the destination still holds the colliding object that displaced it — a direct,
unrecoverable substitution.

### The collision unit is the derived destination KEY, and that is what preserves merging (SPEC-188)

The destination guard asks, per selected item, whether anything is already where that item's objects
would land. **What it compares is each derived destination KEY, never the destination subtree**, and
the difference is a capability rather than a nuance.

That is what the browser does today: `moveFolder` and `copyFolder` intersect `sourceKeys.map(destKeyFor)`
against the listed destination. So copying `reports/` into `out/` while `out/reports/notes.txt`
already exists — where no source key maps onto that key — is legal today and stays legal. "The
destination subtree holds anything" is a stricter test that reads as tidier and would silently
remove **merging into an existing folder**, which is how people actually use a file browser.

**It heads every key rather than listing the destination, and a listing structurally cannot serve
the check.** `CommonPrefixes` carries no `LastModified`, `Size` or keys, so a delimited listing
cannot answer the overwrite predicate below the first level; and `ListObjectsV2` never returns a
per-key 403 — an `AccessDenied` fails the whole listing. HEADs are also bounded by **our own**
`FILE_OPS_MAX_OBJECTS` rather than by the size of someone else's destination folder.

**A 403 counts as OCCUPIED, in both modes**, inherited from the archive guard for the same reason: a
key this role cannot head is one it must not overwrite, and under `overwrite` it yields no
`LastModified`, so "an existing object" must never be read as "the ones we could head". A head that
faults for any other reason refuses its item; it never falls through to clear.

**`refuse` short-circuits and `overwrite` cannot**, and the asymmetry is stated because a shared
early exit would silently make `overwrite` sample-dependent — a newer object *anywhere* in an item's
key set refuses it, so the whole set has to be asked about. The corollary is that the ordinary case
costs a full sweep either way: a clean item is always `objectCount` heads, which is what the verb's
timeout is sized for.

**The overwrite predicate reads `submittedAt` from the PLAN with no fallback to the state**, and an
unusable instant refuses the request rather than degrading the mode. A fallback would reintroduce
exactly the substitution `plan_superseded` exists to catch, and a silent degrade would apply refuse
semantics — *with* the short-circuit that mode must never take — to a request the user confirmed as
an overwrite.

**The conflict sample is bounded by the STATE, not by taste.** Every conflicted item carries its
sample from the guard to the notification, and Step Functions caps a state at 256 KB. Measured at the
selection byte cap with every item conflicted, one full-length path per item is all that fits — so a
sampled path is shortened from the middle to `FILE_OPS_SAMPLE_PATH_CHARS`, which keeps the basename,
and three of them fit with room over. An ordinary path is untouched.

### A conflict is one item's outcome, and the list is created once and carried forward (SPEC-188)

Three verbs decide per-item outcomes — validate-authorize (the protected locations, the no-ops and
the into-itself refusals), inspect-source (`source_missing`, `source_empty`, and every expanded item
provisionally `cleared`) and check-destinations (`cleared` → `conflict`). **None of them creates the
list. Each takes it as input and returns all of it.**

The rule exists because of how a verb's result reaches the state: it REPLACES the path it is merged
into rather than appending to it. Wired the obvious way, the destination guard would silently drop
the two producers before it — and those are exactly the outcomes the per-item model exists to carry.
`focommon.outcomes.carry_forward` is the one function that merges, and it replaces an entry **in
place**, because a person reads this list and a revised verdict must not reorder it.

**An item an earlier verb decided is never expanded**, which is a rule rather than an optimisation. A
same-key no-op's destination subtree IS its source subtree, so expanding it would have the guard
report every one of its own objects as a collision and flip a reported success into a refusal. It
also keeps the same-key comparison — a security-adjacent rule — in exactly one verb.

**Whole-request refusals still raise, and the split is the one SPEC-187 set.** Two items where one
contains the other, and every cap, fail the request; a missing file and an item that resolves to
nothing fail alone. **The overlap check is asked of the WHOLE selection, before the decided items are
dropped**, because an item can be decided and still be the container: a move of `saved_queries/` and
`saved_queries/2026/` has the parent refused as protected and the child untouched by any rule, so a
check over the survivors would move the subtree out of the folder whose own refusal exists to keep it
there.

**Only a proven absence is `source_missing`.** A 403 or a KMS refusal is a statement about what could
be READ; reporting it as a per-item miss drops the file from the plan silently, moves everything
else, and names the user a cause that is false. Those fail the whole request.

**The plan is the object that knows what the run will touch, and it is passed by pointer.** At the
object cap the list is tens of megabytes against a 256 KB payload limit, so it is written to
`{admin_bucket}/file-ops/{requestId}/plan.json` and only the key and the counts ride. It carries
`requestId`, `submittedAt`, `onConflict` and the **execution ARN**; the last is what makes the
request-id reuse guard retry-safe. Every task on this machine carries a three-attempt `Retry`, so a
transient fault after the write is ordinary: a guard refusing any occupied prefix — the archive's
shape — would refuse the request it had itself just planned and tell the user their id had been used
before. Comparing the execution refuses the case the check exists for and admits the one the machine
creates.

**The ETag rides on every plan object because the listing already carried it.** `ListObjectsV2`
returns it in `Contents` at zero marginal cost, and this is the only verb that lists the source — so
it is the only cheap producer of the field a later conditional delete turns on. Getting it any other
way is a `HeadObject` per object, which is a round trip per object where a listing is one per
thousand. `cpcommon.s3_listing` gained `list_data_records` for it, and `list_data_objects` is now a
projection of that function, so there is still exactly one paginator in the fleet.

### The commit gate is per ITEM, so the graph proves less than SPEC-169's did (SPEC-189)

SPEC-169's gate is one boolean over the whole run and its guarantee is **graph-level**: the rollback
arm cannot *reach* `DeleteSource`. A per-item plane produces runs that are simultaneously committing
and non-committing, and **Step Functions has no per-item `Choice` over a list** — so that guarantee
is not available here. Rather than inherit a sentence that no longer holds, this plane asserts the
weaker property honestly and buys the rest at two other layers:

- **the walk asserts exactly one thing** — an empty `deletable` set cannot reach `DeleteSource` — and
  says in its own docstring that it does **not** assert the per-item property. A walk claiming more
  than it proves is worse than one claiming less;
- **the per-item half is a collector unit test with a named mutation** (an item with one failed
  object must not appear in `deletable`), plus **`delete-source`'s subset assertion at the boto
  boundary** — checked against the keys actually handed to `DeleteObjects`, never over the filter's
  own output, which would re-check the filter with the filter.

**Both gates enumerate their positive cases and default to not deleting.** `NeedsSourceDeletion`
names `move` and `delete` explicitly; a state whose `operation` was lost or mistyped reaches
`FinaliseOutcomes`. The first draft had the deleting arm as the `Default` — fail-open, and the
opposite of every neighbouring gate on this fleet.

**The skip branch is recognised positively.** A `delete` reaches the collector with the Map skipped
and every still-`cleared` item deletable. Implemented as the natural negative — *no `mapRun`,
therefore the skip branch* — a `move` arriving without an export would mark every cleared item
deletable and the next state would delete a source nothing had copied.

### The source deletion: what it removes, and what it is conditional on (SPEC-189)

**It deletes the plan's keys, never a prefix listing** (SPEC-187 Premise 1). This plane's lock
serialises its own executions and nothing else — not uploads, not create-folder, not the six other
control planes — so an object written into a source folder between the expansion and the commit was
never copied, and a prefix delete would remove it silently and unrecoverably with versioning off.
The accepted cost is an **orphan**, which is visible and recoverable where the alternative is
neither. A plan **re-read** is not a prefix listing, and per-item gating makes "the plan keys of a
fully-succeeded item" and "the keys confirmed copied" the same set.

**A conditional delete is NOT replay-safe the way an unconditional one is.** `arcommon.delete` rests
its whole `Retry` story on S3 reporting an already-absent key as deleted — true only *without* a
condition. With one, a key the previous attempt removed comes back on the **error** side, so a verb
that deleted five batches of twenty, hit a throttle and retried would report every one of those five
as a failure and the user would be told a completed move half-failed. "Gone" is therefore success and
only a genuine mismatch is `source_changed`.

**409 is handled distinctly from 412, diverging from `cpcommon.cas.is_precondition` on purpose.**
That predicate collapses them and is right to: a compare-and-set retries on either. A conditional
delete is not a CAS — a **412** means the object changed, terminal for that item because its
destination copy now holds stale bytes; a **409** means a concurrent delete or put won the race,
which is retryable. One module answering "did my write lose?" and another answering "why did my
delete not happen?" are different questions, and a shared helper would have to give one answer to
both.

**The HEAD-compare path is ACTIVE and the conditional one ships behind a flag.** Reading
`ObjectIdentifier`'s members off the live service model proves botocore will *serialize* the ETag; it
does not prove S3 *enforces* it, and a serialized-but-ignored condition deletes a changed source
silently. `CONDITIONAL_DELETE_ENABLED` flips only once a live probe shows a wrong-ETag delete is
genuinely refused on these buckets.

**A `delete` operation's deletions are unconditional, and conditionality is the CALLER's explicit
flag.** A move's condition protects bytes that were just copied; a delete has no copy, and an object
modified since the expansion is still one the user asked to remove. Inferring the flag from whether
ETags happened to be supplied made a delete conditional on an empty string, which mismatched every
object and reported `source_changed` having removed nothing — found by a fixture, not by reasoning.

**`assert_item_deletable` is per item and runs BEFORE the transfer.** A whole-list refusal would be
the whole-request reversion this arc's model forbids — and on a `move` it runs after the copy, so it
would leave every item copied and nothing deleted: a full duplicate of the entire selection. The
placement matters as much as the scope: a personal folder holding a **nested** `athenaresults/`
passes the front door (the browser's rule is root-anchored in a personal space) and expands into the
plan, so a post-copy-only refusal would leave it fully duplicated and undeletable — a state the user
cannot resolve through this plane at all.

**It mirrors the IAM POLICY, not the browser rule.** IAM cannot express "at the space root only": a
`Resource` wildcard matches `/`, and this role carries no principal tag to pin one segment the way
the portal role's `${aws:PrincipalTag/username}` does. The strict side is taken — any-depth on both
buckets — and the divergence is handled per item rather than hidden.

## Control planes — one pattern, and the traps are shared

### Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)

The rule the table-share plane arrived at over three specs, stated once: **anything on the Step Functions state whose size a user controls lives in the admin bucket and rides as a key.** The object list went first (PR #256, at 95% of the 256 KB payload), the transfer manifest was born that way (SPEC-160), and SPEC-161 finishes it with the **cloned table definition** — `{admin_bucket}/table-share/{hash}/definition.json`, written by `inspect-source`, fetched by `create-table`. `tscommon.copy_plan` owns all three key layouts, so the request digest has one home.

**A cap is not an alternative to a pointer, and this is the case that shows why.** The definition was bounded inline by `SHARE_MAX_DEFINITION_BYTES` at 32 KiB, and that number was doing two incompatible jobs: keeping the Map's state safe, and deciding how wide a table a user may share. A 100-column table with column comments serialises to roughly 32 KiB — an ordinary thing to want to share, sitting exactly on the boundary. Measured: with the definition inline at cap, the guard Map's peak state reaches **~55%** of the limit; with the pointer it is ~29%. The cap could protect the payload or serve the user, not both. **`test_the_whole_map_state_stays_under_the_payload_limit` now adds an at-cap definition back to the modelled state and asserts it fails the safety bar**, so the pointer is demonstrated to be load-bearing rather than assumed to be tidy.

`SHARE_MAX_DEFINITION_BYTES` survives at **64 KiB** as an object-size sanity check, and **what sizes it is now Athena, not Step Functions**: the definition renders into one `CREATE EXTERNAL TABLE`, and Athena's query-string quota is **262,144 bytes and not adjustable**. The rendered statement can be **twice** the serialised JSON — `ddl.literal` backslash-escapes, so a `'` costs one byte in the JSON and two in the DDL — and *where* those quotes sit decides the ratio: a table property or SerDe parameter carries ~9 bytes of JSON overhead and renders at nearly the full 2x, where a column comment carries ~40 and reaches only ~1.7x. At 128 KiB the property-shaped worst case measured **99.98%** of the quota; at 64 KiB it is 50%. Do not re-read it as a state bound, and do not raise it on the strength of a comment-shaped measurement.

**Three keys, two disciplines, and the split is about what the content depends on.** The plan and the definition are **pure functions of the request** — the digest covers the source database and table, so two overlapping executions write byte-identical content and either object is correct for either run. The manifest is **execution-unique**, because its lines depend on which recipients the guard Map accepted, which is time- and destination-dependent (SPEC-160's entry has the full argument). Do not "make them consistent" by giving the definition an execution segment; it would multiply objects under a lifecycle rule for no gain.

**An unreadable definition fails THAT RECIPIENT, never the request, and never renders anyway.** `definition_unreadable` is terminal for the finish Map's item, and the reason the load refuses an object with no columns rather than passing it on is specific: an empty column list renders a `CREATE EXTERNAL TABLE` that **Athena accepts**, over the recipient's freshly-copied data — a table that reports success and returns nothing.

**No IAM changed.** `CopyPlanReadWrite` already grants `PutObject`/`GetObject` on `${admin_bucket_arn}/table-share/*`, which is the whole benefit of one prefix owning every artifact — and the same property is why FR-004 was discharged by adding **no lifecycle rule**. Detail: `spec-delivery/SPEC-161`.

### Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)

A Standard workflow with no `TimeoutSeconds` runs to Step Functions' default of **one year**. That was harmless while the copy was one Lambda bounded by its own 900-second timeout; once SPEC-160 made it a Distributed Map and SPEC-161 raised the byte cap to 1 TiB, "wedged" became a state a run could sit in indefinitely.

**It is a TOP-LEVEL ASL field** — beside `StartAt`, not an argument to `aws_sfn_state_machine` and not a task field (SPEC-157 settled the same distinction for the table-builder's lock). On a Task it would bound one step, which is not what a wedged *run* needs.

**And a top-level timeout CANNOT reach `NotifyFailure`, which is the trap this entry exists to record.** The state sits in the machine looking exactly like it would. It does not: AWS documents that *"Step Functions catchers are available for Task, Parallel and Map states, but not for top-level state machine execution failures"*, and the remedy it names is *"listen for `TIMED_OUT` events from Standard workflows with an EventBridge bus"*. A top-level expiry terminates the execution outright — no state runs, no `Catch` fires. **A `TimeoutSeconds` shipped alone would therefore have bounded the run and made the sender's silence permanent instead of merely long**, which is worse than it sounds: SPEC-152's guarantee would read as satisfied by a state that could never be reached.

So the field ships **with an EventBridge rule** (`stepfunction.tf`) on `Step Functions Execution Status Change`, matching **`TIMED_OUT` only** and invoking the same `notify-failure` verb through a second door. AWS classifies Step Functions execution events as **best-effort delivery**, so this closes the hole rather than sealing it — a dropped event means the old silence for that one run. That is accepted: the alternative is polling `ListExecutions`, which is a scheduled sweep and a second moving part for a failure mode measured in runs per year. `TIMED_OUT` only is load-bearing: every other whole-request failure already reaches the verb through a `Catch` and ends at `Fail`, whose status is `FAILED`, so matching both would send a second notification for every caught failure. The two doors are disjoint by construction, not by a suppression rule.

**The timeout door recovers the sender from the token, and expiry is deliberately not enforced.** The execution input is what the Pipe forwarded — the raw SQS batch — so the actor is the verified `cognito:username` claim inside the body's ID token, never the body's own assertion. By construction that token is expired: the timeout fires hours after it was minted. The relaxation is the DLQ drain's, taken through the same separately-named entry point (`verified_username_ignoring_expiry`) and safe for the same reason — this path **grants nothing**, it only addresses a message. An input EventBridge omitted (it caps an event at 256 KB) or a token that will not verify is a **logged no-op**, never a guessed inbox. Its wording is its own reason code, `share_timed_out`, rather than the generic failure sentence: a timeout is the one whole-request failure that can leave a recipient holding **part** of a dataset — the copy may have run and the create may not — so "try again" alone would be wrong advice.

**Sized from `SHARE_MAX_TRANSFER_BYTES`, NOT from the source cap — and the difference is a factor of `SHARE_MAX_RECIPIENTS`.** The manifest carries one item per (recipient, object) pair and every item is a full copy, so the Map moves the source **once per recipient**. Sized against the 1 TiB source cap alone, this number was short by 50×: 50 recipients × 1 TiB is 50 TiB, which needs 3.8 hours even at the conservative rate. That is the omission `SHARE_MAX_TRANSFER_BYTES` (3 TiB) closes. **And the rate it is divided by is a makespan, not an aggregate bandwidth** — a fourth review round's correction, and the same class of error a fourth time: `copy_batch` gives one whole object to one worker and `copy_one` part-copies serially, so a batch dominated by one large object runs at ONE stream while seven idle. The pessimistic denominator is `MAP_MAX_CONCURRENCY × rate` (500 MB/s), not `× COPY_CONCURRENCY ×` it (4 GB/s) — under which 16 TiB read as 4,400 s when the truth was 35,000. At 500 MB/s, 3 TiB is ~6,600 s, and with the finish Map (3,000 s) and the serial verbs (~720 s) the worst run is ~10,300 s inside **10,800 s (3 h)**. The margin is bought against the sender's silence, so a longer timeout is a slower failure signal rather than free safety; the cap moves before the timeout does. **A test computes it**, because the hard-coded floor that stood here first is exactly what let the mismatch survive two review rounds.

**The retention obligation inverts once a run can last hours.** Nothing new needed expiring: manifest, definition and Map Run export all sit under `table-share/`, which `expire-table-share-copy-plans` already covers. The risk was the opposite — the rule expiring a *live* run's manifest underneath it. `admin_results_retention_days` (30) clears the run ceiling by **240×**, computed by a test from both files, and **no rule and no rule id were added**.

### Data-quality outcome notifications (SPEC-114)

The notification **is** the completion channel — the browser never waits and the reports folder is hidden from the file browser, so a success message without a **link to `/data-quality/{space}/{requestId}`** would leave the report unreachable. The link builder mirrors SPEC-113's resolution precedence and returns **nothing** where the view would resolve the wrong space (a shared space named like the actor, a personal space that isn't theirs) — no link beats a permanent not-found. **Every figure this arc produces is approximate**, so a flat "some figures are estimates" rides every success message and the real warning is reserved for `hasIncompleteFigures`, the flag that varies. Failure covers three layers: `@notifies_on_failure` on every verb, the `NotifyFailure` state for what no verb can catch (import/SFN-level errors, decoded in Python — never in ASL), and **SPEC-126** for what never starts an execution at all. **One dedup token per outcome, not per verb** (`{requestId}:failure` / `:completed`): `NotifyFailure` runs after the execution has left the failing verb and cannot know which one raised, so a per-verb token would send two messages for one failure; the collapse relies on SQS FIFO's 5-minute window. `TerminalError` gained an optional **`tokens`** mapping — the user-facing inverse of `detail`, which stays raw and operator-only. **FR-005's CloudWatch alarms were removed, not deferred** (user decision): an alarm with no target, on one arc of five, told the user nothing. Detail: `spec-delivery/SPEC-114`.

### Control-plane DLQ drain → user notification (SPEC-126)

Replaces SPEC-114 FR-005. Every control plane dead-letters a request it cannot process, and until this shipped the user was told **nothing at all** — no verb ran, so no `@notifies_on_failure` fired; no execution started, so no `NotifyFailure` state was reached. **One shared drain Lambda** (`lambdas/control-plane-dlq-drain/`, `infra/modules/control-plane-dlq-drain/`) sits on all four request DLQs (data-quality, table-builder, table-share, shared-spaces) and turns each dead-lettered message into one notification. Four things are load-bearing: (1) the recipient is the **verified `cognito:username` from the token inside the body** — a body-asserted `username` would let anyone route a notification to anyone; (2) **expiry is not enforced** on this path (`cpcommon.auth.verified_username_ignoring_expiry`, a **separately named** entry point, never a flag on the function every authorization path calls) because a dead-lettered message is old by construction while an ID token lives an hour — signature/issuer/audience still are, and this path **grants nothing**; (3) **no value from the untrusted body reaches the message** — every other producer interpolates what a verb already authorized, nothing here has authorized anything, and echoing an attacker-supplied path into a victim's inbox would make notifications a text-injection channel; (4) every per-message path is **total** — a throw means redelivery, and a message that always throws loops until retention expires, burning invocations on a failure nobody is watching, which is the invisibility this exists to end. The dead-lettered body is logged (**token redacted**) before the drain consumes it, trading the DLQ's 14-day copy for the log group's. The **notifications DLQ is deliberately undrained** and is the one hole this cannot close — the drain's only delivery channel is the queue that DLQ implies is broken; the honest answer there is operator-facing. **No redrive, no replay, no CloudWatch alarms** (an alarm with no target told the user nothing — the user decision that killed SPEC-114 FR-005). **Follow-up (2026-07-22): the four SQS event-source mappings became one EventBridge scheduled sweep** (`rate(10 minutes)`) — the mappings idle-long-polled four almost-always-empty DLQs around the clock, and that was the bulk of the account's SQS request volume (it was tripping the 1M/month free tier). The handler now polls all four DLQs itself (`DLQ_ARNS`, the same ARNs as an env JSON list) and **deletes every message it reads whether or not it could notify**, so "total by construction" now means *never redeliver* rather than *safe to be redelivered* — the redelivery-loop hazard in (4) is moot because nothing redelivers (the `_guarded_notify` belt stays, so one bad message can't abort the sweep). A resource-based `lambda:AddPermission` lets the rule invoke the function, so **no invoke role** is needed (unlike EventBridge Scheduler); the execution role is unchanged (it already held the four DLQ read/delete grants the mappings polled with). Cost fell from ~10⁵–10⁶ idle receives/month to a few thousand; the price is that a dead-lettered request surfaces within one interval (~10 min) rather than seconds, immaterial for a queue nothing watches live. Detail: `spec-delivery/SPEC-126`.

### Structured-logging pipe (SPEC-127→129)

The pipe every control-plane function logs through; it carried **boundaries only** until SPEC-130 added the narrative half (next entry). `log-foundry` (pinned **exactly**, core not `[aws]`) ships in the `cpcommon` layer. `LOGS_QUEUE_URL` is **optional** (`environ.get`, never `_require`) so a function missing it logs to stdout instead of crashing a whole plane at cold start. The logs queue is **FIFO** with `message_group_id` = the **service** (SPEC-129; it was standard only until `log-foundry` 0.5.0 could set `MessageGroupId`), with **no** content-based dedup (the library mints UUID dedup ids), and it is **swept** on a 10-min schedule, never long-polled (#270/#271). `service` = the **control plane**, and it is untrusted input on an S3 key: anything failing `^[a-z][a-z0-9-]{2,62}$` goes to `logs/_unrouted/`. Layout is `logs/service={s}/year=/month=/day=/data.jsonl` — **one appended object per service-day**, so every write is an **ETag-CAS read-modify-write** (a failed read must never overwrite a day) and the sweep role can **read** `logs/*`, reversing SPEC-127 FR-006. Delivery is put-then-delete (at-least-once; duplicates collapse on `log_id`). Partitions come from the **event's** timestamp. `logs/` is retained **forever**. `@traced` goes **outermost, above `@notifies_on_failure`**, or failed invocations close their span as `ok`. One run = **nine traces**, joined on `fields.request_id`.

### Structured-logging narrative primitives & the one-door rule (SPEC-130/131)

The pipe SPEC-127/128/129 built carries **boundaries only** (entry above), and SPEC-130 opens the door to the narrative half. `cpcommon.observability` gains `info`/`warning`/`error` and `step(name)` — the module's full surface is `init`/`flush`/`traced`/`step`/`stamp`/`info`/`warning`/`error` — and **nothing outside that module may import `log_foundry`**: an emitter sits in the middle of business logic where an exception is a real failure path, so the never-raise discipline needs one door rather than thirty-four. `step` is a **thin** alias for `lf.trace` and must stay one: the library decorator is non-swallowing, and `@traced` sits **outermost above `@notifies_on_failure`**, so a step that caught anything would cost the user their failure notification. Messages are **literals**, everything variable is a field (an f-string message mints a distinct string per run and can be neither counted nor filtered). The narrative **never reaches the console**: `echo=` is prohibited repo-wide and grep-tested, dropped-and-warned when passed as a field (with `**fields` it is otherwise a silent no-op emitting a field named `echo`); the one named exposure is `init`'s `StdoutSink` fallback when `LOGS_QUEUE_URL` is unset, which **stays** because it is the cold-start safety property the module is shaped around (PR #196) and is bounded by the `logging.getLogger()` calls already putting the same keys in the same log group.

Two identity defects fixed at the same time, because instrumenting on top of them would have multiplied the damage: `traced` now passes **`name=verb`** (without it `log-foundry` falls back to `fn.__qualname__` and every root span in the fleet read `function: "handler"`) — a **discontinuity in a store retained forever, accepted without migration** since rewriting appended NDJSON would risk a day of logs to save a `WHERE` clause, with `fields.verb` populated on both sides so a query spans the cutover; and **`verb` moved from a span default to baggage** (set after `_reset_baggage`, which clears the whole mapping), because a span default reaches that span's own events and nothing nested — the first `step` child would have carried `request_id` but not the verb that produced it. Consumers: SPEC-131 (sweep), 132 (data-quality), 133 (DLQ drain), 134→137 (the rest of the fleet).

**SPEC-131 added an eighth name, `stamp(**fields)`** (trace baggage), because the sweep needed an invocation-scoped join key on the boundary spans and the only alternative was importing `log_foundry` at a call site — the one-door rule survives by widening the door, not by excepting it; `_stamp_verb` and `_stamp_request_id` now delegate to it. **SPEC-131's own bound is structural:** the sweep emits into the queue it drains, so its event count is O(1) in messages and O(G) in day-groups (measured `6+4G`, 4 on an empty sweep) — a per-message emitter would give that queue a floor it could never get below, and the guard is a test that sweeps 20 then 200 messages over the same groups and demands an identical count. Its CloudWatch calls **stay alongside** the events, uniquely for that function: the sink is SQS-only, so a sweep that cannot write to S3 cannot report through the structured store that it could not write to S3. Detail: `spec-delivery/SPEC-130`, `spec-delivery/SPEC-131`.

### The field rule — what may be logged (SPEC-130)

**The line is drawn at file contents — not at user-derived data** (user decision, 2026-07-23): `logs/` lives in the admin bucket and is read by administrators, and that destination is what makes user-derived *metadata* the right thing to log — file names, S3 keys, prefixes, **usernames** (already the S3 prefix, the principal tag and the Glue DB name, SPEC-033), database/table/**column names**, space names, counts and durations are all permitted and encouraged, because an operator debugging a failed run needs to reach the object. **Absolutely never: data from inside a file** — a cell value, a sampled row, a result set, a decoded byte range — because it can be PII, it is never needed to debug a control plane, and `logs/` is retained forever (column *names* are schema and are in; column *values* are contents and are out). **Never regardless of provenance: tokens, credentials, email addresses** — a bearer credential is not metadata, and an email is the only personal contact detail that would exist in a forever-retained prefix. There is deliberately **no runtime redaction filter** and the module docstring says so: the rule turns on *provenance*, which no filter over a field name or value shape can see, and a filter that looked like enforcement would be worse than none because it would be trusted — enforcement is review plus per-call-site criteria.

**The no-file-contents rule is about FIELDS, and `error.stack` is an ACCEPTED exemption (user decision, 2026-07-23):** `log-foundry` attaches `traceback.format_exception` to every failed span unconditionally and it walks the `__cause__` chain, so a quoted cell (a polars parse error naming the value it could not convert) reaches `error.stack` regardless — suppressing `detail` does not help (see the per-plane entry below for the `detail` audit) and neither does fixing the raise site (`raise … from exc` is what puts it there). Rather than close it (an upstream `capture_stack=False`, or a strip in the sweep), the decision is to **accept it**: `logs/` is admin-only, and a stack is diagnostic metadata an admin debugging a failed run needs, so the absolute rule binds a **field a verb chooses to emit** — not an automatic traceback. **Do not read a stack trace as licence to relax the field rule.** The characterisation test (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`) is kept as a **tripwire, not deleted**: if it starts *failing*, `log-foundry` began stripping stacks and this decision should be revisited in the open.

**The `error.stack` exemption covers FILE CONTENTS and not CREDENTIALS, and the API scrubs rather than exempts (SPEC-195, 2026-08-27):** the exemption above was reasoned about a polars parse error naming a cell it could not convert — diagnostic metadata an admin debugging a failed run needs, in an admin-only store. That reasoning was never applied to a bearer credential, and the API handles one on every request: a user's ID token is a credential for as long as it lives, and an admin-only store is not a safe place for a live one. Two facts were **measured rather than inherited**, and both narrow the problem. `log-foundry` 0.6.0 exposes **no way to turn stack capture off** — `config.py` offers only `max_stack_bytes`, whose validator rejects any value below 1 — so exemption is unavailable and scrubbing at the boundary is the only answer. And the exposure is **not automatic**: `format_exception` renders each frame's source line, not its locals, and PyJWT's own messages carry no token material. The live route is this repo's own code interpolating the token, or the gateway event whose headers hold it, into an exception message or a log field — so the verifier raises a **fixed literal reason code** and chains the provider exception as `__cause__`, which the API never reads. `max_stack_bytes` is set explicitly at the API and is a **ceiling, not a control**: a reader must not mistake it for the scrub. If a later `log-foundry` offers an opt-out, this is revisited — the tests are not deleted.

**SPEC-137 put EMAIL on the never list** (user decision, 2026-07-23) in the shared module docstring: a username is not sensitive here (it IS the prefix, the tag and the DB name) but an address appears nowhere else, carries no operational meaning, and would be the only personal contact detail in a forever-retained prefix. The hazard is mechanical — a Cognito trigger event carries `request.userAttributes.email`, so **never log a raw event, an attributes map, or any dict you did not build field by field**; `pre-signup` logs the DOMAIN, which is what the rule turns on and is shared by every user of that provider.

### Per-plane instrumentation rules (SPEC-132→137)

**SPEC-132** spent the primitives on all nine data-quality verbs and settled two things the remaining planes inherit. **The `detail` audit is a deliverable, not a reassurance:** every `TerminalError` raise site is read, and any whose `detail` interpolates *parsed file content* logs the reason token and the exception type only — in data-quality that is `inspect-source`'s `_probe_columns` catch-all, whose detail carries a polars parse error that **quotes the offending cell**, and the suppression is unconditional for that verb rather than a denylist of reasons the next reason gets added without. And **a contents-shaped field NAME is banned even when the value is a count** — the tripwire caught `rows=` in `assemble-report` on its first run, so a row count is `row_count`; a field whose safety needs an argument is one whose name should say so instead. Failures are narrated **once per verb**, not per raise site.

**SPEC-133** took it to `control-plane-dlq-drain` (`service="dlq-drain"` — not a control plane, since it spans all four and is nobody's verb) and settled two rules the rollout inherits. **`request_id` is a FIELD wherever one invocation handles many requests, never baggage:** `_reset_baggage()` runs once per invocation, so on a function draining up to 400 messages, baggage would leak one request's id onto the next — the fabricated correlation key SPEC-128 FR-002 forbids. **And one event per item is right or wrong depending on which queue you emit INTO:** the sweep emits into the queue it drains, so per-message events give that queue an undrainable floor; the drain emits to the logs queue and drains the request DLQs, so per-message is correct there. The dead-lettered body is a **permanent forensic record** — redacted (every known token field), size-capped, and ONE serialized field, never re-parsed into fields or a body could shadow `request_id`/`verb`/`service`.

**SPEC-134** promoted the per-plane coverage guard to a **fleet-wide harness** in `control-plane-common`: registering a plane is one `Plane()` descriptor (its glob, service name, expected verb count as a LITERAL so a short enumeration fails rather than passing vacuously, and its decorator expectation), and a verb module is found by **defining a top-level `handler`** rather than by any filename convention. It also settled that **the decorator rule is per-plane and DECLARED**: shared-space verbs notify from inside the handler, so `@traced` is asserted to be their ONLY decorator — adding `notifies_on_failure` there later fails until someone establishes the ordering. And **per-item events are permitted where the bound is STRUCTURAL**: the roster fan-out emits per member because membership is capped at ten Cognito slots, which is the same rule as SPEC-131/133, not an exception to it.

**SPEC-135→137 finished the fleet.** 135 logs Athena's `StateChangeReason` **verbatim** alongside the stable token — that raw text is what would have named the missing `CREATE_TABLE` grant, and a token cannot carry a diagnosis — and moved the DDL poll's transition-only narrative into **`cpcommon.athena`**, since the loop is shared. 137's email decision lives in the field-rule entry above; 137 also verified empirically that **`cpcommon.observability` imports and emits with ZERO env vars** (`cpcommon/__init__.py` has no imports, `clients` lazy-imports boto3), which is what makes the layer safe to attach to functions that lack the six `config._require` variables — one `from cpcommon import config` added to `__init__.py` would arm PR #196's bomb for them. Detail: `spec-delivery/SPEC-132`, `spec-delivery/SPEC-133`.

### No ASL state decodes an error Cause (PR #252, control-plane-wide)

`States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **neither retriable nor catchable anywhere** — not even by a `Catch` on the same state. The `ParseError` `Pass` states that did this killed executions *before* the recorded-failure/notify states on 3 of 4 real error shapes (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — verified live with `TestState`). Terminal states now carry the **raw `$.error` `{Error, Cause}`**; `cpcommon.errors.failure_reason` decodes it in Python. Enforced by `lambdas/control-plane-common/test_state_machines_cpcommon.py`. Related trap: a `Pass` state's JSONPath hard-fails on an **absent key** (a null *value* is fine), so anything a terminal `Pass` names must be seeded on every path — now **enforced by a test** (SPEC-114): every `Pass` reachable from a failure seed may read only keys that seed supplies. It has caught this arc twice (`$.location`, SPEC-112; `$.reportKey`, SPEC-114).

### Notifications (SPEC-058→061)

Per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}` — plus an **optional `link`**, SPEC-113 FR-008: an in-app path the message renders as, gated at render by `isSafeInAppPath` so it can never become an open redirect; absent = plain text, which is every pre-113 producer). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues (`sqs:SendMessage`). Anti-spoofing = user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim (`create` = trusted-producer-only — **enforced since SPEC-206** by the writer refusing a `create` whose SQS-stamped `SenderId` names the portal role; the grant itself is unconditioned and cannot be otherwise, since no SQS condition key reaches a message body). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; **059 browser data layer done** — `features/notifications/` read service + `useNotifications` + prefetch; **060 UI done** — header `NotificationsBell` link + `/notifications` page (10/page, mark-read/all, optimistic + Toast); **061 done** — the 062 verb Lambdas emit `create` inline via `notify.emit_notification` (orchestrator role gains `sqs:SendMessage` to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` env), best-effort.)

### Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)

All four control planes now carry a `NotifyFailure` state ahead of their terminal `Fail`, reached on
every failure path, invoking a thin per-plane verb that decodes the raw `{Error, Cause}` with
`cpcommon.errors.failure_reason` and emits through the plane's own notifier.

**The gap this closes was named by the repo's own design and closed in one of four planes.**
`@notifies_on_failure` needs handler code to run. SPEC-126's DLQ drain covers requests that never
started an execution. Neither covers the middle: an execution that started and then failed **before or
outside** any verb's Python — a `States.Timeout`, a `States.DataLimitExceeded`, a task-level throttle,
a Lambda that fails at **import**. In that window the user got no notification, no DLQ message, and a
request that never completed — against SPEC-114's rule that the notification **is** the completion
channel, with no admin UI to check and no reason to suspect anything but slowness. Not theoretical:
SPEC-137's nine-day `ModuleNotFoundError` and PR #196's shared-layer cold-start crash are both exactly
this shape.

**A fifth plane cannot ship without it.** `test_state_machines_cpcommon.py` enumerates every
`state-machine.asl.json.tftpl` under `infra/modules/` and asserts each has a `NotifyFailure` Task with
a `States.ALL` Catch, plus that its `RecordFailure` copies `$.error` **whole**. The exemption list is
an empty dict — an entry is a decision to leave users in the dark, not a formality. The second
assertion is not redundant with the throwing-intrinsic guard: a plane could satisfy that one perfectly
by copying `$.error.Error` alone, and every message would silently degrade to the generic.

**The duplicate-suppression mechanism differs per plane, and the difference is forced, not stylistic.**
This state sits on *every* failure path, because the paths where no verb ran cannot be selected for in
ASL — so an ordinary failure would otherwise notify twice.

- **table-builder / table-share** suppress in Python via `_verb_already_notified`, on **one name**:
  `Error == "TerminalError"`. That is the only *positive* evidence available — a verb raised it
  deliberately and the decorator's `emit_terminal` fired — and it is the only case where the
  decorator's message is strictly better, because it carries `err.tokens` (without which a
  `columns_removed` refusal cannot name the columns). Everything else notifies, including an
  exhausted `TransientError`, which the decorator deliberately leaves un-notified — a gap this spec
  therefore also closes.

  **The obvious generalisation is wrong in the dangerous direction, and was caught in review.** An
  earlier version inferred the same thing from the *absence of a dot*: bare class name means a
  handler ran, dotted engine name means it did not. But `cpcommon.config` calls `_require` at
  **module scope** and raises a bare `RuntimeError` — not a hypothetical, this fleet's own recorded
  outage (`lambda.tf`: "check-table-absent: RuntimeError COGNITO_USER_POOL_ID unset", PR #196). The
  heuristic would have suppressed it, silencing the exact class of failure the spec exists to
  report. The set of dot-free names meaning "a verb notified" is unbounded and unknowable from the
  payload; the set meaning `TerminalError` is one string.

  **The price is a duplicate on the unexpected-exception path** — a `KeyError` inside a verb
  notifies through `emit_unexpected` and again here, same generic sentence. FR-002 settles it: a
  duplicate is preferable to none. A guess that suppresses is unrecoverable; a duplicate is a
  papercut on a path that is already a bug.

  **A seeded error must not wear a verb's name.** table-builder's `DiffMissingSeed` (the
  `RouteByChange` `Default`) manufactured `Error: "TerminalError"` for a case where `diff-schema`
  *returned successfully* without a `$.diff` — so no exception was raised and no decorator fired. It
  now seeds `DiffMissing`, because a defensive seed whose whole purpose is the shouldn't-happen case
  is the last thing that should buy itself a `Fail` state and silence. The user-facing text is
  unchanged: neither code is registered, so both render the generic clause.
- **shared-spaces** cannot use that test, because five of its seven verbs emit **no** failure message
  at all and a "did a verb run" guard would restore their silence. It reproduces the verb's **FIFO
  dedup token** byte-for-byte instead (`{requestId}:{action}-failed:{actor}`), so SQS drops the second
  message where a verb already spoke and delivers it where none did.
- **data-quality** is unchanged: `dqcommon` centralises one `FAILURE_STEP`, so its pair already
  collapses on an identical token. Unifying `tbcommon`'s per-verb steps to match would change
  notification behaviour on paths that already work.

**shared-spaces needed structural work, not just a state.** Its seven verb `Catch` blocks carried **no
`ResultPath`**, so the error object *replaced* the state and the verified actor was discarded — there
was no recipient to notify even in principle. They now merge under `$.error`; a `ValidateFailureSeed`
covers the pre-identity path (its Catch cannot carry a `ResultPath` — you cannot merge a key into an
array), and the router's `Default` gets an `UnknownActionSeed` whose **literal** `Result` merged under
`ResultPath` is the one seed form that reads no path and so cannot itself raise.

**`$.mode` on table-builder's `RecordFailure` supersedes the rule that forbade it.** The old test
banned `mode.$` there; its stated *reason* was that `ValidateFailureSeed` did not seed it and a Pass
state hard-fails on an absent key. The ban was never the invariant — the seeding was. `mode` is now
seeded, and the test asserts the general form: `RecordFailure` may read nothing `ValidateFailureSeed`
does not seed. Without it a failed **refresh** tells the user their **create** failed.

**shared-spaces gained a `failure_message` resolver** (`shared-space-common/messages.py`), the last
plane to get one. Its domain table is **empty on purpose**: every reason that can reach this path is a
raw engine name that SPEC-106 FR-008 forbids showing, so what varies is the **action**, not the reason.
Going through `cpcommon.messages.register` rather than hard-coding the clause means a code registered
later renders through the same path.

**No deploy-role IAM was needed, and that was verified rather than assumed.** All three planes' deploy
policies scope `lambda:CreateFunction`, `iam:PassRole` and `logs:CreateLogGroup` to
`{project}-*-<plane>-*` wildcards, and each plane's SFN invoke grant renders from the same `locals.tf`
map the new function was added to. SPEC-143's `load-table-definition` is the live precedent. The
spec's Phase 1 assumed an expansion and sequenced a separate land-and-apply around the self-grant
timing trap; neither was required.

**The cold-start probe is the one gate that would have caught SPEC-137.** `test_notify_failure_import_safety.py`
imports each new verb in a fresh interpreter whose `sys.path` is **exactly** what its deploy-matrix row
grants. `conftest.py` puts every layer root on `sys.path` for the whole suite by design, `update-function-code`
succeeds against a function that cannot import, and `test_deploy_matrix.py` reasons about **names** — it
cannot tell you the named layer actually publishes what the code imports. The environment is
**inherited**, unlike `test_layer_import_safety.py` which withholds `cpcommon.config`'s six: these verbs
reach their DOMAIN config through their notifier, whose import-time `_require` is *supposed* to run.
(`cpcommon`'s own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what
an import demands from anyone.) Only `sys.path` is scrubbed, because packaging is what is under test.

**One layer needs a second guard, and only one.** The probe puts layer SOURCE TREES on `sys.path`, so a
module present on disk but absent from a layer's *build* is invisible to it. Every layer copies a
**package** (`cp -r cpcommon`) except `shared-space-common`, which publishes **flat modules** from an
explicit `for m in config casio auth …` list in the workflow — so a new module there ships only if
someone remembers to name it. Review confirmed the gap was live: deleting `messages` from that list left
the entire suite green while the deployed layer lost it. A test now joins the workflow's list against the
directory — **SPEC-153 moved it to `test_deploy_matrix.py`**, the harness whose subject is packaging, and
generalised it; see *A layer gate must check the copy list, not the flag map* below.

---

### A layer gate must check the copy list, not the flag map (SPEC-153)

`test_deploy_matrix.py` exists because SPEC-137 shipped instrumented code whose layer attachment was
missing and every gate was blind. It joins each function's **imports** against the matrix **flags**.
That answers "which functions attach the layer" and says nothing about **what the layer contains** —
so adding a module to `lambdas/shared-space-common/`, importing it from a function whose row already
reads `layer: true`, passed every check, deployed green, and raised `ModuleNotFoundError` at cold
start. SPEC-137 again, straight through the gate built to stop it.

**The rule: for any layer packaged by an explicit per-file list, assert SET EQUALITY between that list
and the directory.** Both directions — a module in the directory and not the list never ships; a
module in the list and not the directory fails the `cp` at deploy time. Completing the flag map does
**not** substitute: all nine shared-space modules ship in one layer behind one flag, so a module that
never reaches the zip is invisible to the flag map no matter how complete it is. `LAYER_PACKAGES` was
corrected to all nine anyway, with a comment saying exactly that.

`shared-space-common` is the **only** such layer — every other copies a whole package directory or
pip-installs, so a new module ships by existing, and those are exempt for that named reason.
`test_no_unchecked_explicit_copy_list_was_added` fails if a second one appears, so the exemption
cannot quietly widen. A guard-the-guard asserts the parsed set is non-trivial: two empty sets are
equal, and a regex that stops matching would otherwise pass vacuously.

SPEC-152 shipped the shared-space half of this in
`test_notify_failure_import_safety.py`; SPEC-153 moved it to the packaging harness and generalised it,
rather than leaving two copies of one set-equality to drift apart.

---

### The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)

Four helpers were duplicated across the Lambda layers *on purpose*, each with a comment saying so
and naming the condition under which the copies should converge. Those conditions had all expired,
and in two cases the drift the comments warned about had already happened — `dqcommon`'s CAS twin
handled a racing 409 that `casio`'s did not and used a different retry cap, and `cpcommon/auth.py`'s
"one JWKS-verification path for the whole repo" docstring was false because `notifications-writer`
could not import it.

**Decided: `cpcommon` owns the algorithm; a domain layer owns its wording and its constants.** The
conditional-write CAS loop (FR-001), the failure-message resolver (FR-002), the results-location
builder (FR-003), the JWKS path (FR-004), the SQS envelope parser and the Athena DDL runner (FR-005)
each exist once. The domain message modules keep only their **tables**: `cpcommon.messages.Resolver`
gained `prefix`, `access_denied` and `fallback` templates and an opt-in `blank_unfilled`, so a plane
expresses its whole sentence as configuration. `Resolver.__init__` refusing a re-defined base code
is what had kept two planes out — both re-definitions were byte-identical restatements, so deleting
them was a provable no-op rather than a wording change.

**The blocker was `cpcommon.config` resolving eagerly** (FR-004). Six `_require`d environment
variables at *import* meant a function that set three could not import `cpcommon.auth` at all, so it
grew its own verifier. That is the general shape worth carrying: **an eager module-level requirement
does not merely inconvenience an importer, it forces a fork.** Config resolves lazily now and still
fails loudly at first use.

**Byte-identity was measured, not asserted.** Every reason in all three planes was rendered under
every argument combination against both implementations — 2214 messages per side. Exactly one row
differed: `malformed_event` under table-share, a shared base code that plane never declared, which
used to fall to `tscommon`'s unknown-code fallback and now reads what it means. It is unreachable
there today (table-share's only `parse_sqs_request` call raises `unauthorized`), and it is pinned by
a test rather than left to be rediscovered in an inbox. **Reading three implementations side by side
would not have found it** — that is the argument for rendering both and diffing, on any future
consolidation.

**Do NOT** read this as licence to merge the domain layers into `cpcommon`. The layers stay; only
genuinely cross-plane helpers moved, and a move that would change which layer a function attaches to
is a `deploy-lambdas.yml` matrix change with SPEC-137's failure mode attached.

### The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)

Sharing a table used to copy every object for a recipient inside **one** `copy-objects` invocation,
inside a `Map` over recipients. The share caps followed from that: `SHARE_MAX_OBJECTS = 1000` and
`SHARE_MAX_TOTAL_BYTES = 20 GiB` were sized backwards from a 900-second Lambda timeout. A user with
several hundred Parquet part files did not get a slow share; they got a refusal that read like a
product decision and was really an implementation detail.

The copy is now a **top-level Step Functions Distributed Map** over a flat `(recipient × object)`
JSON Lines manifest in the admin bucket, batching items into the same copy code as before.

**Top level, NOT nested inside the recipient `Map`.** The nested version is the obvious one and it
buys nothing: it fans out per recipient, so the ceiling stays per-recipient work. One Map over pairs
covers every recipient at once and never raises the nesting question. It costs exactly one thing,
and that cost is this decision's other half: **per-recipient isolation stops being a property of a
Map item.**

**So attribution became a verb, and it reads BOTH result groups.** `collect-transfer-results` reads
the Map Run's `ResultWriter` export. Step Functions files a child by its **execution status, not by
what its payload says** — and the batch copier deliberately **succeeds** while reporting per-item
failures, so those land in `SUCCEEDED_n.json`. A collector reading only `FAILED_n.json` would report
universal success while a recipient received an incomplete dataset **and a table over it**. It
therefore reads `SUCCEEDED_n` (per-item `failures` from the output) **and** `FAILED_n`/`PENDING_n`
(whole-batch failures, attributed from the child's *input*). A record whose payload Step Functions
omitted (`Included: false`) is **unattributable and fails the whole request** — never "no failures
found". One failed item means that recipient gets **no table**: a partial copy under a table
definition is worse than no table at all.

**`ToleratedFailurePercentage: 100` and `STANDARD` children.** The Map Run must always finish, or
there is nothing for the collector to attribute. Children are STANDARD because a batch may hold a
multi-GiB object whose multipart copy exceeds EXPRESS's five-minute ceiling, and EXPRESS's
at-least-once semantics would re-run whole batches.

**A WHOLE-batch failure fails every recipient in that batch, and that is fail-closed on purpose.**
Items are batched in recipient-major order, so a batch spans several recipients only when a
recipient has fewer objects than the batch size — but when it does, a child execution that dies
outright (an exhausted `TransientError` retry, a Lambda timeout) takes all of them down with it. It
reported nothing per item, so which of its items landed is genuinely unknown, and the conservative
answer is the only honest one. Pre-160 each recipient had its own invocation and its own retry
budget, so this is a real narrowing of isolation, accepted deliberately: the alternative is trusting
a copy nobody observed. A Distributed Map cannot partition batches by key, so a per-recipient
guarantee would mean a Map per recipient — the nested design this decision rejects.

**Attribution keys on `(kind, name)`, never the name alone.** A destination is a pair, and nothing
in this system stops a shared space being named after a user (the archival arc records the same
hazard for its key layout). Keyed on the name, one failed object in space `acme` would deny user
`acme` a table they actually received, and send them a failure notification for it.

**The export is reconciled against the manifest, not merely parsed.** Every unrecognised shape
raises — an entry naming no object, a result file that is not a list of records, a record with no
item count — because a reader that skips what it does not understand reports a clean run over an
export it never read. Shape checks alone are not enough, though: a well-formed export can still
cover only some of the batches, so the collector requires the item count the export accounts for to
equal the count `build-transfer-manifest` wrote. Anything less is a whole-request failure.

**The raw `{Error, Cause}` is decoded at the collector and NOT carried onward.** This is a payload
decision. A Cause runs to hundreds of bytes with its stack; leaving `guardResults` on the state
*and* re-emitting the raw error in the outcomes would put three copies of every refusal on the state
by the time the finish Map merges its results — measured at **108% of the 256 KB limit** for 50
conflicting recipients, which is the *ordinary* case of re-sharing a table most recipients already
have, and a breach there lands **on a Map** and destroys every per-recipient outcome. So the
collector **consumes** `guardResults` and carries `cpcommon.errors.failure_reason`'s decoded code;
the raw object remains in the execution history at the state that produced it. The two peaks — the
guard Map's output and the finish Map's — are both modelled by
`test_the_whole_map_state_stays_under_the_payload_limit`, at 42% and 45%.

**A deterministic item failure never raises; a transient one always does.** The batch returns
per-item outcomes and succeeds, so one unreadable key never costs its 49 siblings their copy. A
throttle raises after every in-flight copy settles, and the Map retries the whole batch — safe
because copy is idempotent and the conflict guard has already run. The `CopyObjects` child state
carries **no `Catch`**: catching there would SUCCEED a failed child, filing it under `SUCCEEDED_n`
with no per-item failures, and every item in it would be reported as copied.

**The manifest key is execution-unique; the copy plan beside it is deliberately not.** A plan is a
pure function of the request, and two overlapping executions colliding on one plan key is harmless
because both plans describe the same object set — that argument is written out in `plan_key`'s
docstring and still holds. It does **not** carry to the manifest: its lines depend on which
recipients the **guard accepted**, which is time- and destination-dependent, so a shared key would
let one execution's Map Run copy for a recipient the other's guard had just refused as `conflict`.
The execution name is stamped by a **Pass** state (SPEC-157's measured pattern: reading `$$` in a
task's own `Parameters` wraps the payload, and every notify path here reads the request at the top
level).

**The Distributed Map's permissions are the STATE MACHINE role's, not the Lambda execution role's.**
It is the state machine that calls `StartExecution` for each child and that reads the `ItemReader`
object and writes the `ResultWriter` export. Putting them on the execution role renders green,
applies green, passes a policy-render test, and fails on the first real share with `AccessDenied` at
the `ItemReader` — naming a role nobody was looking at. `StopExecution` is not granted;
`StartExecution` + `DescribeExecution` is the documented least-privilege pair. A test asserts the
`states:` actions appear in the SFN policy and **not** in the execution policy.

**The engine lives on `cpcommon.transfer`, not `tscommon`.** SPEC-164→167 (send files) is the second
caller and SPEC-168→172 (archive) the third; SPEC-156 already settled that `cpcommon` owns the
algorithm while a domain layer owns its wording and key layout. `tscommon.copy` was **deleted**, not
wrapped — a re-export shim is the deliberate twin that spec exists to prevent. Table-share keeps the
manifest **key layout** (`copy_plan.transfer_manifest_key`) and every user-facing sentence.

**S3 Batch Operations is rejected, not deferred** — see the amendment on the *Table Share* entry
above. The refusal is a property of the API (`TargetKeyPrefix` prepends to the full source key; 5 GB
per object; one destination bucket per job), not of the implementation it was proposed to replace.

**The caps did not move.** 160 changes the mechanism and nothing a user can see: same push, same
conflict rules, same notifications, same `SHARE_MAX_*`. That ordering is deliberate — a regression in
a new engine must not be able to hide behind a new limit. SPEC-161 raises the ceiling.

**Two numbers live in two places, and a test holds them together.** `MAX_ITEMS_PER_BATCH` and
`MAP_MAX_CONCURRENCY` (20) are read by the batch verb from `cpcommon/transfer/config.py` and by the
rendered ASL from `locals.tf`, because Terraform cannot import Python. The batch size is sized
against S3's *worst case* — two 1024-byte keys and two 63-byte bucket names put an item near 2.3 KB,
so even 50 items sat under half the 256 KB child-execution input limit — and that bound is
**computed in a test**, not asserted as a number.

> **Superseded (SPEC-161, 2026-08-10) — `MAX_ITEMS_PER_BATCH` is 8, and the PAYLOAD bound is no
> longer the binding one.** `ItemBatcher` batches by **count, never by bytes**, so the unit that
> must copy inside `copy-objects`' 900 seconds is a whole batch. That was implicit while
> table-share's total cap was 20 GiB — a batch could not exceed the whole table — and SPEC-161's
> 1 TiB removed it.
>
> **And a batch's cost is a MAKESPAN.** `copy_batch` hands one whole object to each of
> `COPY_CONCURRENCY` workers and `copy_one` part-copies serially, so the cost is
> `ceil(items / COPY_CONCURRENCY)` rounds of the slowest object — never total bytes over an
> aggregate rate. **8 = `COPY_CONCURRENCY` makes that ceiling one**, so a batch costs one object's
> time (429 s at `SHARE_MAX_OBJECT_BYTES` 10 GiB). At 10 items it was two rounds and 859 s against
> a 900 s timeout; the bytes-over-bandwidth reading called the same configuration 537 s and stayed
> green. `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the makespan and
> `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality. **The batch size,
> `COPY_CONCURRENCY` and table-share's per-object cap can no longer be changed independently.**

### A post-identity failure needs its own seed, and the fleet guard cannot see it (SPEC-165)

**Decision.** The file-send machine carries **two** failure seeds. `InspectSource`'s catch uses
`ResultPath: "$.error"` and routes to `InspectFailureSeed`, which supplies `raw` from
`$$.Execution.Input` and the actor from `$.actor`.

**Why not route the catch straight to `RecordFailure`,** which is what every other plane does. This
plane's `RecordFailure` reads `$.raw`, and `raw` exists on **no** post-validate state — SPEC-164
deliberately did not thread the request through, because the Pipe record carries the selection
again as an escaped string. A Pass state's JSONPath hard-fails on an absent key with an uncatchable
`States.Runtime`, so the direct route kills the execution **before** `NotifyFailure`: the sender
hears nothing, on exactly the failures SPEC-152 exists to report.

**Why the fleet guard does not cover it.**
`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` identifies a seed
**structurally**, as a Pass whose `error.$` is `"$"` — the shape a catch has when the error
*replaced* the state. A catch carrying a `ResultPath` produces `"$.error"` instead, and the fleet
walk skips it entirely. Widening that detection is a fleet-wide change to a guard, on five machines,
and was **rejected as out of scope for this spec**; the plane's own suite compensates with a walk
that derives from the machine what Step Functions actually leaves on the state at each catch
(`ResultPath: "$.x"` ⇒ the task's input plus `x`; no `ResultPath` ⇒ nothing addressable). Verified
by mutation — and the first version of that walk **passed vacuously** on the exact mutation it
existed for, because it treated the catch target as a seed instead of as a reader.

### The machine's ceiling cannot notify on its own, and this plane's timeout door needs a fallback (SPEC-166)

**Decision.** A top-level `TimeoutSeconds` of 10,800, shipped together with an EventBridge rule on
`Step Functions Execution Status Change` / `TIMED_OUT`, a second door in `fs_notify_failure`, that
verb's raise to 60s, and the deploy role's `events:` grant.

**Why together.** AWS catchers cover Task, Parallel and Map states but **not top-level execution
failures**: the timeout terminates the run outright, so no state runs, no `Catch` fires, and the
machine's own `NotifyFailure` is unreachable on the one failure it most exists for. `TIMED_OUT`
only, never `FAILED`, or every caught failure notifies twice.

**The budget is computed, every term of it**: copying 6,597 s + per-child overhead 939 s + guard Map
600 s + serial verbs 735 s = 8,871 s against 10,800 s. The only input without a measurement behind
it is the per-**round** child overhead — charged per round because slots pipeline — and it is
load-bearing: charged per child at even half a second the budget would blow. The test states its
own break-even (~9 s per round).

**The door needs a fallback table-share does not.** EventBridge caps an event at 256 KB and Step
Functions drops the input rather than exceed it, while `SEND_MAX_ITEM_BYTES` deliberately allows a
Pipe record approaching 200 KB — so the sends most likely to time out are exactly the ones the
event alone cannot attribute. The door reads the input back with `states:DescribeExecution`, on the
**Lambda execution role**, because EventBridge invokes the notifier outside any execution.

**And the seed that reports all of this must not carry the request twice.** `RequestFailureSeed`
supplies `$.raw` (the Pipe record, ~200 KB at the cap) and **not** `$.source`, which is the same
selection again: together they breach the 256 KB state limit for a quote-heavy legal request, on a
Pass with no `Catch`, killing the run before `NotifyFailure` at the end of a three-hour copy.
Nothing on the failure path reads the source; an operator has it inside `raw`.

### The lock protocol is `cpcommon`'s, extracted ahead of its second consumer (SPEC-187)

SPEC-187 needs a per-space lock, which made the file-operations plane the second consumer of a
protocol that had lived on `tbcommon.table_lock` since SPEC-157. Copying it would have left **two
full compare-and-set lock implementations in the fleet** — the deliberate twin SPEC-156 spent a spec
discharging, in the one module whose entire purpose is preventing a concurrency bug.

So the protocol moved to `cpcommon.lock`, parameterised by bucket, key, stale threshold, wording and
identifying fields; each domain keeps its key layout, its own thresholds and its own sentences. It
was extracted **ahead of** the second caller rather than after it, which is this repo's recorded
pattern: building the caller first means importing a leaf domain's module, and that is the
undeclared shared layer SPEC-155 had to unpick.

**Two seams the shape had to grow, both forced by what a caller's tests need.** The reader is
**injected**, called as `read(key)` — pinning the read is the only way to reach the concurrent case,
two acquires seeing one stale tag decided by the compare-and-set rather than the age check. Had the
protocol read S3 itself, that seam would not exist and `test_two_simultaneous_steals_and_only_one_wins`
would have degraded into two sequential calls that still pass every assertion, which is worse than a
failure. And the wording is **six sentences plus a fields mapping**, not one label: the six are
emitted from seven call sites with different fields, and a caller's tests assert them by message.

**The proof of behaviour preservation is that table-builder's two lock suites were not rewritten.**
One assertion did have to move — a grep for `delete_object` pointing at a module that no longer holds
any write code, which would have kept passing while asserting nothing.

### The engine's attribution vocabulary belongs to the CALLER, not to cpcommon (SPEC-189)

`cpcommon.transfer.copy_batch` and `results._from_input` built their failure records as
`{recipient, kind, reason}`, hardcoded to table-share's vocabulary. This plane attributes to a
**selected item**, and there was no field to carry it: an `itemKey` on a manifest line rode into the
child input and was dropped on the way out. The engine now takes a caller-supplied `echo_fields` set
in **both** halves — they are separately implemented, one copying what the batch verb wrote and one
rebuilding it, which is exactly the pair that drifts, and a drifted record is one the caller
silently cannot attribute.

**`echo_fields` has no default.** A default hands a new caller either table-share's vocabulary or an
empty set, and both are wrong without a review. Table-share and file-send pass
`("recipient", "kind")` and their records are byte-identical, measured by rendering both rather than
argued. **Archive passes the empty set and its records change**: its manifest carries neither field,
so every archive failure used to read `{"recipient": null, "kind": null, …}`. A named test says the
two nulls are gone on purpose.

**The echoed fields must stay bounded.** The list rides the exported result and then the state, where
a key list is the unbounded term that breaches the 256 KB limit **on the Map** — destroying every
per-item outcome the export exists to preserve. Echo a name, never a key set.

### Two budgets, and both were wrong before they were computed (SPEC-189)

**The joint budget:** the lock give-up, two guard sweeps, every serial verb timeout, the copy's
makespan and the deletion, added. At 3 TiB it came to ~12,700 s against a 10,800 s ceiling — and the
earlier version carried **no give-up term at all**, though a waiter can spend 2,080 s. Waiting for a
busy space and *then* copying is one execution, not two scenarios. **The cap moved to 2 TiB, not the
ceiling**, because the ceiling also sets `STALE_LOCK_SECONDS` and a longer stale window on a shared
space blocks everyone who works in it, not only the person whose run wedged.

**The state budget, which no earlier spec owned:** the deletable list, the per-item counts and the
per-item deletion records measure **287,532 bytes** at the selection cap against 262,144 (307,083
with conflict samples). All three travel by pointer, on this plane's own recorded rule that
everything unbounded on the state does. Where it would have broken is the worst place available:
`States.DataLimitExceeded` on the collector's result lands **after the copy**, and on delete-source's
**after the deletion**, and that error escapes every `Catch` — so the user would be told nothing at
all about an operation that had already moved their data.

### One producer, after the release, reached from BOTH of ReleaseLock's edges (SPEC-191)

The plane's outcome producer is the last state before `Succeeded` and it sits **after**
`ReleaseLock` — before it, the space would be held for as long as the messages take to write. The
half that is easy to miss is that `ReleaseLock`'s **`Catch`** had to move with its `Next`. That
catch exists so a failed release cannot fail a request that did its work; pointed at the terminal,
it skips the producer, and a release whose `Retry` one throttle exhausts then **completes the
operation and tells the user nothing**. The browser's per-space gate, which settles on a
notification carrying the `requestId`, would hold that space until the machine's ceiling — the exact
wedge the always-present `requestId` exists to prevent, arriving through the one path nobody looked
at. Both edges reach the producer now, and a test asserts it.

**It is also the one Task on this plane whose catch reaches a terminal rather than a release**, and
that is not an oversight to be tidied. The lock is free by the time it runs, and a release is an
**overwrite**, not a compare-and-set on the holder — so a second one would clobber whichever
execution had since acquired that space. The graph walk's not-under-the-lock set names it with the
reason, beside validate-authorize and the failure notifier.

It cannot fail the run: `ResultPath: null` on the state *and* on the catch, and **no**
`@notifies_on_failure` — by the time it runs a `move` has already deleted its sources, so a raise
would report a completed operation as a failed one. And it reads the **state and nothing else**: a
verb that loaded the plan would join the set whose smallest memory sizes `FILE_OPS_MAX_OBJECTS`,
shrinking a cap that has nothing to do with notifying. A test derives that set from the source.

### A notification payload is bounded by BYTES, and the binding case is the PLAIN one (SPEC-191)

The inbox is capped at 200 rows and the browser fetches and `JSON.parse`s the **whole** document on
every 60-second poll, from the header bell, on every page — so a worst-case inbox is a recurring
per-minute download rather than a one-off read. Against that, one conflicted item is ~200 bytes at
ordinary key lengths and ~12,000 at this plane's caps: S3 keys are 1,024 bytes of arbitrary UTF-8
and JSON escaping turns a control character into six. A count of three is therefore either
negligible or 36 KB, and the count alone cannot tell those apart.

So the payload is bounded by **bytes as well as count**, enforced at mint by adding conflicted items
only while the serialised payload still fits and setting `more` when any are dropped — for either
reason. That is what makes the pathological case *safe* rather than merely small: a run whose keys
are at S3's limit carries fewer items than the count allows, or none, and says so.

**The budget the byte cap is derived from is the MARGINAL one** — the structured field may not add
more to the worst-case inbox than the row already costs without it. An absolute number would be one
chosen and then defended, and the row's own fixed cost (a percent-encoded link, a 1,024-byte
destination prefix) is not something this spec controls.

**The estimate was overturned twice, and both corrections came from measuring rather than
reasoning.** 4 KiB was written down first. The first measurement refused it — and the binding case
turned out to be the **plain** one, not the escape-heavy one, because a control character expands
*six* times inside the JSON payload and only *three* times in the percent-encoded link beside it, so
the row a payload competes against is **smaller** when the keys are hostile. Then a reviewer found
the second error: that measurement compared the budget against a row **that already carried the
payload head**, which weighs the field against itself. Measured against a row carrying no payload at
all, the allowance is **1,674 bytes**, not 3,047. **The cap is 1 KiB.**

**The head is mandatory, so its one unbounded term is capped separately.** Dropping conflicts cannot
help when the head alone is over budget, and nothing validates the LENGTH of a destination prefix on
the way in — only its containment. Left unbounded, a hand-crafted envelope with a multi-kilobyte
prefix would push the payload past the writer's ceiling and lose the **whole message**, on the queue
whose dead-letter queue is deliberately undrained, after the data had already moved.
`FILE_OPS_NOTIFIED_PREFIX_BYTES` is S3's own key limit: a prefix longer than a legal key cannot
produce a legal destination key, so the run it describes copied nothing and a re-submit of it would
be meaningless.

**The producer's bound and the writer's refusal are two numbers in two languages.** A payload the
producer considers fine and the writer refuses does not lose its conflict list, it loses the
**whole message** — on the one queue whose dead-letter queue is deliberately undrained. So
`notifications_writer.MAX_PAYLOAD_BYTES` **rejects** (never truncates) an oversize payload, and a
test reads that ceiling back out of the Lambda and asserts the largest payload this plane can emit
sits under it.

### The run's ONE sentence opens neutrally, because its residue is not all failure (SPEC-191)

Partitioning a run's outcomes into "the operation's success outcome, or not" is the obvious split,
and it makes the sentence contradict itself on the two outcomes that matter most.

A **`duplicate`** reached the destination — the notification's own link points there — so an opening
of "Nothing was moved" is false, and it is followed two clauses later by "This data is now in both
places". A **`noop`** is a success that did nothing, which this plane's vocabulary says in as many
words; reported as a denial it reads as exactly the failure the wording rules exist to prevent.

So the opening is `N need your attention`, which is true of every member of the residue and is the
only thing they have in common. What succeeded is still named first on a mixed run — "2 of 5"
answers the question a user actually has, where a message listing only refusals reads as though
nothing worked.

### A resolved space carries its own IDENTITY, not only its location (SPEC-191)

`authz` resolved a space to `{bucket, root}`. A root is not a name and a bucket is not a kind, and
the difference surfaces only at the far end of the plane: the producer has to say which space a run
touched and link into it, and a re-submit built from that notification needs the **source** space,
which no absolute key contains.

Left as it was, `kind` and `name` reached the summary as `None`, the link builder refused to mint
anything, and **every notification shipped with no link at all** while the payload carried nulls
where a re-submit's spaces belong — with a full green suite, because every fixture in the notifier's
tests hand-wrote the shape it wanted. That is the test-that-cannot-fail class: the fixture asserts a
shape the producer does not emit.

They ride from the resolver rather than being re-read off the request, because that is the point at
which the claim has been **authorized** — a later verb reading the untrusted body would be naming a
space the actor may never have been granted. The guard against the fixture problem recurring is one
test that builds the notifier's input from the real `authorize_source` and the real finaliser
instead of a literal.

### `requestId` rides on every row, including a clean run's and a failed run's (SPEC-191)

A reader settles its in-flight record by matching it, and a clean run has nothing to re-submit — so
scoping the field to "what a re-submit needs" would leave successful operations unsettled. The same
argument applies one path over, to a run that **failed** before the producer ever ran, which settles
nothing otherwise; so the two failure emitters carry a minimal `{requestId}` payload too. That is
beyond the spec's own acceptance criteria and was built deliberately.

### The outcome link: destination, source, or the common folder of the items' PARENTS (SPEC-191)

A copy or move that landed anything links to the **destination**; anything else links to the
**source**, because that is where the items still are. One message per run means one link, so the
rule is about the run rather than about an item — and a `duplicate` counts as landed, since its
objects *are* at the destination and that is exactly where the user has to look to choose which copy
to keep.

**A `delete` links to the deepest folder its items shared, computed over the items' PARENTS.** Over
the keys themselves, a single-item delete yields the item — linking the user into the folder that
was just removed, an empty listing where a folder used to be. Taking parents first makes the
one-item and many-item cases the same computation. A common prefix is also cut back to its last
slash: two siblings named `report-a` and `report-b` share `report-`, which names no folder.

**`?space=` is minted FIRST, and that is not cosmetic.** `NotificationRow` gates the shared-space
variant on the literal `?space=`; the other parameter order slips the gate, the route never reads
the space, resolves the personal one, discards a prefix that does not start with it, and lands the
user in their own files with no banner while the message names a shared space.

**This is the fleet's first link built from an arbitrary KEY**, so the prefix is **percent-encoded**
at mint — every other plane interpolates catalog-constrained names. An unencoded `?`, `#` or `&`
truncates the link into one that resolves elsewhere, and the browser's `isSafeInAppPath` cannot see
it: that guard inspects only the first two characters.

### The outcome wording reuses the failure bodies and is deliberately NOT a resolver (SPEC-191)

Six per-item outcomes carry a reason the failure table already words — `source_missing`,
`source_empty`, `copy_failed`, `source_changed`, `source_delete_failed`, `delete_refused` — so the
item clause resolves through that same table and only the outcomes with no body of their own are
written out. A second table would be one code with two sentences, inside one module.

**The outcome table is not registered as a `Resolver`.** `Resolver.__init__` ends by marking every
key it is given a globally valid reason code, so registering these would let
`TerminalError("duplicate")` pass raise-time validation — undercutting `outcomes.py`'s rule that no
member of the per-item vocabulary may ever be a whole-request failure reason. That a success
sentence cannot open with "Couldn't move that: " is the lesser argument.

### A pre-existing notifications spoofing gap, recorded and not fixed here (SPEC-191)

> **Superseded by SPEC-206 (2026-08-24).** The gap below is closed: the writer refuses a `create`
> whose SQS-stamped `SenderId` names the portal role. The grant is still unconditioned — that part
> stays true, and is why the control is a runtime one. See the SPEC-206 entry at the end.

The portal role holds an **unconditioned** `sqs:SendMessage` on the notifications request queue, and
the writer takes the body's `username` verbatim for a `create`. A signed-in browser can therefore
already plant a notification — message and clickable in-app link — in another user's inbox. The
comment directly above that IAM grant asserts the opposite, which is the dangerous combination: a
reader checking the IaC is told the hole is closed. IAM cannot condition on a message body, so the
fix is a second queue or a token on `create`, and it changes a plane seven features share. Recorded
rather than absorbed into this spec; the payload ceiling above is the only part of it this spec owes.

### The notifications `create` boundary is a runtime check, because IAM cannot express it (SPEC-206)

The plane has said since SPEC-058 that `create` is trusted-producer-only, and the writer takes the
body's `username` on that action — correctly, because a plane notifying a *recipient* holds no token
for the person it is telling. **The IAM policy never implemented it.** The portal role's
`sqs:SendMessage` on the notifications queue was unconditioned, so any signed-in user could enqueue a
`create` naming anybody and saying anything, including a clickable in-app link. The comment above that
grant asserted the opposite, which is the dangerous combination: a reader checking the IaC was told the
question had been answered.

**IAM cannot express this rule at all, and that is the argument — not a preference for runtime checks.**
No SQS condition key reaches a field inside a message body, so a queue or identity policy could only
deny the portal role `sqs:SendMessage` outright: the same principal on the same action that `markRead`
and `markAllRead` need. There is no policy that permits two of the three actions. So the boundary is the
`SenderId` SQS stamps on every message — a message *system* attribute the service sets and a
`SendMessage` cannot — compared on the **role-id half**, the substring before the first `:`. Not
equality against the whole value (which never matches, and a control that never matches reads exactly
like one that works) and not `startswith` (which would refuse an unrelated role whose unique ID merely
shares an opening). The session-name half is never examined: Cognito's enhanced flow does not document
what it puts there.

**The rule is a DENY of one principal, not an ALLOW of eight.** Nine principals hold the grant — seven
control-plane execution roles, the DLQ drain, the portal role — and exactly one is user-reachable, which
is what makes a single-principal refusal complete rather than partial. An allow-list would be a
hand-maintained list of role IDs that fails closed on the day a plane is added: that plane's
notifications would stop, drop or dead-letter unnoticed and nobody would connect the two. One
environment variable beats eight, and the deny direction fails open only toward principals that require
an explicit IAM change to exist.

**A refusal LOGS AND DROPS; it does not raise.** Raising would cost three invocations and one permanent
dead-letter message per forged request, on the queue whose DLQ SPEC-126 deliberately leaves undrained
and which is this plane's only operator-facing signal — handing every signed-in user a way to drown it.
The structured `observability.error` therefore *is* the signal, and has to be, precisely because nothing
accumulates to notice. It carries the reason code and the SQS `messageId` (both service-stamped) and
**nothing from the body**: echoing it would move the injection from the victim's inbox to the operator's
log rather than remove it. The guard sits **above** `_resolve_username` rather than inside the `create`
branch, because that call runs before any branch — lower, a forged create that simply omits `username`
would reach `create requires a username` and raise, which is the vector the drop exists to close.

**Three reason codes, not two.** `untrusted-sender`, `sender-id-absent` and
`sender-check-unconfigured`. A check that cannot run must not report a pass, and the cases are
operationally opposite: one is somebody trying it on, one is the control having broken, one is the
deploy being wrong. Splitting the third out is also load-bearing, and two guards carry it: the
empty role-id half is refused **before** the comparison, so an absent sender never compares equal to an
unset variable and gets logged as a forgery; and the configuration is tested **first**, so an unset
variable reports itself even when the sender is absent, rather than returning `sender-id-absent` and
blaming the message for a broken deploy.

**Do NOT split `create` onto a second queue.** It is the obvious fix — IAM could then enforce this with
no runtime check — and it is rejected. The single-writer guarantee is *one FIFO queue, one message group
per user, batch size 1*, and FIFO ordering is per `(queue, group)`. Two queues means two event-source
mappings and two concurrent invocations read-modify-writing one user's `notifications.json`: a mark-read
and an arriving notification can lose each other. It trades a spoofing bug for a data-loss bug, and
closing that would mean putting the inbox write under ETag CAS first.

**Two limits, stated rather than implied.** This decides who may send a `create`, not who may reach the
queue — a non-JSON body or an unknown action still raises from `_parse_record` and dead-letters. And it
is the **interim** fix: Arc B removes the browser's grant (SPEC-200) and after SPEC-196 the denied
principal becomes a *service* principal, harmless because every `create` is emitted by execution roles.
The check stays regardless; that removal is eleven specs out and reversible. Detail:
`spec-delivery/SPEC-206`.

## Analytics, the catalog, and two SQL dialects

### Analytics (SPEC-032→036)

In-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.

### Query workspace has NO active database (SPEC-077)

Supersedes SPEC-047/076. Database *selection* is removed entirely — no "current database" anywhere. Queries carry **no** `QueryExecutionContext.Database`, so every base table must be **fully-qualified `database.table`** (an unqualified name fails); this enables cross-database joins in one statement. The schema rail (`useConnections` seam) is **browse-only** (no radio/active); per-table actions (View DDL/data/Drop) take the DB from the rail node; Create view **derives** its target DB from the body's qualified tables; autocomplete (`useAllSchemas`) spans **all** accessible databases with fully-qualified suggestions. The rail no longer inserts into the editor (FR-004 dropped, user decision). Results always land in the personal prefix; shared save destinations stay a Save-time choice (SPEC-049/055).

### Multi-statement scripts (SPEC-078)

The editor splits `;`-separated statements client-side and runs them **sequentially, stop-on-first-failure**, one history entry each; three run scopes — **Run Statement** (⌘⏎, selection/cursor), **Run Script single-result** (⌘⇧⏎), **Run Script tab-per-statement** (⌘⌥⏎, ephemeral per-run **result tabs**; DDL/DML earn none). No transactions (Athena has none); statements never run in parallel. Detail: SPEC-078 + delivery doc.

### Table Builder (SPEC-066→072)

"Create a Glue/Athena table from a folder of files" via a **dedicated** async control plane (its own FIFO SQS → EventBridge Pipe → **linear** Step Function → five single-task verb Lambdas `validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl`) sharing **one execution role** (all five verbs; consolidated from the SPEC-066 per-verb roles — user decision, mirroring shared-spaces) + a CI-built `table-builder-common` (`tbcommon` package) layer + a CI-built `polars` layer (infer-schema only). **Partitions:** keys are **user-declared in the modal in granularity order** (Hive `key=value/`, never auto-detected), exposed via **Athena partition projection** (no `MSCK REPAIR`); per-key type+range collected in the modal. **CSV is not type-inferred** (all-string, OpenCSVSerde); Parquet/JSON infer + parse dates. **The shared execution role creates tables via the `portal-managed` LF-Tag (TBAC), NOT via LF-admin status** (SPEC-070/111 correction — LF *admin* alone does NOT grant CREATE_TABLE; target DBs are dynamic per-user/per-shared-space so are tagged at provision time and the role is granted on the tag + a static per-bucket DATA_LOCATION_ACCESS; see the Control-plane TBAC decision below; IAM otherwise scoped, delete denied). Any **unexpected (non-Terminal/non-Transient) verb error notifies the actor** via `tbcommon.notify.notifies_on_failure` (no more silent failures); SFN terminal states record `{…, status: created|failed, reason}` (the outcome SPEC-072 notifies from). Decision record: `lambdas/info/planes/table-builder.md`. Do NOT build MSCK-based partition loading or auto-detect partition keys.

### Table Share (SPEC-088→094)

**COMPLETE:** "share a table across databases" — from the Query schema rail, copy a table's data files into recipient spaces under `shared_tables/{table}/` and create a clone table in each recipient DB (personal users and/or shared spaces). Its own **dedicated** async control plane (FIFO SQS+DLQ → Pipe → Standard SFN with a recipient `Map`, single-task Lambdas + `table-share-common`/`tscommon` layer, **one shared execution role** — creates tables via the `portal-managed` LF-Tag, not LF-admin status; SPEC-070/111 correction). SFN: validate-authorize (actor must have **source** access — personal=own DB, shared=active member) → inspect-source (**clone the source Glue table definition**, not re-infer; reject views/catalog-partitioned/non-external; cap object count+size) → Map(recipient): check-target-absent (fail-that-recipient on conflict, no overwrite) → copy-objects (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → create-table (repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Push** (no consent; recipient notified); **any shared space is a valid target** (sender needn't be a member — source access still gated); v1 sources = flat or projection-partitioned base external tables. UI = schema-rail per-table **"Share table"** (`features/table-share/` dialog + `useTableShare`, SPEC-093); **outcomes = SPEC-058 notifications** (sender per-recipient success/failure + whole-request failure; on success the recipient user / space **owner** is also told — `tscommon.notify`/`messages`, best-effort, `sqs:SendMessage` on the notifications queue only, SPEC-094). New browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`. Decision record: `lambdas/info/planes/table-share.md`. Do NOT build a consent/accept flow, schema re-inference, or catalog-partition-metadata copy in v1.

> **Amended (SPEC-160, 2026-08-10) — S3 Batch Operations is REJECTED, not deferred.** The original fence read "do NOT build … S3 Batch Ops … in v1", which recorded it as the scale path to reach for later. It is not one. Its Copy operation **cannot rewrite a key**: `TargetKeyPrefix` prepends to the *full* source key, so a job can only ever produce `bob/shared_tables/sales/alice/tables/sales/year=2024/part-0.parquet` — the sender's own prefix layout echoed inside the recipient's space, with the clone's `LOCATION` pointed at a path naming the sender's directory structure. It also caps objects at **5 GB**, where `tscommon.copy` already handles more via `UploadPartCopy`, and one job writes to exactly one destination bucket while recipients span two. The scale path is a **top-level Step Functions Distributed Map** over a flat `(recipient × object)` JSONL manifest in the admin bucket, running the existing copy code unchanged (SPEC-160), with the engine on `cpcommon.transfer` because the send-files plane (SPEC-164→167) is its second caller. **Do not re-propose Batch Ops** — the refusal is a property of the API, not of the current implementation.

### Data-quality report view (SPEC-113)

The report is read at `/data-quality/:space/:requestId` — **the space is in the route, not derived**, because `requestId` alone cannot say which space holds `{space}/_data-quality-reports/{requestId}/report.json`. Resolution precedence: the actor's **own username always wins**; shared-space names are consulted only when the segment differs (SPEC-114's link builder pins the same rule). An unreachable space renders the friendly denied state and **issues no S3 request** — no existence oracle. The SPA's report types mirror `dqcommon/report.py` byte-for-byte; the banner **warns on `hasIncompleteFigures`** and only softly qualifies on `hasApproximateFigures`, which is true on every report the arc can produce. Detail: `spec-delivery/SPEC-113`.

### Data-quality runs index + dashboard (SPEC-123)

The `/data-quality` list is backed by a per-space **`index.json`**, not by listing the reports prefix — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives NO chronology, and building rows from the reports themselves costs one GET per row and gets slower the more the feature is used. `assemble-report` appends one small entry (the row's fields and nothing else) under **optimistic ETag CAS** with bounded retry, because checks of DIFFERENT locations run in parallel (the queue serializes only same-location checks) — the same lost-update fix SPEC-082 applied to the registry. It was duplicated in `dqcommon` because `casio` sat in a layer the data-quality functions don't attach (**SPEC-125 did NOT merge it** — it folded the shared *client/config/JWT/notify* surface onto `cpcommon` and deliberately left the CAS retry loop domain-side).

> **Superseded (SPEC-156 FR-001, 2026-08-07) — the duplication ONLY.** The loop and the 409 predicate live in `cpcommon.cas`, which every data-quality verb already attaches; `DQ_INDEX_CAS_RETRIES` is gone and the cap is one value (6) for all callers. The twin had drifted before anyone merged it, which is this paragraph's real lesson. Everything below is unchanged and still live.

The index is **capped at 200, oldest dropped first**, and every failure is **logged and swallowed**: the report is the artefact, the index is a convenience, so write order is report → notification → index, most durable to least. The page **aggregates across spaces** (this is "my checks", not "checks in one folder") and one unreadable space is skipped rather than blanking it. It lists **completed checks only**, and the footer line saying failures live in notifications was worded **"usually"** until **SPEC-126** closed the never-started-an-execution hole; it now says **"always"**. No new IAM. Detail: `spec-delivery/SPEC-123`.

### Control-plane table creation = TBAC (SPEC-070/111 correction)

Supersedes "execution role = LF admin ⇒ catalog-wide create". LF data-lake **admin status does NOT grant `CREATE_TABLE`** on a database the admin didn't create — so table-builder/table-share/data-quality (all admins) silently failed to create tables in user/shared DBs. Fix: a single **`portal-managed` LF-Tag** stamped on **every** personal + shared DB at provision time (`post_confirmation.py` / `create_space.py` call `AddLFTagsToResource`; backfill existing DBs via `scripts/backfill-portal-managed-tag.sh`), with **one tag-policy grant per execution role** (DB `CREATE_TABLE`… + inherited table perms) — **not** per-DB named grants. Locations (which LF-Tags can't express) get a **static per-bucket `DATA_LOCATION_ACCESS`** grant (3 roles × user-space + shared buckets). The portal role keeps its named per-DB grant (per-user isolation needs the named ARN). Not-in-scope-to-change: the "per-user isolation = username IAM principal tag, not LF-Tags" decision — that's a *different, per-user* tag. Detail: `infra/modules/analytics/lakeformation.tf`.

### Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)

A refresh reads a table this run did not create, so before re-deriving anything it must answer *can
this be faithfully rebuilt from its own definition plus a fresh look at its files?* **It answers from
what Glue reports, never from a `portal.managed` marker** — and the marker exists anyway, written by
`cpcommon.ddl.build_create_table_ddl` from this spec onward. Both halves of that are deliberate.

**Why not the marker.** Every table created before SPEC-143 lacks it, so a marker test refuses the
entire existing estate. Worse, `TBLPROPERTIES` are user-writable through `ALTER TABLE SET
TBLPROPERTIES` from the query workspace — so it can be trusted neither as a permission nor as a
fact, and the moment a verb branches on it a user can grant themselves whatever that branch guards.
A test scans the whole Lambda tree and fails if anything outside `ddl.py` (which writes it) and
`glue.py` (which excludes it) so much as references it. That scan reads the **parsed AST**: a
literal-only grep waves through `from cpcommon.ddl import PORTAL_MANAGED`, and a text scan flags the
comments that warn against confusing `portal.managed` with `portal-managed`. **Those two names are
one character apart and unrelated** — the dotted one is a table TBLPROPERTY that records and grants
nothing; the hyphenated one is the Lake Formation tag on DATABASES that is how control-plane roles
get `CREATE_TABLE` at all (`infra/modules/analytics/lakeformation.tf`). Every site of both carries a
comment saying so.

**What the shape checks are.** `cpcommon.glue.clone_definition` — moved here from `tscommon.glue`
because table-share asks the identical question — refuses views, non-external tables, catalog-
partitioned tables and unusable locations. The refresh path **maps** its four codes to its own
vocabulary at its call site rather than parameterising them (the stems differ, so no substitution
produces both sets), and asserts its mapping covers `clone_definition`'s whole set. That assertion
is load-bearing: `cpcommon.glue` now registers those codes itself, because `TerminalError` validates
at the raise site and they were previously registered only as an import side effect of
`tscommon.messages`, which a table-builder Lambda never imports. Registration is what lets the
refresh path speak — and its cost is that an **unmapped** code no longer explodes; it would sail
through as a valid terminal and resolve to the generic `unexpected_error`.

**Beyond the shape: the reconstruction needs two guards, and neither suffices alone.** SPEC-069's
declared partition keys are recorded nowhere but on the table, as `projection.*` properties, and
`build_create_table_ddl` requires the declared shape (it raises a bare `ValueError` on a Glue-shaped
key). So the verb rebuilds them and then **re-renders each one through the create path's own
renderer, demanding exact equality** — which catches a dropped property, a rewritten one (a
zero-padded bound), and any extra `projection.*` option. What it structurally cannot see is the
**column type**: Athena permits a projection over a wider set than this builder writes, and an
`integer` projection on a `string` column is precisely how a zero-padded partition gets declared.
That table round-trips *perfectly* and would be rebuilt as `int`, retyping the column while
reporting success. Table-level `storage.location.template` is refused for the same reason — it sits
outside the namespace the per-key round-trip compares. **The rule: a reconstruction that cannot be
performed is a refusal, not a guess.**

**Three ASL/marker traps worth carrying.** (1) **A `Choice` rule whose `Variable` path is ABSENT
raises `States.Runtime`, which no Catch anywhere can catch — it does not fall through to `Default`,
which covers only a value that is present and matching no rule.** So the one input `Default` exists
for is the one a bare `StringEquals` kills; both rules are `And` + `IsPresent`. (2) The same hazard
on the success side — `RecordSuccess` reads `$.mode` and a `Pass` state's JSONPath hard-fails the
same way — is closed by `execute-ddl` defaulting the field, since only a create reaches it; the
window is an execution starting after the state machine deploys but before the Lambda code does,
which would otherwise die *after* the table was created and the actor notified. (3) **Marking is an
explicit `mark` argument, never inferred from `storage is None`.** That inference reads correctly
against today's two callers and is wrong for the next: SPEC-144's `apply-refresh` is a `DROP` +
`CREATE` supplying a rebuilt `Storage`, so inference would strip the marker from every table a
refresh touched. Full account: `docs/spec-delivery/SPEC-143-refresh-table-contract-and-eligibility.md`.

### Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)

A refresh that would drop a column does **nothing** and fails terminally with `columns_removed`,
naming the columns in the notification. The user re-submits with `allowRemovals: true`. Removal is
singled out because it is the one class of change that breaks things somewhere the person who ran
the refresh is not looking: every saved query, view and dashboard referencing the column starts
failing, and nothing tells them.

**Two designs were rejected, and they are the two a later reader will propose.** *A plan-then-apply
pair* — run one writes a plan artifact into the user's prefix, notifies, the user clicks Apply, run
two references the plan. The textbook shape, and it costs a new artifact, a new index, a new view, a
new IAM surface and two async round trips for what the user experiences as one button. *A
browser-side preview* — the browser can already read the table's Glue columns and list the folder,
but it **cannot infer types**: that needs polars over a bounded Parquet footer or CSV head, which is
why `infer-schema` exists and carries a 240 MB layer. A preview showing guessed types would be a
preview of something other than what the apply does.

**What the chosen design guarantees, stated honestly:** the *specific columns* are named to the user
in a durable notification before any removal happens. It does **not** guarantee they read it —
SPEC-145's dialog requires an explicit tick with explicit consequence copy, and names the columns
when it can via the notification's link. Do not overclaim this as consent.

**Three things about the mechanism are load-bearing.** (1) **`allowRemovals` is validated, not
coerced** — a non-boolean is refused, because truthiness reads the string `"false"` as opting *in*,
on the one flag that authorises data loss. (2) It is **persisted nowhere** — not on the table, not in
a registry, not in an index; a test greps the Lambda tree for it. The flag authorises one run, and a
stored copy would carry that authorisation into a refresh nobody opted into. (3) **The notification
link is the only channel that names the columns to the browser**, and its column names are
**percent-encoded** — column names are NOT catalog-safe (`infer-schema` reads them verbatim from a
file header and nothing validates them), so `Order ID` puts a raw space in a URL and `&` invents a
query parameter. SPEC-145 must not re-validate them as identifiers: `CATALOG_IDENTIFIER_RE` rejects
`id`, `ts` and `Amount`, which would discard the whole link for most real tables.

> **Superseded in part by SPEC-149 (2026-08-04): the apply is no longer a DROP + CREATE.** It is a
> single in-place `glue:UpdateTable`, so the metadata loss described below no longer happens and the
> reason codes named in it are gone. Everything above this line — the opt-in, the refusal-as-warning,
> the three load-bearing mechanism points — is unchanged. See *The refresh apply replaces the
> definition in place* below.

**The apply WAS a DROP + CREATE, and what that cost is recorded in SPEC-144 FR-004** — table
identity, `Description`/`Owner` and any table-level Lake Formation grant were destroyed with the
catalog entry (column comments were carried). `ALTER TABLE ADD COLUMNS` cannot retype or remove, so it
would have covered only the easiest third. Full account:
`docs/spec-delivery/SPEC-144-refresh-table-schema-diff-and-apply.md`.

### The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)

`apply-refresh` issues **one `glue:UpdateTable`**, not two Athena statements. There is no moment at
which the user's table does not exist, no new catalog entry, and therefore no loss of table identity,
`Description`, `Owner` or table-level Lake Formation grants. A **failed update changes nothing**,
which is what retires SPEC-144's "a committed drop followed by exhausted retries notifies nobody"
exposure: there is no committed destructive step left to be silent about. It also stops the portal
entrenching a pattern it would have to unpick for Iceberg, where drop-and-recreate destroys the
snapshot history that is most of the reason to adopt it.

**The one thing to understand before touching this verb: it is a READ-MODIFY-WRITE on the live table,
never a rebuild from SPEC-143's capture.** `UpdateTable` replaces the WHOLE definition — a
`TableInput` omitting a field does not leave that field alone, it **clears it** — and
`clone_definition` never carried `Description` or `Owner` and deliberately strips `EXTERNAL`. Building
the input from the capture would delete exactly what the change exists to preserve. The verb reads the
live table immediately before writing it and mutates only the **columns** and the **`projection.*`
parameters**.

**Three mechanism points are load-bearing.** (1) The `TableInput` is an **allowlist projection** of
the live `Table`, pinned against botocore's service model by a test — `Table` returns 25 members and
`TableInput` accepts 14, so a denylist of the extras goes stale whenever AWS adds a field, and four of
today's eleven already postdate the obvious set. (2) **Column names are lowercased on write**, because
AWS documents that Athena folds names created through DDL — the create path gets the fold for free and
this path, bypassing Athena, must reproduce it or leave a mixed-case entry the create path could never
produce. (3) **`portal.managed` is re-asserted through `ddl.mark_managed`, never named in the verb**,
so SPEC-143's guard against a verb branching on a user-writable marker stays strict.

**IAM moved the right way: `glue:DeleteTable` was REMOVED, `glue:UpdateTable` added.** No verb on this
plane deletes a table any more, and a test greps the table-builder modules to keep it so. The explicit
`Deny s3:DeleteObject` is untouched — it never depended on the drop, and it outlives the mechanism
that prompted it. Lake Formation needed no change: the `portal-managed` table tag policy already
grants `ALTER`.

**What is NOT fixed, and must not be claimed:** the concurrent-refresh race is **reduced, not
closed**. The Pipe still starts executions `FIRE_AND_FORGET`, and **Glue offers no compare-and-set on
`UpdateTable`** — `VersionId` is documented only as "the version ID at which to update the table
contents", with no precondition-failure error. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions. A real fix is a serialization change to the Pipe.

> **Superseded in part by SPEC-157 (2026-08-09).** The race is now serialized by a per-table lock
> outside Glue, so the second refresh is refused rather than raced — the paragraph above stands as
> the state SPEC-149 left, not as the state today. What it says about Glue is still true and is
> exactly why the lock exists: `UpdateTable` has no compare-and-set, and `VersionId` is still not a
> precondition. The fix was NOT a Pipe change — see *A per-table lock serializes refresh* below.

Full account: `docs/spec-delivery/SPEC-149-refresh-table-in-place-rebuild.md`.

### A per-table lock serializes refresh, because the catalog cannot (SPEC-157)

Two refreshes of one table could overlap. `MessageGroupId` is the target database, so SQS serializes
*delivery* per database — but the Pipe starts the machine `FIRE_AND_FORGET`, so **delivery ordering is
not execution ordering**. SPEC-149 reduced the damage to last-write-wins between two definitions and
could not close it, because **Glue offers no compare-and-set on `UpdateTable`**.

**The serialization is a lock object in the admin bucket, claimed under ETag CAS**, one per
`{database}/{table}` under `locks/table-builder/`. The loser is **refused, not queued**: a held lock
means a refresh of that table is already running *against the same files*, so a queued run would pay a
full `inspect-source` to compute an identical definition. The refusal is a `TerminalError` through the
plane's existing notify path — the refusal **is** the notification.

**Two rejected alternatives, recorded so they are not re-proposed.** `REQUEST_RESPONSE` on the Pipe is
**impossible, not merely undesirable**: botocore's `pipes` model states that it "is not supported for
STANDARD state machine workflows", so making the Pipe synchronous means converting the machine to
EXPRESS — rejected on two independent grounds, its 5-minute ceiling against `inspect-source`, and its
**at-least-once** semantics, which would introduce the duplicate executions this spec exists to
prevent. A finer `MessageGroupId` would change nothing, because delivery is already ordered.

> **The PROTOCOL moved to `cpcommon.lock` (SPEC-187).** Everything below still describes what the
> table-builder's lock does and why; what changed is where the code lives. The three-way acquire, the
> 412/409 mapping, the staleness and future-date rules, the re-claim and the release-by-overwrite are
> now shared, and `tbcommon.table_lock` binds them to this plane's key, thresholds and wording. Its two
> suites were not rewritten — the protocol moved out from under them — which is what makes the move
> provably behaviour-preserving.

**The lock releases by OVERWRITING, and that is forced rather than chosen.** The execution role
carries an explicit `Deny` on `s3:DeleteObject` for the whole admin bucket, which SPEC-149 kept when it
removed `glue:DeleteTable`. Releasing by deletion would mean amending a standing safety property for an
implementation convenience, so **"free" is a state of the object, not its absence**.

**The holder is the EXECUTION ARN and must never be the request id.** A request id identifies the
*message*; Pipes delivery is at-least-once, so a redelivered message runs a second execution carrying
the same id — and the re-entrancy branch (which exists so an SFN Task retry does not self-refuse) would
hand the lock to both, silently. The ARN reaches the verb through a `Pass` state, **not** the task's own
`Parameters`: reading `$$` there means building an object, which wraps the payload, and every
notification path in this plane reads the request at the **top level** of the event.

**A lock is stealable only because executions are bounded, so the bound came first.** The machine had
no `TimeoutSeconds` — a Standard execution may run for a year, against which no age threshold is
defensible. It is a **top-level field of the ASL**, not a resource argument (`aws_sfn_state_machine`
has none; `tofu validate` rejects it). A malformed body, an unparseable stamp and a **future-dated**
one are all stolen: a timestamp that cannot be true is no evidence a refresh is running, and the
alternative is a table that can never be refreshed again.

**The freshness guard narrows the residual window and does not close it.** `apply-refresh` compares the
`UpdateTime` captured at the start of the run against its own pre-write read. **A moved stamp is not by
itself another writer** — the state retries on faults that can fire *after* the update committed, so
the retry re-reads a table whose stamp this run moved; judging on the stamp alone failed a run that had
already succeeded and sent the user a notification contradicting the success one. The columns settle
it: a live table already carrying what this run intends to write was written by this run.

Full account: `docs/spec-delivery/SPEC-157-serialize-concurrent-table-refresh.md`.

### Every DDL literal goes through `literal()` (SPEC-151)

`cpcommon.ddl` renders **every** string literal in a `CREATE EXTERNAL TABLE` through `literal()` —
`TBLPROPERTIES` keys and values and the `LOCATION`, alongside the column comments that already did.
Raw `f"'{value}'"` is forbidden in DDL construction.

The demonstrated consequence of the old form: a partition enum value of
`eu','projection.enabled'='false` rendered as
`'projection.region.values'='eu','projection.enabled'='false'`, **injecting a property that switched
partition projection off**. Blast radius is **self-scoped** — a user can only reach a table in their
own database and Athena rejects multi-statement DDL — so this is robustness, not cross-tenant
escalation. The sharper everyday path is data-quality, where the `LOCATION` and the partition values
both come from **S3 key segments**: a folder named `year=2024'` or `o'brien` broke the temp-table DDL
and killed the whole check as `query_failed`.

**Two escapers exist and must not be confused.** `cpcommon.ddl.literal` escapes with a **backslash**,
which is Hive's rule and what Athena parses `CREATE`/`DROP` with. `dqcommon.sql._literal_dml` **doubles
the quote**, which is Trino's rule and what Athena parses `SELECT` with. Using the Hive form in a
query would render a backslash into the S3 path being matched, and the predicate would silently match
nothing. Each lives in its own module with a docstring saying so; `tscommon.ddl._lit` is the
table-share twin of the DDL one and has always done this.

Ordinary values render **byte-identically** to the old form, which is why the golden-DDL tests are
untouched — a rendering change that moved any existing statement would have been a different and much
riskier decision.

**Corroborated, not demonstrated:** the escaped form has never been exercised against Athena itself.
The tests assert the rendered string. If a `'` in a partition segment ever still fails, suspect the
engine's acceptance of `\'` before suspecting the renderer.

### A generalized signature is the whole point of the second extraction, and one moved constant must not be renamed (SPEC-177)

`features/saved-queries/` is the arc's second extraction and it follows SPEC-176's shape exactly:
the `.sql` store — the service, the space memory, the pager, the save flow — came out of
`features/query/` before its second consumer exists, with no user-visible change and nothing live
owed. The reasoning in the SPEC-176 entry above applies unchanged; what follows is only what is
different here.

**The one deliberate signature change is what makes the extraction worth doing.** `useSaveQuery`
took `activeTab: QueryTab` — a shape the Data Explorer cannot produce, since it has no tabs. Moving
the module without changing it would have left SPEC-183 reimplementing the collision-and-confirm
path SPEC-175 spent a whole spec getting right: validate, `ensureSavedQueriesFolder` on the CHOSEN
space, write, the `Collision` round-trip that survives a cancelled Replace, the inline failure that
leaves the dialog open with the destination intact. So it takes `{sql, link}` — the two fields the
flow actually reads — and the Query workspace passes `{sql: activeTab.sql, link: activeTab.savedQuery}`
at the call site. An extraction that moves a module but leaves it unusable by the second consumer
has not extracted anything.

**`onSaved` keeps its second argument, against the spec's own Data Model.** The spec sketched
`onSaved: (link: SavedQueryLink) => void`; it ships as `(query: SavedQuery, sql: string) => void`,
because the workspace clears its dirty marker with `rememberSavedSql(query.key, sql)` — against the
bytes that were **written**, not against whatever the buffer holds by the time an async write
returns. Dropping the body would have changed workspace behaviour, which FR-002 AC2 forbids. A
`SavedQuery` is structurally a `SavedQueryLink` plus two fields, so a caller needing only the link
is served by the wider callback; a caller needing the body cannot be served by the narrower one.

**`QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` moved without being renamed, and its VALUE is the reason.**
`s3portal.query.savedQuerySpace.` is a live `sessionStorage` key. The `query.` segment describes
where the module used to live, which is exactly the kind of thing a move invites tidying — and
tidying it silently discards every user's remembered space on the deploy that ships it. The constant
name and the string are both untouched; the docstring says why.

**The layering rule gained a third participant and its message had to change with it.** SPEC-176's
clause governs `features/query/` ↔ `features/data-explorer/` and the layer below them;
`features/saved-queries/` joins on the same footing — it may import neither sibling, while
`features/query/` importing the store stays open (`saved-queries` appears in no `group` pattern).
The rule was verified the only way this rule can be verified — by committing a violation in the
**relative** form a sibling actually produces (`'../query/useQueryTabs'`) and watching lint fail,
in each of the four directions. Reading the config proves nothing; SPEC-176's first version resolved
onto the right files and caught nothing.

**One a11y test had to split rather than move.** `saveQuery.a11y.test.tsx` drove the Replace confirm
through `QueryDialogs`, which is a Query workspace component and stays. Moving the file whole would
have made the new feature's own test suite the rule's first violation. The three dialog passes moved
with the dialog; the confirm pass became `features/query/queryDialogs.a11y.test.tsx`, assertions
byte-identical.

### The renderer's signature is the rule, and the browser's first SQL value interpolation is two gates wide (SPEC-178)

The Data Explorer reduces to one idea: a user's grid gestures are a *description of a query*, and
the app renders that description and runs it. SPEC-178 builds that engine with no route, no grid
and nothing a user can see, because it settles two things that would be expensive to get wrong
after five specs have built on them.

**Filter, order and grouping render SQL; everything else is presentation — and that is enforced by
a PARAMETER LIST, not by discipline.** `renderExplorationSql(source, query)` takes two arguments,
so column visibility, order, pinning, width and SPEC-184's colours and transformers are not merely
documented as unable to change the SQL: they are unreachable from the function that renders it. A
later edit cannot make the projection depend on which columns are visible without changing the
signature, which is a change a reviewer sees. `SELECT *` always follows. The rejected optimization
is recorded rather than left as an apparent inefficiency: narrowing the projection to the visible
columns would cut bytes scanned substantially on Parquet, and would turn un-hiding a column into a
billed, several-second re-run — cost depending on a gesture users read as cosmetic. Predictable
cost wins. A feature-scoped AST-style sweep forbids a second builder; a **repo-wide** one was
specified and is not achievable, since `useTableActions`, `useRunDdl` and `CreateViewDialog` build
real DDL today and `DEFAULT_SQL` is `SELECT 1;` — a sweep exempting three legitimate builders would
prove nothing about the fourth.

**This is the first place the browser interpolates a user-supplied VALUE into SQL, and the escaper
is the Trino/DML one.** Everything the portal built before is either typed into Monaco or assembled
from identifiers already validated against `CATALOG_IDENTIFIER_RE`; a filter value is neither.
`lib/sql.ts`'s `sqlLiteral` **doubles the quote** and is not `cpcommon.ddl.literal`, which
backslashes for Hive — the repo's "two escapers, never confused" note gains its TypeScript half
here, and the failure mode of confusing them is the bad one: no error, just a predicate that
silently never matches. The raw expression bar does **not** relax this and the asymmetry is the one
thing a reader must not get backwards — the bar is the *user's own SQL* and passes through
verbatim, as Monaco's does, while a filter value arrives *from data* and is quoted on their behalf.
A cell containing `O'Brien` filtered by one click is the whole hazard, and it arrives from real
data long before anyone thinks to type it.

**The spec's own filter model would not have worked, and nothing offline would have caught it.**
`value?: string` with every value quoted renders `WHERE "qty" > '5'`, and Trino does not coerce
varchar to bigint — a *query-time* error, invisible on the CSV-derived tables the Table Builder
makes all-string, surfacing on the first Parquet table. `ColumnFilter` therefore carries an optional
`valueKind`, and `'number'` renders **bare**; the repo's own Trino renderer already does exactly
this (`dqcommon/sql.py` interpolates a count unquoted beside a `_literal_dml`-quoted path). The bare
value is the one thing the renderer does not escape, so what admits it IS the trust boundary, and it
is **two gates**: a bounded charset, which is load-bearing rather than a fast path because `Number`
alone accepts `0x1f`, `0b11` and `Infinity`; and `Number.isFinite`, because a hand-written numeric
grammar is exactly the thing that is subtly wrong — the first one written here tripped
`security/detect-unsafe-regex`, and deferring to the engine's own parser is both safer and shorter.
A value failing either gate is **refused, never quoted as a fallback**, since quoting restores the
type error the kind exists to prevent.

**One execution per distinct rendered SQL, and the failed one is evicted on the way OUT.** The
rendered SQL is the cache key, which makes the cache the cost control: an identical description is a
cache hit, so changing a filter and changing it back is free, and paging *within* an execution
scans no extra bytes. Requiring that a re-applied description **retry** after a failure is the
subtle part — evicting on observing `FAILED`, with an observer still mounted, refetches
immediately, which is start → FAILED → evict → start, an **unbounded loop against
StartQueryExecution** on any permanently-bad statement. The eviction happens in the effect cleanup,
when the statement changes or the hook unmounts. **Be precise about what that loop costs**: AWS does
not bill a FAILED Athena query, so the first cost is the API hammering and the account-wide query
concurrency it consumes — but the same branch covers **CANCELLED**, which *is* billed for whatever it
scanned before it stopped, so a loop over a statement the user keeps stopping bills every pass. A
paired test asserts a SUCCEEDED
execution is *not* evicted, because an unconditional eviction makes every remount a fresh bill and
the failure test alone would still pass.

**A tab's cost ledger is keyed by execution id rather than accumulated**, which makes "a cache hit
adds nothing" true by construction — a re-rendered identical statement resolves to an id already in
the map. A running total would have to *detect* a hit, and a detector can be wrong in the direction
that overcharges. Athena offers no pre-flight estimate, so reporting after the fact is the only cost
signal the feature can give.

**`ExplorationSource` is a union from the outset with only the `table` arm reachable for five
specs.** A saved `.sql` file cannot be reverse-engineered into a table plus filters without a SQL
parser, so SPEC-183's loaded file is a **source**, not a view state; filters, ordering and grouping
compose over either arm without knowing which. Retrofitting the union at 183 would have touched
every spec in between.

### A space maps to ONE database, so the picker has no database step — and a deep link resolves without asking (SPEC-179)

The Data Explorer's front door. FR-005 specified the picker as *space → database → table*, and the
middle step does not exist in this codebase: a space maps to exactly **one** Glue database — the
personal space to the username, a shared space to its own name, both built by `useConnections` — so
the control would have offered a single option, which is the one-option control SPEC-163 declined to
render for the share dialog's recipient kind. The picker is two panes with the database **shown**
beside its space, and `spaceDatabase()` is the single definition of the mapping. `?db=` survives in
the deep link as a **cross-check rather than a choice**: a link naming a database that is not that
space's resolves to nothing and opens the picker.

FR-005 AC3's "a database the user cannot see is absent rather than present-and-failing" therefore
lands one step later than its wording implies. The space list comes from **memberships**, which are
known reachable; an unreadable database renders an explanation instead of a failing table list. No
table is ever offered that cannot be read, which is the property the AC is protecting.

**The deep link resolves from the LIST, never by probing** (SPEC-113's rule, applied to the
catalog). `denied` and `none` are deliberately different states: a named space this user cannot
reach renders a refusal, while anything malformed opens the picker — an error page for a bad
parameter would tell a user their correct-looking link is broken when the honest answer is "pick
something". Own username always wins over a same-named shared space, mirroring
`useDataQualityReport`'s `resolveSpace`, and `?space=` is **not read at all** with
`sharedWorkspaces` off — never resolved-then-fallen-back, because a "we sent you somewhere else"
banner over a parameter that was never consulted would be a lie (SPEC-167's rule).

**The page must not mount the picker while a link is still resolving, and this was found by a test
rather than by design.** `useConnections` reports loading before the shared spaces arrive; the
workspace rendered the picker meanwhile, and the picker reads the *personal* space's database on
mount — so a denied link issued a Glue call and swapped to the refusal a tick later. Still an answer
about a catalog, just about the wrong space. `LoadingState` now holds the page while a resolution is
pending, and the hook reports `loading` **only when a `?space=` is actually present**: without one
there is nothing to wait for, and a blanket wait would put a spinner in front of every visit to
`/explore`. This is `FeatureRoute`'s own rule one layer down. The parameters are then **dropped with
`replace`** once acted on — tabs survive a reload through `sessionStorage`, so a link left in the URL
would stack a duplicate of the linked table on every reload.

**One surface, registered under TWO flags.** *Explore data* on the Query rail is the mirror image of
"Create table": a Data Explorer capability living on a Query-workspace surface. It is gated by
`dataExplorer && query` and carries a row under each, because either gate can be deleted alone and a
single row would leave the other unwatched. Verified by violation — dropping `explorerEnabled`
reddened both the walking test and the menu-shape test that asserts the **rest of the menu is
unchanged** with the flag off, which is the half the walking test cannot see: a conditional written
one bracket wide takes Refresh table and Share table with it while "the item is gone" still passes.

**Adding a flag key lands in SIX places and two of them are Python.** The spec named the publish
workflow's matrix; the matrix is per **environment**, not per flag, and needed no edit. The two that
matter are `scripts/validate_feature_flags.py`, which refuses an unknown key — without it the publish
job would have failed on the very document the key was added to — and
`lambdas/test_feature_flags_config.py`, which **re-states the same tuple on purpose** so a test
cannot pass by agreeing with a mistake it imported. That second one went red on CI: this repo's four
named local gates (`format:check`, `lint`, `build`, vitest) run no pytest, so **a change touching
`scripts/` or `lambdas/` needs `pytest lambdas/` before the push**, not just `ruff`.
`FEATURE_FLAG_KEYS` **order** is load-bearing beyond iteration: `FeatureRoute` offers the first
ENABLED feature as its fallback link, so a new key goes **last** or an existing unavailable page
silently changes where it points.

**An unsettled link must run NOTHING, and "denied" is not the same condition.** Review measured a
real `StartQueryExecution` behind the refusal: the guard read `denied ? null : …`, and `denied` is
false during the resolution window, so a tab restored from `sessionStorage` started a billed query
for a page that then rendered only the refusal. FR-006 AC2's letter survived — the execution is
against the user's *own* table and no Glue call is made — but cost is this feature's declared
through-line, so the guard is now "the link is not settled". The connections read that resolution is
*made of* stays: it is the user's own cache of their own memberships, the same document
`useDataQualityReport` reads on the same path, and no request touches the space named in the link.

**A tab's close control may not be a `<button>`, because it lives inside `role="tab"`.**
`ExplorationTabStrip` shipped one and tripped axe's `nested-interactive` — the exact arrangement
`QueryTabStrip`'s comments forbid, in a component whose own docstring claimed to mirror it. The ✕ is
a non-focusable `role="presentation"` span and **Delete on the focused tab** is the operable path
(WCAG 2.1.1). The feature had **no axe assertion at all** while 19 other feature suites have one;
that absence is what let a violation ship past a review of the markup.

### Calc computes what only the browser has, grouping computes what only Athena can, and the percentage says which page it is of (SPEC-182)

Two panels that look like siblings and are the opposite of one another. The split is not a
compromise between fidelity and cost — it falls out of what each panel *is*, and everything else in
the spec follows from getting that right.

**Calc is client-side because a selection is client state.** It aggregates the cells the user has
selected, and those exist nowhere but the browser, so a server-side Calc means a billed
`StartQueryExecution` **per selection change** — for a gesture as cheap as dragging across ten
cells. Grouping is the mirror image: aggregating in the browser would aggregate whichever rows
happened to have been fetched, which is the scale lie the whole feature was designed to avoid. So
Calc issues **zero** executions (asserted by count, FR-001 AC7) and grouping mints exactly one per
apply, however many columns and aggregates changed — which it gets for free by staging a draft and
going through SPEC-181's single `apply`.

Because Calc's numbers are true only of loaded, selected cells, the panel **says so every time it
says anything**: `calcScopeText` renders "N selected cells on this page", and none of those words
are droppable. With nothing selected it explains itself rather than showing zeroes — a column of
`0`s reads as a computed answer to a question nobody asked. The numeric predicate is the renderer's
own `isBareNumeric` rather than a second rule, so the panel and the filter cannot disagree about
which cells are numbers; a `count` of an empty set is `0` and an empty `sum` is `0` (both real
answers) while every other function shows a no-value marker, which is the guard that is easy to draw
one line too wide.

**The percentage is of the rows on the CURRENT PAGE, and its column header says so.** Only one page
of a result is in the browser — `useQueryResults` exposes exactly one — so a share computed here is
a share of those rows and nothing else. A column headed `% of count_all` beside a paged result would
be read as a share of the table, which is precisely the class of claim grouping exists to prevent,
so the header is `% of count_all (this page)`. The alternative, a windowed total in the SQL, is a
second scan of the same data for a column the user asked only to *see*; the flag renders no SQL at
all, and a test pins that. It rides on `Grouping` rather than on `ExplorationPresentation` even so:
it is meaningless apart from the grouping it describes, and a grouping restored from
`sessionStorage` has to restore whole.

**Grouping mode is exactly "at least one grouping column".** A grouping with aggregates and no
columns is legal SQL — a global aggregate — but FR-003 AC6 says removing every column leaves
grouping mode, and the alternative reading strands the user in a mode with nothing in it. So
`setGrouping` maps an empty-column grouping to `null`, and **leaving grouping mode drops any sort on
an aggregate's output column**: `count_all` exists only while the grouping does, so carrying that
`ORDER BY` onto the raw table is a query Athena rejects — and it would also miss the cached ungrouped
execution AC6 promises to return to. That is the half of AC6 the spec does not mention and the whole
of what makes it work.

**`groupingOrderingViolation` is exported for the same reason `isBareNumeric` was.** Trino rejects an
`ORDER BY` on a column that is neither grouped nor aggregated, and the renderer refuses it first —
but that refusal is an `ExplorationRenderError` naming a column and an operator, which SPEC-106
forbids showing a user. So the rule returns the offending **column** and the two callers word it
differently: operator text in the renderer, a sentence naming the sort to clear on the panel's Apply
(`Button.disabledReason` — `aria-disabled`, reachable rather than hover-only). A second rule at the
panel is a rule that can disagree, and the way it would disagree is a grouping the panel accepts and
the renderer throws on, which takes the whole exploration to an error banner. The refusal belongs on
Apply because that is where the conflict is *built* — sort a column, then group it away.

**But the panel's Apply is not the only guard the rule needs, and this spec falsified its own premise
in the same commit.** "While a grouping is in force the grid shows only the grouping columns and the
aggregates" stopped being true the moment the percentage column was appended: it is a real
`GridColumn`, so it gets a header menu, a row in the settings dialog (the ONLY sort/filter path below
`tablet`) and the toolbar's *Filter by this value* — and it exists in no statement, so sorting it is
a description the renderer REFUSES and filtering it is a `COLUMN_NOT_FOUND`. `ColumnQueryActions`
therefore carries **`queryRefusalOf`**, asked by every per-column surface before it offers a filter
or a sort; the header menu opens and states the reason rather than offering controls that each fail,
while Show, Pin, width and order stay available, because geometry applies to a calculated column like
any other. The lesson generalises past this column: **appending anything to `columns` before
`useColumnGeometry` hands it every affordance a real column has**, and the grid has no other way to
tell the two apart.

The same reachability argument closed a second hole. `assertGroupingIsRenderable` compared aggregate
aliases with each other and not with the **grouping columns**, which are projected beside them under
their own names — so grouping by a column called `count_all` while `COUNT(*)` is present produced two
result columns of one name, sharing one geometry key and leaving `groupingOrderingViolation` to
answer for whichever the reader meant. Unreachable before this spec, because nothing let a user
choose what to group by. `groupingNameCollision` is now the renderer's rule, exported on the same
precedent, and the panel refuses at the gesture.

**Both panels are `<aside>`s, not `Drawer`s, and that is structural rather than stylistic.** A
`Drawer` traps focus. Calc has to recompute as the selection changes and grouping takes a column
**dragged from a grid header**, so a focus trap would put the grid out of reach of the panel that
needs it. The dragged column travels by an additive `onColumnDrag` callback rather than through
`dataTransfer`, for the reason the header's own reorder ref already exists: `DataTransfer` is not
implemented everywhere, and a drop handler that depends on it works in a browser and nowhere else.
The panel is also offered the **source's** columns while a grouping is active, not the result's —
the result's are the grouping columns and the aggregate aliases by then, and offering those would
let a user group by `count_all`, a column that exists only inside the query it would be added to.

**The disclosure shows the string the execution used, never a second rendering of it.**
`useExploration` renders once, runs that string and returns it; `GeneratedSqlDisclosure` shows that
value. Re-deriving it for display is one `renderExplorationSql` call away and would drift the moment
a caller passed a slightly different description — and a disclosure that is right most of the time
is worse than none, because it would be believed. It is available whether or not grouping is active:
the Explorer writes SQL the user did not, grouped or otherwise, and every statement it writes is an
invoice.

**Calc opens on MIXED aggregation, and that default is not cosmetic.** Numbers-only narrows every
function, so a numbers-only default answers `Count 0` over a selection of three text cells — printed
directly under "3 selected cells on this page", which is the one pair of numbers this panel must
never show together. The toggle still narrows everything when a user asks for it; what changed is
which reading is the default.

Two smaller things worth carrying. `canonical()` folds the grouping's two new flags **explicitly**
and `readExplorationTabsState` normalises them (absent ⇒ false) — needed together, because a
document written before this spec carries neither flag and an absent flag comparing unequal to
`false` would push a history entry for an apply that changed nothing; the validator accepts them
absent rather than requiring them, since requiring them would discard **every tab** in the document
over a field that did not exist when it was written. And `CalcPanelState` is region state, not tab
state: it describes a selection, and a selection does not survive a page change, let alone a session.

---

### A saved exploration follows the flag that owns the STORE, not the one that owns the screen (SPEC-183)

An exploration can be saved as a `.sql` file through SPEC-177's generalized flow. The body written
is the **rendered** SQL — the exact string `useExploration` handed `StartQueryExecution`, not a
second rendering of the description — because what the user is looking at is what the file should
reproduce, and saving the bare `SELECT *` would produce a file that reopens as something they did
not save. `SaveExplorationDialog` is a thin host over `SaveQueryDialog`: every rule about names,
destinations, collisions and in-place replacement stays in `useSaveQuery`, which is what SPEC-177's
`{sql, link}` signature was for.

**The gate is `query`, not `dataExplorer`, and the registry is what found it.** Registering the
control under `dataExplorer` reads naturally — it is a Data Explorer control on a Data Explorer
surface — and the walking test failed it immediately, because there was no gate to find: `/explore`
already hides the whole workspace, so the row asserted nothing. The right question is not which
screen a control is on but which feature it belongs to, and this is the exact mirror of SPEC-179's
**Explore data** on the Query rail. With `query` off there is no editor to open a `.sql` file in and
SPEC-173's `saved_queries` folder has already left both the file browser and the destination picker,
so a file written from here lands somewhere the user cannot see, open or delete — the failure
"Create table" is on the `query` list for. The control is **removed** with the flag rather than
disabled: a `disabledReason` would explain a state the user has no way to change.

**A save mints a link even though a load cannot.** `ExplorationTab.savedQuery` is written by
`setTabSavedQuery` on success, **by tab id** — the write is async and a tab switch behind it would
link the wrong tab, whose next re-save would then replace a file it has nothing to do with. Without
it, every SPEC-175 rule about in-place replacement would be vacuously satisfied by a predicate that
is permanently false. It does **not** rename the tab: a Query workspace tab IS its buffer, so a save
renames it; an exploration tab is named for the source it is exploring, which a save does not
change. Restored all-four-fields-or-none, so a document written before this spec restores the tab
without a link rather than being discarded (SPEC-182's precedent).

**A FAILED exploration is refused, and it is the case that has teeth.** The obvious refusal —
"there is no statement" — is keyed on a null `sql`, and a failed apply has a perfectly good one: the
statement Athena rejected. Meanwhile `ExplorationResultsRegion` has deliberately fallen back to the
LAST GOOD execution's rows (SPEC-181), so the grid on screen belongs to a different query. Saving
there writes the rejected statement under a name whose rows the user was reading from somewhere
else, and the file then fails to open in the Query workspace this decision promises it opens in. It
is **not** the suspended state and cannot be folded into it: SPEC-181 suspends only on a *history
step* onto a known-bad statement, so the FIRST failure is exactly the window in which Save is
offered. It is checked first, and worded apart, because something did run.

**The sidecar stays rejected.** A JSON document beside the `.sql` file, carrying the exploration's
view state so a saved exploration could reload as an exploration, would reintroduce exactly the JSON
store SPEC-173 deleted — plus a second artifact to keep in sync with a file users can freely rename,
edit, copy or delete from the file browser. The guard is a count: a save issues **exactly one
`PutObject`**, asserted over a space whose folder marker already exists, so the number is a statement
about sidecars rather than about folder creation.

**Loading a `.sql` file as a source was descoped during build (2026-08-13, user decision) and is
deferred to a later spec.** The `sql` arm of `ExplorationSource` stays as SPEC-178 left it,
unreachable; nothing was half-built for it. One thing that arc will have to face first:
`splitSqlStatements` lives in `features/query/query.sql.ts`, which `features/data-explorer/` may not
import (SPEC-176's sibling rule), and the refusals a wrapped subquery needs are built on it. The
answer is to move the lexer down into `lib/sql.ts`, whose own docstring already claims language
rules rather than feature domain — not to write a second one.

---

### Results are read only at SUCCEEDED, and `isPending` is not a substitute (2026-08-16)

**Found by running the live-check script against deployed prod, not by review.** Opening a table in
the Data Explorer occasionally showed *"Something went wrong. Contact the Administrator."* on an
ordinary first load.

`ExplorationResultsRegion` handed `useQueryResults` the execution id the moment
`StartQueryExecution` returned, with no gate on the query having finished. `GetQueryResults` against
a QUEUED execution is **400 `InvalidRequestException` / `INVALID_QUERY_EXECUTION_STATE`, "Query has
not yet finished"** — a name in no `CODE_RULE` whose message matched no `MATCH_RULE`, so
`toUserMessage` returned the **generic fallback**. The most alarming sentence the app owns, for a
transient race of our own making.

**`useQueryResults` already documented the contract** — "a pager over a **succeeded** query's
results" — and cannot enforce it, because it is handed an id and never sees the state. So the
contract is kept at the caller, and the caller is now the only place it can be broken.

**`isPending` looks like the obvious gate and is wrong, which is the part worth carrying.** Between
`StartQueryExecution` resolving and the FIRST poll landing, `state` is still `null`, so
`isPending`'s `state !== null && !isTerminalState(state)` clause is *already false*. That window is
exactly where the race lived: gating on `isPending` leaves the bug in place while looking fixed.
The region therefore takes `state` as a prop.

**It read as intermittent, and the reason generalises.** The race fired on **every** load; what
varied was whether TanStack's `retry: 1` re-asked before or after the query finished. A bug that
self-heals on retry presents as flaky and hides in exactly the place a rendering assertion would
look — so **the guard asserts on the CALL, not the screen**, and was verified by reverting the gate
(`expected getQueryResults to not be called at all, but actually been called 1 times`).

**The mapping rule is defence in depth and is matched on the MESSAGE, never the name.**
`InvalidRequestException` is also the name for a rejected MALFORMED_QUERY, and a `code` rule
outranks every message rule — keying on the name would have turned a rejected-at-submit syntax error
into "still running". (An execution that reaches FAILED arrives as `code: 'FAILED'` and was never at
risk.) Rule ordering is **not** load-bearing; the two regexes are disjoint, measured.

**`QueryWorkspace` was never affected** — `displayedResultTab` is null unless the batch is done, and
result tabs are only pushed at SUCCEEDED.

**Two consequences left standing.** While a statement runs the status line now says **"Running…"**
where it said "Loading rows…" — the old text was wrong, and wrong *because* the app really was
fetching rows then. And a query outliving `MAX_POLL_DURATION_MS` (5 min) now shows an indefinite
"Running…" rather than a permanent wrong error banner; neither self-heals, and the behaviour is
unspecified.

### A stale result must not be served at all, so the eviction reaches the tab in front of you (2026-08-19)

The Data Explorer caches an Athena execution at `staleTime: Infinity, gcTime: Infinity`, keyed by
the SQL it rendered. That cache **is** the cost control — changing a filter and changing it back is
a hit rather than a second bill. What it could not see is a table dropped and rebuilt over
different data under the same name: the SQL renders byte-identical, so the entry stayed a hit and
the pre-rebuild rows came back for the rest of the session, with nothing on the page able to ask
otherwise.

**It evicts what is on screen, and a reload fixing it is not a fix.** The first attempt spared
observed entries to avoid a second billed `StartQueryExecution` — measured, 2 calls where there
should be 1 — which left the tab in front of the user showing old rows until they came back to it.
That is the bug, quieter. `resetQueries` rather than `removeQueries`: removal only re-runs an
observed query if something re-renders afterwards, and in the app something usually does (a toast,
a dialog closing), which is exactly the accident correctness must not rest on.

**The narrowing is what makes that affordable.** The execution key carries the TABLE, and
`invalidateSchema(client, db, table?)` takes the table its caller changed. Dropping the table you
are exploring re-runs it; creating a view beside it does not. Only a change that names no table
falls back to the whole database — an arbitrary DDL statement the user typed and the rail's own
refresh button, both of which ARE requests to re-read everything. A caller that could name its
table and does not is a bug in that caller.

**The rebuild had a second road in, and it was the reported one.** A table build is asynchronous:
the browser enqueues and the table appears minutes later, announced by a notification nothing in
the tab hears. So dropping invalidated and rebuilding did not. `armCatalogCatchUp` is **module
state drained by a listener mounted once in `ProtectedLayout`** — held per component, the arm died
with the control that set it, and both controls that enqueue a build unmount when the user leaves
that route. Residual: `focus` fires on blur→focus only, so a user who never leaves the window gets
no catch-up until they do.

**A registration, not a call beside each `invalidateSchema` site.** `features/catalog/` reaching
into `features/data-explorer/` is the undeclared shared layer pointing the wrong way; five call
sites is five things to forget, and the sixth would be written by someone who had never heard of
this cache. Not a query-cache subscription either: TanStack emits no event for invalidating a key
nothing has cached, and the rail's schema is not always loaded when DDL runs.

### A column name is user data, and the renderer must be safe without it being validated (2026-08-19)

Column names are the one part of a schema this portal does not choose — they are read out of a
file's own header or Parquet footer. Nothing judged them, and Glue accepts what Athena then cannot
read: the result is not a failed build but a table that is CREATED, appears in the rail, and fails
or returns nothing when queried.

`cpcommon.columns` is one rule shared by both planes that infer a schema. It refuses an empty name
(a blank CSV header cell), leading or trailing whitespace, anything outside `[a-z0-9_]` after the
fold, over Glue's 255, and two names that fold to the same lowercase string — the last being the
one that reads as a portal bug rather than a file bug, because `Total` and `TOTAL` are two columns
to every tool the user has and one column to Athena. It ALLOWS a leading digit, a leading
underscore and a reserved word: those are what the quoters exist for.

**The blanket `[a-z0-9_]` is stricter than AWS documents, and that is a product decision, not an
oversight.** `Order ID` builds and queries today. It is refused so that one rule holds everywhere
rather than a narrower one holding until someone writes a query by hand without the quoting this
app applies for them. Reversing it is a change to one regex.

**Creates only.** A refresh re-derives the columns of a table that already exists, so refusing one
would break every refresh of a table built before the rule and leave rewriting the source files as
the only repair. It selects on the storage descriptor, not on `mode` — a tripwire forbids the
shared verbs reading that field, because the moment one does, "a refresh reuses these verbs
unchanged" stops being true.

**The rule is not what makes the renderer safe.** `cpcommon.ddl.quote` now doubles an embedded
backtick, as `quote_dml` always did for the double quote. A renderer that is safe only because
someone else validated first is one refactor from not being safe — and data-quality proved it:
its partition keys are derived from S3 path segments, so a folder named ``ab`c=eu`` put a backtick
straight into `PARTITIONED BY`. Those keys are checked too, under their **own** reason code: the
repair is renaming a folder, and a user told to fix a column name goes looking in the wrong place.

### Athena's two dialects need two escapers in the browser, and the second was missing (2026-08-19)

`CREATE VIEW` is Trino (double quotes); `DROP TABLE` / `DROP VIEW` is Hive (backticks, an inner
backtick doubled). The browser had only `lib/sql.ts` `sqlIdentifier`, the Trino one, so both
statements interpolated their identifiers raw.

The identifier that matters is the **database**. A view or table name is typed into a dialog held
to `CATALOG_IDENTIFIER_RE`; a shared space's name is held to nothing the browser cannot bypass —
`shared-space-validate` applies **no format check** to `space` on the create path, and the SPA
talks to its queue directly. A crafted space name reaches a member's space list and from there
into DDL, under their own Athena credentials.

Both statements are quoted now, each with its own dialect's escaper (`sqlIdentifier` /
`sqlDdlIdentifier`). The lesson that generalises is the ordering: `buildCreateViewSql` was fixed
first and `DROP` two functions down was left live for a commit — **a quoting fix is not done until
every statement built from the same value is swept**, because the second one is the one nobody
tests against a real engine.

### A table's LOCATION is read recursively, so the space root is not a data folder (2026-08-19)

AWS is explicit: "Athena reads *all* data stored in the Amazon S3 folder that you specify." A table
built at a space root therefore covers `athenaresults/`, `saved_queries/`, `user_settings/`,
`shared_files/`, `shared_tables/` and `archive/` as well as the user's own data. It does not fail —
it **succeeds**, and every later read returns the portal's own bookkeeping mixed into the answer.
Succeeding is what makes it worth blocking rather than warning about.

Refused on the control with its reason (`createTableRefusal`, on `writeLockRefusal`'s
predicate-with-its-words precedent) and in `validate-authorize` as `location_is_space_root`. A
refusal rather than a hidden control: the button is where a user standing at the root looks for it,
and a control that vanishes teaches nothing about where to go instead. **Creates only** — a refresh
reads the location the table already has, so refusing one would strand any root table already in a
catalog with no way to repair it.

## Archive and restore — the only place a mistake is unrecoverable

### The archive vault, and the four choices that shape the whole arc (SPEC-168)

### `GLACIER`, and why the other two were rejected

`arcommon.config.ARCHIVE_STORAGE_CLASS` is the single definition, and it determines the shape of
every spec after it. **`GLACIER` (Flexible Retrieval) is not readable**: a `CopyObject` whose source
is in it fails `InvalidObjectState`, so a restore is not a copy — it is `RestoreObject`, a 3-5 hour
wait, and *then* a copy. That is why SPEC-171 grows a `Wait`/poll loop no other plane in this repo
has, and why 170 must land before it.

**`GLACIER_IR` was rejected precisely because it would have removed all of that.** It is readable in
real time, which deletes the restore machinery entirely — and it is the most expensive Glacier
class. An archive the user can still read on demand is not an archive; it is data moved to a cheaper
bucket, and the feature's whole premise is that putting something away is deliberate and reversing
it is slow. **`DEEP_ARCHIVE` was rejected the other way**: ~4x cheaper again, but 12-48 hours to
restore and a **180-day** minimum, which turns an ordinary "I need that back" into a two-day wait.

The **90-day minimum storage duration is a property of the class, not a defect**, and the user has
to be told: an object archived on Monday and restored the following week is still billed for 90
days. SPEC-172's confirm dialog says so in user-facing wording.

The restore machinery is **unconditional** whatever the constant is set to — a class that needs no
restore still tolerates one being requested. A test forbids any branch on the constant anywhere on
the plane, because making the machinery conditional is how a config change silently deletes a code
path with nothing in the diff to show for it.

### Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose

Every object expires 2557 days (7 years) after creation. Nothing prevents an earlier delete, and
nothing may: SPEC-171's restore deletes the archived copy once it has been put back.

The expiry rule is **bucket-wide with no prefix filter**, and it is the exact **inverse** of the
admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check. That check exists because *that*
bucket mixes `logs/` (retained forever) with expiring content, so an unfiltered expiring rule there
would silently delete the logs. This bucket holds exactly one class of object, so the risk runs the
other way: a prefix filter would be a silent way to leave some archived data unexpired past the
retention the feature promises. **S3 lifecycle can include a prefix but never exclude one**, so if a
second content class is ever put in this bucket the repair is *not* to add a filter — that would
leave the new class unexpired and this rule looking correct. It is to revisit the rule, and probably
to give the new class its own bucket.

**S3 Object Lock is out of scope for two independent reasons.** It requires bucket versioning, which
this project deferred by decision (2026-08-03); and in compliance mode nothing can delete an object,
not even root, which would make SPEC-171's cleanup of a restored archive impossible.

### The bucket the browser has no relationship with

No CORS configuration, no entry in the SPEC-140 `connect-src`, and the portal role holds **zero**
statements naming the ARN. The only route to archived bytes is a restore request through this plane.
The bucket's own policy is a `StringNotLike aws:PrincipalArn` Deny admitting the archive execution
role, the deploy role and the account root — so an identity policy that later grew a statement here
would still be refused. It denies `s3:RestoreObject` as well as the four ordinary actions:
`RestoreObject` is what makes a `GLACIER` object readable and is not covered by `GetObject`, so a
policy without it would leave any principal able to start a **billed** retrieval on someone's
archive.

What the browser *does* get is a **Deny** on `PutObject` / `DeleteObject` / `AbortMultipartUpload`
under `archive/` in both space buckets (FR-006). A user who can rewrite a receipt can misreport what
was archived. `AbortMultipartUpload` is included even though a `PutObject` Deny already blocks
multipart writes: without abort, a half-started upload cannot be tidied and its parts sit billed and
invisible. `GetObject`/`ListBucket` are untouched — the receipt is deliberately a plain text file
the user downloads and reads themselves, which leaves the no-preview rule intact. **The UI mirror is
owed and lands in SPEC-172**; an IAM Deny with no UI counterpart produces a bare `AccessDenied` for
a rule this application itself authored.

All of this is a **negative** claim, which is the kind that rots without anything looking wrong, so
`lambdas/test_archive_bucket_isolation.py` asserts it against the IaC rather than describing it.

### The key layout: the archived key carries its own origin, partitioned by space kind

`personal/{username}/archive/{uuid}/…` and `shared/{space}/archive/{uuid}/…` in the archive bucket;
`{root}archive/{uuid}/receipt.txt` in the space's own bucket.

**The archived key encodes its origin**, so `origin_key` reconstructs the source with no lookup at
all. That is what lets SPEC-170 rebuild every restore destination from one `ListObjectsV2` over the
archive prefix: **the receipt is a report, not a record**, exactly as SPEC-143 judges a table by
its shape rather than by the marker it also writes. The manifest exists only as a cross-check that
can fire when something is already wrong.

**The leading kind segment is the entire fix for a real collision.** Receipts live in each space's
own bucket, where the two namespaces cannot meet; the archive bucket is the first place they do.
Shared-space names are made unique against the shared-space registry only — **nothing anywhere
checks a proposed space name against the User Pool** — so a user `alice` and a space `alice` can
both exist today. Flat, they would share one archive prefix, and since SPEC-170 authorizes a restore
by *space* and then reads whatever sits at that prefix, a member of space `alice` could restore user
`alice`'s archived files into the shared space. The alternative fix — refusing to create a shared
space whose name matches an existing username — is **rejected**: it changes a shipped, unrelated
control plane, it cannot repair names that already exist, and it would make space creation depend on
the User Pool for a reason unrelated to space creation.

The `{uuid}` is browser-supplied and becomes a path segment in two buckets, so it is validated as a
UUID v4 **before it is ever concatenated**, at every builder rather than once at the front door, and
**lowercased** — S3 keys are case-sensitive, and a re-submitted id in different case would open a
second archive under a name that reads identically in every message and every listing.

### One plane, one `mode` branch, and no grant this spec did not need

**ONE machine serves both archive and restore**, branching on `mode` — SPEC-143's create/refresh
branch on the table-builder is the precedent, not a sixth module: the two verbs share the bucket,
the execution role, the key layout and the receipt, and a restore is meaningless without the archive
that produced it. The `Choice` guards **every** comparison with `IsPresent`, per choice rather than
once: a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default` does not cover
it. Its `Default` seeds a **reason code**, never `TerminalError` — notify-failure treats that one
name as evidence a verb's decorator already notified, so a seed wearing it would be silently
suppressed (the recorded `DiffMissingSeed` rule).

**The execution role holds no S3 grant on any data bucket at this stage, and the restraint matters
more here than on any other plane.** Archiving is the only operation in this repo that deletes a
user's data as a side effect of a copy. Every other plane's execution role carries a blanket
`Deny s3:DeleteObject` from its first apply and has that be an enforced property forever; **this one
cannot**, because SPEC-169 has to grant `DeleteObject` on the source buckets. So the property that
replaces it belongs to the spec that grants it — scoped to the space prefixes, never reaching
`athenaresults/`, `user_settings/` or any `DO_NOT_DELETE.txt`, with the commit gate in front of it —
and granting nothing today keeps that an explicit decision rather than an inheritance.

**No `TimeoutSeconds` yet, deliberately.** Nothing in this machine waits: no Map, no manifest, no
copy, no poll loop. A ceiling does **not** on its own reach `NotifyFailure` — AWS catchers cover
Task, Parallel and Map states but not top-level execution failures — so it must ship WITH an
EventBridge `TIMED_OUT` rule or it is SPEC-152 satisfied on paper and silent in practice. Two tests
are tripwires on exactly that: one fails the moment a `Map`, `Wait` or `Parallel` appears, the other
the moment notify-failure grows a second door without one.

### Two things the fleet's own guards caught while this was being written

**Containment moved to `cpcommon.paths` rather than being copied into `arcommon`** (SPEC-156).
`assert_inside_root` / `has_dot_segment` / `normalize_root` arrived on `fscommon.paths` with
SPEC-164; archive is the third plane to ask the identical question, and it is the one place where a
second copy that drifts is a **cross-tenant read**. `fscommon.paths` re-exports the three names, so
every file-send call site and test is unchanged. A test asserts `arcommon.paths` defines none of
them.

**`ARCHIVE_BUCKET` is not a `cpcommon.config` required variable.** The first attempt added it to
`_REQUIRED_VARS`, reasoning that the lazy `__getattr__` made it free for planes that never read it.
That is true of resolution and false of the contract: `_REQUIRED_VARS` is a **fleet-wide** set that
`test_the_common_environment_satisfies_every_import_time_require` asserts each plane's Lambda
environment supplies, so the change failed table-builder's guard immediately. The value is
`arcommon.config.archive_bucket()` instead — a **function**, not a module attribute, because a
constant resolved at import time in a layer runs for every attaching function and an unset variable
then crashes at **cold start**, where no test and no deploy can see it (PR #196). `cpcommon.config`
gained a public `require()` so a domain layer reaches for the fleet's one fail-fast reader rather
than writing a second.

### The commit gate, and the four choices that make a deletion safe (SPEC-169)

### The source is deleted only when EVERY object is confirmed copied

Archiving is the only operation in this portal that deletes a user's data as a side effect of a
copy, and the failure mode it must never have is **"copied 900 of 1000, deleted 1000"**. So the
gate is a state, not a convention.

`collect-transfer-results` returns ONE BOOLEAN and `CommitOrRollback` branches on it: the
committing arm reaches `DeleteSource`, and the rollback arm **cannot** — asserted by walking the
ASL graph from the gate's default, because a `Catch` or a `Next` added anywhere on that arm could
reconnect it and nothing about the diff would say so. The `Default` is the ROLLBACK, so an absent
or unrecognisable verdict fails closed; the failure on the other side is deleting a user's only
copy.

**Three ways to be short, one verdict.** A reported item failure; an export accounting for fewer
items than the manifest listed; a manifest whose count disagrees with the plan it was built from.
The last is a check file-send cannot make — there a manifest line is one `(recipient, object)`
pair, so the two counts differ by design. Here they are the same number written twice, and a
disagreement is the one shape where every downstream count agrees with itself and is wrong.

**Both halves of the Map Run's export are read**, for SPEC-160's reason: Step Functions files a
child by its execution STATUS, and the batch copier deliberately succeeds while carrying per-item
failures. A `FAILED`-only collector reports universal success — and on this plane that reported
success is a deletion.

`plan.load` refuses a plan that is short of the `objectCount` it records, and that check is what
makes the gate's guarantee true rather than aspirational: a truncated plan produces a manifest
short of its lines, a copy that succeeds over it, and a gate that **agrees**, because both sides
of the comparison are short by the same amount.

### The rollback deletes what is THERE, not what it was told about

FR-004 says the rollback removes the objects the collector reports as copied. It is implemented as
a `ListObjectsV2` over the archive prefix, and the reading is deliberate. Keys are the unbounded
term — tens of thousands of them cannot ride a 256 KB state — but the listing is also the strictly
better answer: the prefix is `{kind}/{name}/archive/{uuid}/`, this request's alone, so everything
under it was put there by this archive and by nothing else, **including anything a batch copied
before it died and never reported**. A collector-supplied list would omit exactly those. Its
predicate ignores nothing, because the shared paginator's default drops zero-byte placeholders and
hidden segments and both are things this plane deliberately archives.

**A rollback that itself fails partially does not change the outcome.** The property that matters
is that the source is intact, and it is; the residue is billed at the GLACIER 90-day minimum, is
unreachable by the user (the browser has no relationship with that bucket) and is swept by the
7-year expiry. It is reported in the failure notification through its own reason code rather than
retried forever. The same disposition covers a collector that cannot read the export at all: that
is a whole-request terminal with the source untouched, and it does not roll back, because a
collector that cannot read the export cannot say what there is to roll back.

### The delete grant is the one this role could not inherit

Every other plane's execution role carries a blanket `Deny s3:DeleteObject` from its first apply.
This one cannot, so the narrower property is written out: `DeleteObject` on the two SPACE buckets
only, plus an explicit **Deny** under `athenaresults/`, `user_settings/`, `archive/` and on any
`DO_NOT_DELETE.txt` at any depth (`*` matches `/`). A Deny rather than a narrower Allow, because an
explicit Deny beats every Allow — including one a later spec adds without reading the file.

IAM is the SECOND line of defence. The first is the gate; the third is
`arcommon.delete.assert_deletable`, which checks the whole list **before issuing anything**, so a
key the policy would refuse fails the run rather than stopping a deletion half way through — after
some of the user's data has already gone. It fails loudly rather than filtering: a silent filter
would delete a source the archive is missing objects from.

Review found that check accepting `alice/../bob/secrets.csv`, which starts with `alice/` and passed
a prefix-only test. S3 resolves nothing, so no cross-tenant delete followed; it is closed because a
containment rule that holds only while every consumer stays careful is not a rule, and this
consumer is the one that deletes. **Containment is both of `cpcommon.paths`' rules, everywhere.**

### The request id is browser-supplied, so a reused one is refused twice over

**Both halves of this came out of review, and one of them could have deleted the wrong data.**

The request id is the whole identity of an archive: the copy plan, the archive prefix,
``_manifest.json`` and the receipt are all keyed on it alone (only the transfer manifest also
carries the execution). The queue's FIFO ``MessageDeduplicationId`` is that id, but its window is
five minutes against a three-hour ceiling, this arc's live checks submit hand-crafted messages, and
the browser producer that would mint a fresh id per submit is SPEC-172's. So a second request under
a used id is reachable, and nothing downstream noticed.

**delete-source takes the bucket, the root and the KEY LIST from a plan it re-reads.** The commit
gate upstream compares two values that both come from the state, so it cannot see a plan another
execution overwrote. Run 1 could therefore pass its own gate on its own counts and then delete run
2's selection — in either space bucket, since the grant covers both. ``plan.load`` now takes the
request and ``assert_describes`` compares the plan's request id, source bucket, source root and
object count against it; a mismatch is ``plan_superseded``, with the source untouched.

**The rollback made the second half worse than a duplicate.** A run under a used id that fails its
gate lists ``{kind}/{name}/archive/{uuid}/`` and deletes everything under it — including a
PREVIOUS, completed archive's objects, out of a bucket with versioning off. Unrecoverable. So
inspect-source now refuses up front when the archive prefix already holds anything
(``request_id_reused``), one ``ListObjectsV2`` before a single ``HeadObject`` is spent. It
**narrows rather than closes**, exactly as table-share's conflict guard does: two concurrent
executions can both find the prefix empty. What it removes is the ordinary case.

### An object this plane could copy but could not delete is refused, not archived

Two rules were each correct alone and disagreed with each other. The code's reserved-folder rule is
anchored at the SPACE ROOT on purpose — ``assert_not_reserved``'s own docstring says
``alice/reports/archive/`` is an ordinary folder the user made. The IAM Deny protecting the same
names cannot be anchored anywhere: ``*`` matches ``/`` in a resource ARN and IAM has no
single-segment wildcard, so ``*/archive/*`` covers every depth.

The gap between them was a real user-facing failure. Archiving ``alice/projects/`` containing
``alice/projects/archive/notes.txt`` would copy every object into Glacier at the 90-day minimum,
write its record, and then fail part way through the deletion with "contact an administrator" — a
full orphaned copy and an escalation, for an ordinarily-named folder.

It is refused at expansion time now, and refused **WHOLE** rather than excluded, which is SPEC-165's
rule: a silent exclusion drops the user's own data out of an archive that reports success. The
message names the folder so the user can rename it. A file merely CALLED ``archive`` is untouched —
the Deny needs a segment after the name, so the rule reads folder segments and not basenames.

### The artifacts are ordered most durable to least, and the receipt's failure is terminal

`_manifest.json` into the vault → the source deletion → the receipt into the user's own space,
matching the data-quality plane's report → notification → index. A receipt therefore only ever
exists for an archive that completed, and a run interrupted between any two states leaves something
an operator can read.

**The receipt failing fails the RUN**, even though the data is safely archived and the source is
already gone: a user with no receipt has no id and therefore no route to a restore. The message
says the data IS archived and names the request id, so the run is recoverable by hand.

**The manifest is a report, not a record.** Nothing may come to depend on it — SPEC-170 rebuilds
every restore destination from the archived keys themselves, because an archived key encodes its
own origin. An AST sweep over the plane enforces that for the specs that have not been written yet,
exempting docstrings by node identity (SPEC-165's recorded trap) and qualifying the import test,
because `cpcommon.transfer.manifest` is a different module with the same name.

Both timestamps come from `$$.Execution.StartTime`, stamped onto the state by the same `Pass` that
stamps the execution name. Two `now()` calls would disagree by however long the deletion took, and
a re-run would disagree with itself.

### Three caps, and the one the spec does not name

Each is COMPUTED by a test that reads `locals.tf` back, never asserted as a number.

`ARCHIVE_MAX_OBJECTS` **20,000** is sized by the copy plan held in memory — by inspect-source,
which builds and serialises it, and by delete-source, which loads it back. `ARCHIVE_MAX_BYTES`
**3 TiB** is sized by the machine's own `TimeoutSeconds` at a **makespan** rate
(`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s), never the aggregate the
same constants suggest multiplied together; the test adds the copy, the per-child overhead of
20,000 items in batches of 8, and the seven serial verbs (~8,100s against 10,800s). Unlike
file-send there is no product cap beside it: an archive has one destination, so the source cap IS
the transfer cap.

**`ARCHIVE_MAX_OBJECT_BYTES` 10 GiB is not in the spec, and the arithmetic above needs it.** A
batch is one round of the worker pool and **one object is one worker** — `copy_batch` hands a whole
object to a thread and `copy_one`'s multipart loop is serial — so nothing else bounds a single
object's copy time. S3 accepts objects up to 5 TiB, which is ~220,000s at the conservative rate:
240× the batch verb's timeout and 20× the whole machine's ceiling. Without it the makespan model
certifies the distributed case only, which is SPEC-166's recorded finding inherited rather than
rediscovered.

### The ceiling ships with its rule, again

`TimeoutSeconds` 10,800 is **top-level** (SPEC-157 settled that distinction), and it arrived in one
PR with the EventBridge `TIMED_OUT` rule, `ar_notify_failure`'s second door and its 15s → 60s
raise. AWS catchers cover Task, Parallel and Map states but **not top-level execution failures**, so
without the rule the ceiling terminates the run outright and the actor is told nothing — SPEC-152
satisfied on paper and silent in practice, on the one failure where the user has been waiting three
hours. `TIMED_OUT` only, never `FAILED`, or every caught failure double-notifies.

The door needs the same `DescribeExecution` fallback file-send's does, and for the same reason:
EventBridge caps an event at 256 KB and this plane's execution input is the Pipe's record, which
`ARCHIVE_MAX_ITEM_BYTES` deliberately allows to approach 200 KB — so the biggest selections, the
ones that run for hours, are exactly the ones the event alone cannot attribute. What the timeout
message may PROMISE is decided by where a timeout can land: the deletion is downstream of the gate,
so a timed-out archive has never deleted anything, whatever else it did.

### The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops

The spec's illustrative receipt shows a selected folder as the original path. That would be wrong
for the key layout this arc shipped: `archived_key` keeps every object's path relative to the SPACE
root, so naming the selection pairs it with an archive prefix that does not correspond to it — and
a 200-item selection has no single original path at all. Rooted at the space root and the archive
root, the two lines are exact inverses of each other for every object, for every selection.

The expansion's ignore predicate is this plane's own, and it **keeps** what
`cpcommon.s3_listing.is_ignored` drops: zero-byte folder placeholders (an archived empty folder has
to come back, and nothing else in the plan records that it existed) and hidden or underscore-
prefixed segments (those are ignored because *Athena* ignores them, which says nothing about a
byte-for-byte copy of a user's own folder). It excludes only prefix markers and the portal-managed
root folders. An empty expansion is a REFUSAL, never a success: a receipt claiming zero files
archived is worse than a refusal, and an empty archive prefix is indistinguishable at restore time
from one whose objects have vanished.

### The restore guard, and the four choices that make it safe to start a bill (SPEC-170)

### The guard is absolute, and it runs before the retrieval

S3 has no move and no rename, so a restore is a copy and a copy overwrites. If the user has
re-created `reports/q1.csv` since archiving it, restoring on top destroys the newer file with no
trace and no versioning to recover from. So **any** occupied destination refuses the **whole**
restore: no skip, no overwrite, no merge and no "restore what fits". Partial restores around an
obstacle were considered and rejected — they leave a folder holding two generations of the same
data with nothing recording which is which, and the user cannot tell by looking.

**A `403` counts as OCCUPIED.** A key this role cannot head is a key it must not overwrite, and on
these buckets that is live rather than hypothetical: the execution role's own policy Denies it
beneath `athenaresults/`, `user_settings/` and `archive/`. Reading an ambiguous answer as "clear" is
the one mistake here that ends in data loss, so the guard fails closed on anything that is not a
proven 404 — including an error carrying no status at all.

**And it runs before any `RestoreObject`, which is why the arc splits at exactly this state.**
Glacier retrieval is billed and irreversible once initiated. Everything in SPEC-170 is verifiable in
seconds; everything in SPEC-171 takes 3–5 hours and cannot be cancelled. A guard on the far side
would report the same refusal and charge the user for the privilege. The property is asserted by
walking the ASL graph from the guard's failure branch and requiring that **everything** reachable
from it is the failure path itself — not by asserting "no path to a retrieval state", which passes
vacuously while no retrieval state exists and would go on passing forever.

The refusal names a **bounded sample** because the guard **short-circuits**: an archive of 200,000
objects must not issue 200,000 heads to report a conflict found in the first hundred. Having
short-circuited, it genuinely does not know the total — so the message says there may be more.
Implying the sample was exhaustive would send the user round the clear-and-retry loop once per
hidden collision. The sampled keys render **relative to the space root**, so the user reads a path
they recognise from the file browser.

### The bound is botocore's connection pool, not the thread count

`RESTORE_HEAD_CONCURRENCY`'s first value was 32, computed against "workers × timeout / latency",
which is the model that makes a head-heavy verb look like a scheduling problem. It is wrong in a way
its own arithmetic cannot show: `boto3.client("s3")` takes botocore's default
`max_pool_connections` of **10**, so threads past that do not each get a connection — they contend,
and urllib3 opens and discards sockets rather than reusing them. A pool of 32 buys throughput the
client cannot deliver *while every bound computed from it reads as satisfied*.

So the concurrency sits inside the client's ceiling at **8** — which is also, not coincidentally,
why `COPY_CONCURRENCY` is 8 — and the **timeout** is what pays for the work: 20,000 heads, 8 at a
time, at a pessimistic 100 ms each is ~250 s, and `locals.tf` gives the guard 600 s. A test reads
the ceiling off `botocore.config.Config` rather than restating it, because that is the term a later
"just raise the concurrency" would skip.

`RESTORE_CONFLICT_SAMPLE` (5) is a **presentation** bound and is documented as one: the guard has
usually seen only a handful, so the number is about what fits in a sentence a person reads.

### The lookup reads the KEYS; the record is a cross-check it can do without

`inspect-archive` derives every destination by listing the archive prefix and running each key
through `paths.origin_key` — the exact inverse of the writer — because the archived key encodes its
own origin. `_manifest.json` is consulted only to compare counts, and **absent, unreadable and
malformed are all tolerated**: a restore that refused for want of a convenience record would be
precisely the failure mode the self-describing key layout exists to prevent. Only a record that
**disagrees** refuses, which can fire only when something is already wrong.

That tolerance is what made SPEC-169's `test_no_restore_verb_requires_the_manifest` sweep survivable
rather than deleted. The exemption is the layer module alone; a companion test keeps **verbs** out,
including SPEC-171's, so the cross-check has one home and one tested tolerance.

The exclusion is by **exact key at the archive root**, never by basename: a user's own
`reports/_manifest.json` three folders down was archived like any other file and must come back.
Conversely the lookup applies **no ignore predicate at all** — SPEC-169's expansion deliberately
KEEPS zero-byte placeholders and hidden segments, so restoring through a filter the archive did not
write through would silently return less than was taken.

The restore plan goes to the admin bucket and only its **key** rides on the state, for the reason
every artifact on this plane does: at `ARCHIVE_MAX_OBJECTS` the list is tens of megabytes against a
256 KB payload limit, and `States.DataLimitExceeded` escapes every `Catch`. It is read back with the
same identity check SPEC-169's review added to the copy plan — the key is a pure function of the
request id, so a second run under a reused id overwrites it, and a guard that cleared **that** plan's
destinations would clear a restore for keys this run is not going to write.

### The space comes from the request, and the two ids are different things

Authorization is a question about the space the user's route names (SPEC-113's rule), never about
whatever the archive claims — so an archive belonging to another space resolves to an empty prefix
and is simply **not found**. `archive_not_found` therefore never distinguishes "never existed" from
"not yours"; the difference is an existence oracle over other people's archives.

`requestId` ≠ `archiveId` is enforced rather than conventional. The run and the archive are
different things: a refused restore must be re-submittable under a new run id, and a second attempt
at one archive is a new request rather than a duplicate of the first. A producer that conflates them
will do it on every request, and the symptom would surface only under a retry.

The pasted id is matched against `arcommon.paths`' **one** UUID regex before it is concatenated into
anything — the same rule `validated_request_id` uses, differing only in the refusal's wording,
because a second and laxer copy would be a second door into the same key. It is lowercased, so a
receipt retyped in capitals still resolves the prefix the archive was written under.

### One front door, one `Validated` Pass, and two message prefixes

The restore validator is a **branch of the existing verb**, not a second Lambda, and that is forced
rather than chosen: `ChooseMode` sits downstream of validate-authorize and reads `$.mode` off the
parsed request, while in the raw Pipe record the same field is inside an escaped JSON string ASL
cannot look into. A separate front door would need the branch to happen before anything had parsed
the body.

Both modes therefore return the **same five top-level keys**, because a shared `Validated` Pass
naming a path one mode lacks raises an uncatchable `States.Runtime`. `source` is the authorized
SPACE in both — the archive's source in one, the restore's destination in the other — and only its
`items` are archive-only. The unknown-field check is made **per mode**: a union of the two contracts
would accept a restore carrying a selection and an archive naming an archive id, and silently ignore
whichever the mode did not read.

The failure path carries `mode`, and `arcommon.messages` registers **two resolvers over one body
table**. The codes only one mode can reach are unambiguous; `forbidden`, `malformed_event` and
`invalid_request` are reachable by both and are exactly what a single "Couldn't archive that" prefix
gets wrong. `ValidateFailureSeed` supplies a literal `null` — its input is the raw error, so reading
`$.mode` there would raise on the failure path itself.

**`restore_archive_incomplete` does not reuse FR-005's proposed `archive_incomplete`.** SPEC-169 had
already registered that code for a copy that fell short, its body promises "nothing was deleted and
your files are exactly where they were" — meaningless about a restore — and the ASL seeds the
literal in `RollbackReturnedSeed`. One code cannot carry both sentences, and the shorter name
belongs to the arm that shipped first.

### This spec adds no IAM, and that is asserted rather than assumed

FR-006's additions were already in place: `SourceDataRead` grants the `s3:GetObject` a `HeadObject`
authorizes against, and `ArchiveVaultList`/`ArchiveVaultWrite` cover the vault — all SPEC-169's. So
there was no grants-first PR split to make, unlike 168 and 169.

The `GetObject`-not-`ListBucket` distinction is nonetheless pinned by a test, because the failure
mode of the wrong grant is a **false pass**: a role holding only the bucket-level listing permission
gets a 403 on every head, and a guard that read 403 as "clear" would then report every destination
clear and overwrite the lot. Both directions of that mistake come back to one statement existing.

### Review closed two holes, and one of them was a silent, unrecoverable deletion

**A user's own file at the SPACE ROOT called `_manifest.json` archived onto this plane's own
record.** An object's archive key is `{archivePrefix}{relKey}` and the record's is
`{archivePrefix}_manifest.json`, so the two collide for exactly one relative key. Nothing upstream
caught it: `assert_not_reserved` refuses selecting the space root as a *folder*, but naming that
file directly passes containment, the reserved-root rule and the marker rule. The copy would land,
`write-manifest` would **overwrite** it with the record, `delete-source` would then delete the
user's original — the vault has versioning off — and the run would report **success**. The archive
was also permanently unrestorable: the restore excludes that key as the record, counts one object
fewer than the record claims, and refuses `restore_archive_incomplete` for everything archived
beside it; archived alone, it restores as `archive_not_found` against a receipt the user is holding.

It is refused up front (`reserved_object_name`), for the whole request, rather than excluded —
SPEC-165's direction, because dropping it silently would archive everything else and delete the one
object it could not carry. Moving the record out of the archive prefix would remove the class
rather than the instance, and was **rejected**: FR-003 AC2 specifies the exclusion, so the record
living at the archive root is the spec's own model, and a sibling key would make the exclusion test
assert nothing. The rule is exactly as narrow as the collision — `reports/_manifest.json` three
folders down has a different relative key, collides with nothing, and archives and restores like any
other file.

**The guard did not short-circuit in the case FR-004 AC3 names.** The sample check sat after a full
round *and* required `RESTORE_CONFLICT_SAMPLE` collisions before returning — so fewer than five
meant no short-circuit at all. Measured: 20,000 heads to report a collision at index 3, when one
re-created file is the likeliest real conflict there is. It now stops at the round that finds the
first one. **The test that named the property could not fail**: its fixture used 64 *consecutive*
collisions, which fills the sample inside the first round, so it passed against the broken code — a
fixture that makes an assertion trivially true, which is the shape SPEC-163 records.

Two smaller ones, both about the wording rather than the data. A malformed **restore** was worded
as an archive failure, because `mode` came from the contract check's *return* and every refusal it
raises happens before that — so the wording mode is now seeded from the untrusted body first, which
is safe because the value selects between two fixed prefixes and reaches nothing else. And the
EventBridge `TIMED_OUT` door never passed `mode` at all: unreachable today, but SPEC-171's 3-5 hour
retrieval makes the timeout *predominantly* a restore event, so it now reads the mode out of the
same raw body the actor comes from and `restore_timed_out` ships beside `archive_timed_out` —
because what a timeout may PROMISE differs by arm, and "nothing was deleted and your files are
exactly where they were" says nothing true about a restore.

---

### Retrieval as the point of no return, and the four asymmetries the restore introduces (SPEC-171)

### The destination guard runs TWICE, because this spec turned a guarantee into a promise

SPEC-170's rule is absolute: **any** occupied destination refuses the **whole** restore, because S3
has no move and no rename, versioning is off, and a copy over a file the user re-created destroys it
with no trace. One check was sufficient while the guard and the copy were seconds apart — the
residual TOCTOU was an unlikely double-submit, the same one table-share and file-send carry.

**SPEC-171 put three to five BILLED HOURS between the check and the write, and spent them telling
the user a restore was in flight.** That is not the same window wearing a bigger number. It is a
window the plane itself opens and then invites the user to act inside: the receipt marker exists
precisely so somebody waiting hours knows something is happening, and somebody who knows their
restore is hours away goes and works in their own space. Re-creating a file there is the ordinary
case the guard was written for, arriving late — and the copy-back would have overwritten it,
reported **success**, and swept the vault.

`ReCheckDestinationClear` invokes the same verb over the same plan immediately before the copy-back.
It costs one round of heads (the guard's own 20,000-at-8 bound, ~250 s worst case) against a run
that has already waited hours, and it is what makes "any occupied destination refuses the whole
restore" true at the moment of the WRITE rather than only at the moment of the PROMISE.

Two details are decisions rather than mechanics. **The refusal is worded differently**, because the
two passes leave the user somewhere different: before the retrieval nothing has been spent, and
after it the objects are out of Glacier and stay ready for `RESTORE_AVAILABILITY_DAYS`, so a prompt
second attempt costs neither the wait nor the bill again — a fact the user needs and cannot possibly
infer from "some files are already there". And **the stage is SEEDED BY THE MACHINE**, never
inferred from what else is on the state, for the same reason `update-receipt`'s three stages are:
"the retrieval has not run" and "the retrieval reported nothing" look identical from inside a
handler, and getting that wrong tells a user their retrieval is still warm when it was never made.

It **narrows rather than closes**, as table-share's and file-send's guards do — two concurrent
writers can still land a file between the second head and the copy. The difference in kind is what
matters: seconds of overlap is a double-submit, and hours is the user acting on a message this plane
sent them.

### The retrieval Map tolerates NO failure, and the copy tolerates every one

`ToleratedFailurePercentage` is 0 on `RetrieveObjects` and 100 on `CopyBackObjects`, three states
apart in one machine. Both are right, and the reason is what each Map's failure would cost the
verdict after it.

The COPY must finish whatever happens, because a Map that aborted early leaves the gate after it
unable to tell "failed" from "not attempted" — on the archive arm that gate decides whether a user's
only copy is deleted, and on the restore arm it decides whether the archive is. The RETRIEVAL has no
verdict after it: a genuine fault means nothing was copied and the archive is untouched, so the
cheapest correct answer is to fail the Map Run and let the user re-submit.

**What makes that re-submission free is the two tolerated responses**, and without them the design
would be indefensible. `RestoreAlreadyInProgress` (HTTP 409) is the state the call wanted to bring
about, wearing an error's clothes — raised instead, a redriven execution or any re-submission would
fail on exactly the objects already on their way back, and each retry would bill a second retrieval
for the rest. `InvalidObjectState` is tolerated for a different reason: it is what S3 says when an
object is not in an archival class at all, so tolerating it is what keeps the restore path
**unconditional on `ARCHIVE_STORAGE_CLASS`**. Setting that constant to `GLACIER_IR` leaves this
machinery harmlessly in place rather than requiring a branch, which is how a config change deletes a
code path with nothing to show for it in a diff (SPEC-168's own rule, now load-bearing).

The retrieval is issued through a Distributed Map over the same manifest the copy-back reads, rather
than one verb with a longer timeout, because 20,000 `RestoreObject` calls is not work a single
invocation should be sized for — and the plane already knows how to fan out over a JSONL dataset.
**One manifest serves both Maps**: two would be two things that could disagree with the plan, and
the disagreement would surface as a restore that retrieved one set of objects and copied another,
with every count still agreeing with itself.

### Completion is the `Restore` header, and an ABSENT header is a failure

Nothing observable about an archived object changes when its retrieval completes. It stays
`GLACIER`; what appears beside it is a temporary readable copy that the `Restore` response header
describes. So the poll reads that header and nothing else, and there are three answers rather than
two:

- `ongoing-request="false"` — the temporary copy exists and the object can be copied.
- `ongoing-request="true"` — S3 is still working.
- **no header at all, on an object still in a Glacier class — nothing ever asked for this object.**

The third is why this is a module with its own suite rather than a boolean. Read as "not yet" it
would burn every one of the 84 poll iterations, wait seven hours, and then report `restore_timed_out`
for something that was never going to complete — a wrong cause on a run the user has been watching.
The mirror case matters too: an absent header on a NON-Glacier object means the object needs no
retrieval, so treating a missing header as a failure everywhere would refuse a restore of something
already readable.

**The poll samples, and its progress is an S3 pointer.** A per-object status list on the state is the
256 KB failure whose overflow escapes every `Catch` — which on this plane is a run that told the user
nothing at all — so the record lives beside the plan in the admin bucket and only scalars ride. The
paging rule has two halves that are easy to conflate: `RESTORE_POLL_PAGE` is the granularity progress
is **recorded** at, and the invocation's own bound is the whole plan. One page per `Wait` was the
obvious reading and is wrong: every object was requested at once at one tier, so they finish
together, and sweeping 20,000 objects a page at a time would add twenty five-minute waits — over an
hour and a half — *after* the retrieval had already completed.

**S3 Event Notifications (`s3:ObjectRestore:Completed`) were rejected as the completion signal**, and
not because polling is nicer. They would need bucket notification configuration covering every
archive prefix, a correlation store keyed by object so an arriving event could be attributed to the
run that asked for it, and a second delivery path with its own at-least-once semantics — to replace
a poll inside a machine that is already sitting still for hours, and that the plane already knows how
to write. The poll costs one Lambda invocation every five minutes.

**The iteration cap lives in Python and not in the ASL `Choice`.** `poll-restore` computes
`exhausted` itself and the Choice reads a boolean, because a literal in the rendered machine plus a
constant in `config` is two homes for one number — and they would only ever disagree on a restore
that was already going badly.

### The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane

`RESTORE_MAX_POLLS × RESTORE_POLL_SECONDS` is **seven hours** against a tier whose documented worst
case is five. Every other timeout in this repo can be tight, because failing means re-running
something free. Here the cost is asymmetric in a way most timeouts are not: **giving up on a
retrieval that was going to finish makes the user pay for a second billed retrieval**, while waiting
two more hours costs one Lambda invocation every five minutes. AWS documents 3–5 hours as typical
rather than contractual, which is exactly the class of premise this project has been burned by
before.

That budget forced `TimeoutSeconds` from 10,800 to **43,200**, and the raise is not about data
volume: the archive arm's long pole is a copy, and the restore arm's is a *wait*. `TimeoutSeconds` is
a top-level ASL field on one machine serving two arms, so **the archive arm's backstop rose with
it** — a wedged archive is now reported after twelve hours rather than three. Accepted: it is a
backstop, not an expectation, and the alternative was killing healthy restores. A test asserts the
archive arm's own worst legal run still clears the ceiling by more than 4×, so the ceiling drifting
until it stops being a backstop for the arm that does not wait would fail the build.

### The restore's gate is the commit gate's MIRROR IMAGE, not its twin

Archiving's gate protects the SOURCE: nothing is deleted unless every object was confirmed copied.
The restore's gate looks identical — one boolean from one collector, `IsPresent`-guarded, failing
closed — and protects the ARCHIVE, for a reason that runs the other way.

**A partial restore cannot be rolled back.** The user's space already holds some of their own data,
and deleting it to make the operation atomic would destroy the very thing the restore was for. So
the failure arm deletes **nothing** — not the objects that landed, not the archive — and the archive
it keeps is then the only complete copy in existence. A restore that half succeeded and then deleted
its own source would be unrecoverable, versioning being off. A graph walk asserts no path from that
arm reaches `DeleteArchived`, the same way SPEC-169's walk asserts no path from its rollback reaches
`DeleteSource`.

`restore_incomplete` therefore has to say **three** things, and the third is the one an author would
leave out: how many objects came back, that the archive is intact and still restorable under the
same id, and that **requesting it again will report the files that DID land**. Without that last
sentence the obvious next action produces a `destination_occupied` refusal that reads like a new bug
on top of the old one. It is also the one body on this plane that describes a partial outcome, so
`test_no_body_promises_a_partial_outcome` gained a named exemption set rather than a skipped
assertion — a second body drifting into partial wording has to be argued for.

**The vault sweep's failure does NOT fail the run, where the source deletion's does.** Same
algorithm, opposite consequence: a half-deleted source means a user told their archive completed
while their files are still half there, and a half-swept vault costs storage in a bucket the browser
cannot reach that the 7-year expiry reclaims. So it is a `cleanupIncomplete` flag on a *successful*
run and the user is not told at all. Deleting inside the `GLACIER` 90-day minimum is an
early-deletion fee brought forward, not a defect — recorded because a later cost investigation would
otherwise read it as one.

### The receipt is rewritten, never re-rendered, and the counts come from the run

`arcommon.receipt` is still the single writer, but SPEC-171 rewrites **two lines by label** and
keeps every other line verbatim. The archive lines record the archive RUN, and its start time is the
one field no restore can recompute — so re-rendering the document from the restore's own state would
silently blank `Requested` on the only durable record the user has of what was archived and when. An
absent receipt (a **proven** 404) is composed fresh, losing only that one field; an **ambiguous**
read — a 403, or a fault carrying no status — raises rather than taking that branch, which is the
destination guard's fail-closed 403-is-occupied discipline pointed at a write.

**The marker runs before the retrieval, not after.** FR-006 AC4 asks for it "when retrieval is
initiated"; immediately before is the same guarantee and strictly safer, because there a
receipt-write failure costs nothing where a moment later it would fail a run the user had already
been billed for. It is also why that stage's failure contract differs from the other two: before the
bill a failed write fails the run, and after the data has landed it must not — the ASL `Catch` on
`UpdateReceipt` reaches the SUCCESS terminal, because the ordering is most durable to least (data
restored → receipt → notification).

One function serves all three stages and **the ASL seeds which one**, rather than the verb inferring
it from what else is on the state: "nothing has run yet" and "the run reported nothing" are
different facts that look identical from inside a handler. The seed carries the STAGE and the run
carries the COUNTS — an earlier version let the seed supply `restored`/`expected` too, so the
sentence written onto the receipt and the tokens in the notification had **two sources and could
disagree**, with nothing to say which was right.

### The metadata fix: a latent bug on all three planes, surfaced by a round trip

FR-003 AC5 asked for `MetadataDirective: COPY` on both copies. `CopyObject` has that directive and
defaults to it; **`CreateMultipartUpload` has no such directive at all**, and `UploadPartCopy` moves
bytes and nothing else. So every object over `MULTIPART_COPY_THRESHOLD` (5 GiB) came out of a copy
as `binary/octet-stream` with its user metadata gone — silently, and on table-share and file-send as
much as here.

It surfaced on this spec because an archive round trip is the first operation in this repo that
copies an object **twice** and hands it back to the user expecting it unchanged; a shared table is
read through Athena, which does not care about a content type. The fix is explicit on the single
path (stated rather than assumed, because the path beside it proves the default is not universal)
and a `HeadObject` on the multipart path whose headers are re-stated on the create call, skipping
anything the source does not carry so the two existing callers' requests are unchanged below 5 GiB.

**One thing `MetadataDirective` carries that the multipart path still does not: the object's TAG
SET.** `CopyObject` copies tags by default; `HeadObject` does not report them, so parity would cost
a `GetObjectTagging` per object over 5 GiB. Nothing in this portal tags an object, so it is
**recorded in `copy.py` rather than bought** — the moment a plane starts tagging, every object over
the threshold will start losing them silently.

**A test that fixtured only a small object would have passed while the bug lived on**, so the round
trip runs at both copy strategies. That is the same shape as SPEC-163's recipes that re-implemented
the gate they were testing: the fixture, not the assertion, is what decided whether the test could
fail.

---

### The archive surface: a confirm that is not a confirm, folder names as identity, and the first prefix write gate (SPEC-172)

### The one dialog in this app where the confirm is not the default, and Enter does nothing

Every other destructive confirm in this portal focuses Cancel because a stray Enter should not
delete a file. Archiving raises that from a courtesy to a structural requirement: it is the **only**
action here that removes the user's data and cannot be undone in the same sitting — getting it back
takes three to five billed hours.

So `ArchiveDialog` is built on `ConfirmDialog` **because of what `FormDialog` has**. `FormDialog`'s
`submitOnEnterRef` is a real affordance, and a dialog that merely declined to pass one would be one
refactor away from acquiring it. `ConfirmDialog` is not a form at all: focus lands on Cancel and
Enter cancels, by construction rather than by discipline. `RestoreArchiveDialog` makes the opposite
call for the opposite reason — one field, and Enter submits from it.

**The dialog does NOT say "This can't be undone."** `ConfirmDialog` will render that line on
request, the delete confirm uses it, and it would be the single false sentence in this dialog: a
restore is exactly that undo. What it says instead is how long one takes, which is the fact the user
actually needs and the one no button label can carry.

### The folder names ARE the archive ids, so the folder must stay visible

An archive is identified by a UUID the browser minted, and the user needs it back to restore. There
are three places it could come from: a notification, the receipt, and the folder that holds the
receipt. The notification is transient and the receipt is inside the folder — so the FOLDER is the
durable surface, and `archive/` is therefore the first app-managed root that is visible, unpasteable
and undestroyable at once.

That is also why this spec ships **no archive index, no archive browser and no picker of past
archives**. A cross-space index is the directory-shaped disclosure SPEC-158 declined; a per-space
one would be a second, weaker copy of a listing the file browser already renders. `ls` is the index.

**The receipt is downloaded and read, not previewed.** The project's no-in-browser-preview rule is
untouched, and this is the intended surface rather than a workaround: the ids are readable from the
folder names without opening anything at all.

### The write gate mirrors each bucket's own Deny, and averaging them gets one case wrong

`isWriteLockedPrefix` is the app's first rule about the prefix the user is STANDING in, as opposed
to a rule about a folder's name. It exists because IAM already denies writes beneath `archive/`, and
without a browser counterpart every attempt produces a bare `AccessDenied` for a rule this
application authored — the situation `isUndeletableRootFolder` exists to prevent for
`athenaresults/`.

**The two space buckets are denied differently**, and that asymmetry is structural rather than an
oversight:

- personal: `{bucket}/${aws:PrincipalTag/username}/archive/*` — anchored at the caller's own root,
  because in that bucket the prefix IS the principal tag;
- shared: `{bucket}/*/archive/*` — where the wildcard is the space slot, and **an S3 resource
  wildcard matches `/`**, so it reaches an `archive` folder at any depth.

Anchoring both at the root offers writes into a nested shared `archive/` that IAM refuses; applying
the any-depth rule to both refuses writes into a user's own `alice/backups/archive/` that IAM
permits. FR-004's criterion is both directions — "must not offer a write the policy refuses, and
must not refuse one it permits" — so the predicate takes the space kind. `archiveWriteLock.test.ts`
turns each `Resource` into a key matcher and runs the app's own predicate over the same keys;
deleting the shared branch reddens it (measured).

**The refusal is `aria-disabled`, not `disabled`.** A `disabled` control is skipped by the tab order,
so its reason is reachable only by hovering — which is how "it's greyed out and I can't find out
why" happens. `Button.disabledReason` renders the reason as the accessible DESCRIPTION and swallows
the click, and deliberately does not put the text inside the button: content becomes part of the
accessible NAME, which every `GATED_SURFACES` row and journey test queries by.

### Only three outcomes needed a producer, and one of them had to be invented

FR-006 names nine terminal outcomes. Six were already reason codes in `arcommon.messages`, emitted
exactly once by `notifies_on_failure` or by the machine's `NotifyFailure` — a second producer for
them would be the duplicate SPEC-114's one-token-per-OUTCOME rule exists to prevent. What was
missing was what a failure table cannot carry: `archived`, `restored`, and `restore_started`.

**`restore_started` is the only "started" notification in this application**, and the reason is
specific to this plane rather than a general improvement: every other control plane finishes in
seconds or minutes, so silence until the outcome is honest there. Here it is three to five *billed*
hours, during which silence is indistinguishable from a request that was dropped. It is emitted
**after** `RetrieveObjects`, not before — that Map is where the bill and the wait actually begin, so
announcing earlier would promise a wait that a failed retrieval never starts.

**The producer cannot fail the run, and the ASL enforces it.** On the archive arm the source is
already deleted when it speaks; a raise would turn a completed archive into a reported failure with
the data gone. All three states carry `ResultPath: null` (two sit mid-machine, ahead of a wait, a
poll loop, a second guard and a copy) and a `States.ALL` Catch whose `Next` is the state they were
inserted in front of. The verb carries `@traced` and no `@notifies_on_failure` — that decorator
would report a failure of the NOTIFIER as a failure of the archive.

**The ASL seeds which outcome it is.** All three call sites carry identical keys, so nothing on the
state distinguishes them and inferring would mean guessing — SPEC-171 settled its two destination
guards the same way, for the same reason.

**The restored link is the SPACE ROOT.** A restore puts every object back where it came from, which
for any selection of more than one folder is several places at once; picking the first would send
the user to a folder holding part of what they asked for. The archived link is the receipt's own
folder, and both carry the recipient's full key including the space root — SPEC-167's finding, that
a root-relative prefix is silently discarded by the route and lands the user at their space root
looking like a link that worked.

### The restore's FIFO group id hashes the archive ROOT, not the bucket and the root

SPEC-170 FR-001 specifies the digest of `{archiveBucket}/{archiveRoot}` and left it owed to this
spec, which is the producer. The browser cannot produce it: SPEC-168 decided the browser has **no
relationship with that bucket** — no CORS, no `connect-src` entry, zero portal-role statements — and
`test_archive_bucket_isolation.py` asserts the SPA's build env learns the archive QUEUE and nothing
else about the plane.

Including it would also buy nothing. The group id's one job here is that two restores of ONE archive
serialize, and the archive root's own leading `personal/`/`shared/` segment — the segment SPEC-168
added precisely because nothing checks a space name against the User Pool — already makes it
globally unique. The bucket is one constant across every restore this app can make.

So the canonical string is `{kind}/{name}/archive/{archiveId}/`, mirroring `arcommon.paths.
archive_root`, and `docs/testing/e2e.md`'s hand-crafted command was corrected to
match so the live check exercises the rule the browser reproduces. A test pins the derivation and
names SPEC-168's browser isolation — not the test — as the decision to re-open if it ever fails.

## The browser

### State

TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)

### Responsive (SPEC-095)

Mobile-first with **two custom breakpoints** in `index.css` `@theme` — Tailwind defaults (`sm`/`md`/`lg`/`xl`/`2xl`) reset to `initial`, only `tablet:` (≥900) / `desktop:` (≥1300) compile; unprefixed = mobile. Reflow via responsive utilities on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); a separate markup branch is allowed only for genuine structural divergence (Files table vs card list) or mount-cost/mobile-chrome cases. One viewport hook `useBreakpoint`/`useIsMobile` (`src/lib/`) for **mount-gating only**, never styling. Mobile nav = Header hamburger → `AppNavDrawer`; shared `Menu` + `MobileActionBar` primitives; `Modal`/`Drawer` gain small-screen presentations. Detail: `apps/portal/info/best-practices/react/react.md` §20.

### Help & guides (SPEC-074)

In-app how-to surface — a header help icon → `/help` page (Files/Query left-rail shell: section sidebar + accordion guide cards, active section in the URL hash). **Presentation + authored content only** (no data layer/network/AWS/IAM/infra/env/deps). Content is a **static, code-grounded** module (`features/help/helpContent.ts`) documenting only shipped, wired-end-to-end behavior (FR-005) — **keep it in sync via the completion-ritual step 6** whenever a user-facing feature lands/changes.

### User-facing error messaging (SPEC-106)

Raw AWS/Cognito/Athena text is **never** shown to a user. One SPA mapping module (`lib/errorMessages.ts` `toUserMessage`) is the single source of error wording — app code → AWS/Cognito name → Athena pattern → generic "Contact the Administrator" fallback; never render `error.message` directly (route it through the mapper at the code-in-scope boundary). App-level `ToastProvider`/`useToast` + `ErrorBanner` replace per-page toasts; dev-only original-error log (`import.meta.env.DEV`). Lambda control planes (tb/tscommon, shared-space create/delete) emit friendly failure notifications + cache `reason`, keeping raw text in logs + the SFN/registry record. Detail: `spec-delivery/SPEC-106`.

### `components/` may not import from `features/` (SPEC-155)

`features/query/` had become a shared layer nobody declared: `components/ToastProvider` and
`components/Sidebar` imported from it, and five sibling features pulled `CATALOG_IDENTIFIER_RE`,
`Connection`, `isConnectionUsable` and `useConnections` out of it. That direction is backwards —
`components/` is the shared presentation layer that features compose, so it cannot depend on one.

The fix moved each shared thing to where its direction is correct: `Toast` to `components/`, the
identifier rule to `lib/catalogIdentifier.ts`, and the connections domain — `Connection`,
`ConnectionKind`, `isConnectionUsable`, `useConnections`, `connectionStatusLabel`, plus the two nav
surfaces `Sidebar` and `SpacesList` — into a new `features/connections/`.

**The rule is enforced, not documented.** `eslint.config.js` bans `features/**` imports under
`src/components/**`. Two things are exempt, both deliberately:

- **Tests.** Integration-style tests mount real features by design (`react.md` §21), so the rule can
  only produce noise on that glob.
- **`Header.tsx` and `ProtectedLayout.tsx`.** These are app *chrome*: they exist to wire features
  into the shell, so composing features is what they are for. Bringing them under the rule needs a
  separate app-shell layer, which is a re-layering rather than an import fix. They are **named in
  the config** rather than left as a silent violation, so a third such file requires an explicit
  edit to that list. Everything else that was on the list has been moved out of `components/`.

Two residuals, both recorded rather than hidden:

- `features/connections/useConnections.ts` still reads `queryKeys.connections` from
  `features/query/queryKeys.ts`. Feature-to-feature is allowed, and splitting the key factory would
  change key *values* that two tests assert.
- ~~**`lib/queryClient.ts` imports `features/file-browser/fileBrowserKeys`**~~ — **CLOSED 2026-08-09.**
  It was a lower layer importing a feature, and a strictly worse inversion than the one this decision
  targets. `invalidateListing` moved to `features/file-browser/invalidateListing.ts`, beside the key
  factory it builds from; `lib/queryClient.ts` now owns only the client and imports no feature.
  `features/query`'s save-results flow reaches it through the file-browser barrel — feature-to-feature,
  which is allowed, and which was already true transitively through `lib/`.

  **The rule widened with it**, to `src/lib/**` and `src/hooks/**`. That was the point of the move:
  fixing the one file without widening the glob leaves the next one to be found by hand.

  **The test exemption is load-bearing on `src/lib/**`, not a formality.** `lib/support.test.ts`
  imports seven feature service modules — it is the consolidated lib suite, and testing a lib helper
  against real feature callers is what it is for. Without `src/lib/**/*.test.{ts,tsx}` on the
  exemption list the rule reports **6** violations there and `npm run lint` fails. The
  `src/hooks/**` test glob is inert today (nothing under `src/hooks/` imports a feature) and is
  carried for symmetry. Non-test files in both directories were clean, which is what made the
  widening a one-line glob change rather than a migration.

  The mock count in the original note was wrong — **two** test files mocked the module by path
  (`fileOpHooks.test.ts`, `UploadQueueProvider.test.tsx`); the other four merely imported it. That
  overstatement is most of why this looked expensive enough to defer.

  **What the rule still does not catch:** a dynamic `await import('../features/…')`. Base
  `no-restricted-imports` only sees static import/export forms — type-only imports, `export … from`
  and deep relative paths are all caught. The hole predates the widening and is unchanged by it.

### Dialog Enter-to-submit fires from ONE field, never from the form (SPEC-155)

`FormDialog` (SPEC-155 FR-002) turned eleven hand-written dialog chromes into one. Its body is a real
`<form>` with a `type="submit"` primary button — but **the browser's implicit submission is
suppressed on purpose**, and Enter submits only from the field named by `submitOnEnterRef`
(defaulting to `autoFocusRef`).

Adopting the form naively is the trap: implicit submission fires from *every* text input in a form.
The dialogs being consolidated each had exactly one field that submitted on Enter; handing it to all
of them filed a table build from a partition-key row the user was still editing — **measured before
the fix, not hypothesised**. A radio group is the same shape: arrow keys move a choice, Enter would
commit one the user never made.

A child that already handled the key wins over both, so a combobox's Enter-to-commit still works
inside a dialog.

### Escape dispatches by tree depth, not per-component opt-out (SPEC-155, supersedes `closeOnEscape`)

`useEscapeKey` now maintains a module-level registry of enabled handlers, each tagged with its
`EscapeLayer` depth, and dispatches Escape to **the innermost one only**. Nested dialogs are correct
by construction.

What this replaces: `Drawer`'s `closeOnEscape` prop, a per-component opt-out that every new nesting
had to remember. It is **gone**, not deprecated — it had no consumer left, and a prop nobody sets is
a rule nobody applies. `Modal`'s `dismissible={false}` now **swallows** Escape (`useEscapeBlock`)
instead of letting it fall through and dismiss the layer beneath — the case `dismissible` could not
express before without also disabling backdrop dismiss.

This sits beside, and does not contradict, the settled finding that `stopPropagation` from a React
handler DOES stop `useEscapeKey`'s `document` listener (SPEC-147, measured). That is still true: a
child that stops the event never reaches the registry at all. Depth-based dispatch decides between
layers that *do* reach it.

### The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)

`fileBrowser.format.formatSize` and `query.format.formatBytes` are documented as "deliberately not
merged", and on `undefined` handling that is defensible. On the **unit ceiling** it was not: a 3 TB
object read `3072.0 GB` in the file browser and `3.0 TB` in the query status bar, from the same
number, on two screens of one app.

**Decided: unify the ceiling at TB.** This is a **user-visible change**, which is why it is a
decision and not a refactor — SPEC-155's scope otherwise forbids one. The two functions stay
separate for their `undefined` handling; only the unit table is now shared. Silently keeping both was
explicitly not an outcome the spec allowed.

### A display page is not a listing page, and the space selector is gated (SPEC-174)

**Decision (2026-08-11).** The saved-queries surfaces page over **filtered rows**, never over S3
keys, and the two counts do not track each other. SPEC-173's store returns only the top-level
`.sql` files of a folder it deliberately left ordinary, so one `ListObjectsV2` page of 25 keys can
yield 25 rows, three, or **zero while more pages remain**. Paging the listing directly would render
a folder of two hundred CSVs and one saved query as an empty list with a "Load more" the user has
to guess the meaning of.

`useSavedQueriesPager` therefore **keeps fetching while the listing is truncated and it holds fewer
rows than the page in view needs.** Two bounds make that safe and neither is optional: the
listing's own end (`hasNextPage` goes false), and **an error stops the fill** — a failed
`fetchNextPage` leaves `hasNextPage` true and `isFetchingNextPage` false, which is exactly the
condition the effect fires on, so without the error guard one failure spins forever.

While it fills, the surface reads as **loading**. `isFilling` (no rows yet, pages remain) is a third
state beside `isEmpty` (listing exhausted, no rows) and the first-page load, because the two
alternatives are both wrong: an empty state that a fetch is about to contradict, and a pager
reading `0–0 of 0+`. The label carries `Z+` while pages remain for the same reason — S3 reports no
total, and `24` and `at least 24` are different claims.

**The window advances past the loaded rows and the clamp holds the view.** Next sets the index
beyond what exists; `safeIndex` clamps it to the last real page while the fill runs, and the new
page lands when its rows arrive. That one mechanism also covers a delete emptying the last page,
which is why FR-005's "move to the new last page" needed no code of its own.

**The selector is gated, deviating from FR-001's "exactly the spaces `useQuerySpaces()` returns".**
With `sharedWorkspaces` off it offers **My files alone**. SPEC-163 already filters the connections
list and the schema rail on that flag; a dropdown still naming a colleague's space, moments after
every other shared-workspace surface disappeared, reads as a bug rather than a policy. The filter
is applied in `QueryWorkspace` — at the **view**, never in `useQuerySpaces` and never in a service
(SPEC-162 FR-006) — and it needed no new fallback: `useSavedQuerySpace` takes its spaces as a
**parameter** and already resolves an id naming nothing offered to personal, so a revoked
membership and a flag turning off travel the same path. It is a **new registry row** (*Shared
spaces in the saved-queries selector*), not a widening of *Shared databases in the schema rail*:
that row gates the connections the rail browses, this one gates a control reading a different hook,
and SPEC-163's rule is one surface per row. Its reach-recipe opens the **real drawer** on the
**real workspace**.

### The shared layer is extracted before its second consumer exists, and the rule that guards it had to be verified by violating it (SPEC-176)

`features/query/` had become the portal's catalog layer by accident: the Glue reader, the Athena
start/poll/results/cancel layer, the space list, the results pager, the background row-count walk and
the column-width store all lived inside a feature that owns an editor and a tab strip. The Data
Explorer (SPEC-179 onward) needs every one of them.

**The extraction leads the arc rather than following it.** Building the Data Explorer first and
factoring afterwards would mean writing `import {useSchema} from '../query/useSchema'` and living
with it — which is exactly the undeclared shared layer SPEC-155 spent a whole spec dismantling, one
directory over. Extracting first costs a large mechanical diff against a codebase where every test
still passes; extracting later costs the same diff plus a second feature's worth of call sites, at a
moment when the pressure is to ship the feature. So `features/catalog/` exists with **no** user-
visible change, no new behaviour and no altered AWS call — the change most likely to go wrong,
made when nothing is riding on it.

### The key namespace moves with the module, and a prefix is not cosmetic

`catalogKeys` is rooted at `['catalog']`, not `['query']`. Keeping the old prefix would have been a
smaller diff and is the wrong call: a key namespace naming a feature the module no longer belongs to
is the same hidden coupling the extraction removes, and it would make a future
`invalidateQueries({queryKey: queryKeys.all})` in the Query workspace silently reach into the Data
Explorer's caches. Cache keys are in-memory and per session, so the change needs no migration and the
spec asserts none.

### The producer decides where a type lives, not the consumer

`useSchema.ts` moved carrying an import of `DatabaseSchema` from `sqlCompletions.ts`, which stays
behind — FR-001's "no catalog module imports from `features/query/`" broken by the first file moved.
`DatabaseSchema` is `{database: string; tables: GlueTableSummary[]}`: it had been declared beside the
completion provider that consumes it rather than the hook that produces it, and nobody had reason to
think of it as domain until the layers were separated. It is in `catalog.types.ts` now. Where a
producer sits in a lower layer than its consumer, the type belongs with the producer.

### `no-restricted-imports` matches the SOURCE STRING, so a sibling rule needs relative patterns

The SPEC-155 rule forbids `components/`, `lib/` and `hooks/` importing `**/features/**`, and it works
because those layers sit *above* `features/` and must name it: `'../features/query/queryKeys'`. The
sibling clause written the same way — `'**/features/query/**'`, `'**/features/data-explorer/**'` —
resolved onto exactly the right files and **caught nothing**, because one feature reaches another as
`'../query/queryKeys'`, which contains no `features/` segment at all. The load-bearing patterns are
the relative ones (`'../query'`, `'../query/**'`, `'../../query'`, `'../../query/**'`, and the same
four for `data-explorer`); the `**/features/…` globs stay for any path written the long way.

This is why FR-006 required the rule be **verified by committing a violation in each direction and
observing the failure**, not by reading the config. A rule that resolves onto the right files, prints
a correct `--print-config` and is written in the same shape as a working one is not a rule that
fires. `features/data-explorer/` is named in the rule before it exists, so the first file created
there lands under a guard already known to work.

**Tests are not exempt from this clause**, unlike the shared-layer rule above it. That exemption
exists because integration-style tests mount real features by design (react.md §21) — but a Query
test importing the Data Explorer is the coupling itself, not a mount of the tree under test.

### What did not move, and why

`SchemaBrowser`, `DatabaseNode`, `QueryResultsTable` and every dialog stay: the Data Explorer's
picker and grid are different components with different requirements, and SPEC-155's precedent is to
move the *domain*, not every consumer. The display page-size constants stay too —
`MAX_RESULTS_PAGE_SIZE` is a SPEC-087 workspace preference, not a property of Athena. `formatBytes`
went to `lib/format.ts` rather than into `catalog/`: it is a pure formatter with no catalog domain,
and both features render the same scanned-bytes figure.

### Geometry is keyed by NAME, NULL is kept apart from empty, and a page nobody watched is not "no rows" (SPEC-180)

The grid replaces SPEC-179's placeholder wholesale, and three of its decisions reach outside the
feature.

**Column geometry is keyed by the column NAME, which is why it is not `useColumnWidths`.** FR-001
asks to reuse SPEC-176's width store; that store keys by execution id and column **index**, in
memory, and re-defaults on a column-count change. Every other requirement points the other way — the
spec's own `columnWidths: Record<string, number>`, FR-001 AC7's per-tab persistence through
`sessionStorage`, and FR-006 AC3's "geometry for a column that no longer exists is discarded". Name
keying makes that last one true **by construction**: a width, a pin or a hide belonging to a column
this result set does not contain simply never resolves, where an index would have landed it on
whichever column moved into that position after a re-order or a `GROUP BY`. Stale entries are left
in place rather than pruned, so a re-execution that brings a column back brings its geometry back
too. The catalog's sizing constants and its resize gesture are reused; the hook is not.
`ColumnResizeHandle` itself **moved to `features/catalog/`**, generic over its column key (index for
the Query workspace, name here) — two sibling features now draw result grids and neither may import
the other, so the alternative was the `*Mobile`-style twin SPEC-095 calls a smell.

**A focusable `role="separator"` needs a value, and the Query workspace had been shipping without
one.** axe raised `aria-required-attr` the first time a grid full of handles was driven into a live
state — the violation was always there, but no axe assertion had ever run over a header row carrying
handles. `aria-valuenow`/`aria-valuemin`/`aria-valuetext` now ship with the shared handle, so both
surfaces gain the fix.

**`getQueryResults` stopped collapsing SQL NULL to `''`, because nothing downstream can undo that.**
Athena's Datum omits `VarCharValue` for NULL and carries an empty one for an empty string; the
service mapped both to `''`, so FR-003 AC5 ("an empty string and a `NULL` are visibly different")
was **unbuildable** at the layer that had to satisfy it. Rows are now `(string | null)[][]`. The
Query workspace renders both as blank exactly as before — this is information kept, not behaviour
changed — and SPEC-181's `isNull` filters and SPEC-185's copy both need the distinction. Its cost is
that every consumer of a cell now handles `null`, which the compiler enumerated: six sites.

**A remembered page index outliving its cached pages rendered a result WITH rows as "No rows
returned".** `useQueryResults` keeps a per-execution page position (SPEC-078's result tabs); the
pages behind it are collected once nobody observes that execution for `gcTime`, and the refetch
starts again from page 1. The remembered index then selected a page that was not there, and **an
absent page is indistinguishable from an empty one** — so the pager read `rows: []` with
`isPending: false` and the grid drew the friendly empty state over a full result. The index is now
clamped to the pages actually loaded, only while any are. The neighbouring test named for the page
memory could not have caught it: the test client runs `gcTime: 0`, so it was asserting the transient
index during a refetch rather than a restored position, and it now holds a second observer warm so
the case it is named for is the case it runs.

**`presentation: null` means UNCHOSEN, and that is the whole of FR-007's mobile default.** Below
`tablet` an unchosen tab opens in Record; a tab whose user has chosen keeps that choice at every
width. A non-null default would have had to be picked when the tab is created, by
`useExplorationTabs`, which has no business reading the viewport — and `useIsMobile` would then have
been deciding a persisted value rather than mount-gating one (SPEC-095 FR-008). Record and the grid
share **one** focused row, so switching between them lands where the other left off rather than
where the cursor happened to be.

**The selection model is explicit because two later specs are built on it.** `ranges` is a list of
inclusive rectangles and **the last one is live** — its `from` is the anchor a Shift gesture extends
from, its `to` is the cursor — and a Ctrl/Cmd+click appends a single-cell rectangle that becomes the
live one. Toggling off removes only a rectangle that is exactly that cell, because punching a hole
in a rectangle is not something the model can represent. The count is taken over a **set of
coordinates**, not summed per rectangle, since overlapping ranges are one click away and a sum would
report more cells than the page has. Everything is addressed by (row on the page, column name), so
coordinates are meaningless across a page change — the reset happens **during render**, not in an
effect, because an effect paints one frame of the old selection over the new page's rows, which is
precisely the state AC8 forbids. Cells carry an explicit `role="gridcell"`: a bare `td` inside
`role="grid"` maps correctly only through one HTML-AAM lookup, and several accessibility APIs (and
the test renderer) resolve it statically as `cell`, a role with no selected state.

**Hide, pin and reorder live in a PANEL, not in the header.** SPEC-181 owns the per-column header
menu, so putting them there would have meant building that menu a spec early and rebuilding it a
spec later; the panel is also where the **keyboard alternative to dragging** belongs (Move earlier /
Move later, announced in a live region), since a drag has no keyboard equivalent to inherit. A
cross-block drag — an unpinned column dropped onto the pinned block — is **refused rather than
coerced into a pin**, because inferring a pin from where a drag ended is a mutation the user did not
ask for and pinning has its own control.

### One `apply` per gesture, a numeric refusal at the INPUT, and a failure that keeps the rows (SPEC-181)

This is the spec the Data Explorer exists for, and the only place in it where a user gesture spends
money. Four decisions are worth keeping.

**Every description change goes through ONE `apply`, and that is what makes "one gesture is one
execution" structural.** Four surfaces edit the query — the header menu, filter-by-cell, the
expression bar, the settings dialog — and each of them hands a `Partial<ExplorationQuery>` to
`useExplorationQuery.apply`, which writes the tab's description once; `useExploration` then renders
one statement and the execution cache decides whether it costs anything. Nothing else may write a
description. An apply that changes nothing is a **no-op**, compared with `sameQuery` on a canonical
form rather than field by field, because `filters` and `ordering` are arrays whose order carries no
meaning (priority does) — without that, applying the same filter twice would fill Back with
duplicates of one description. `clearAll` deliberately **preserves `grouping`**: that is SPEC-182's,
and un-grouping a view from a control labelled "Remove all filters" is a change nobody asked for.

> **SUPERSEDED by SPEC-182 (FR-006 AC3): `clearAll` clears the grouping too, and the control's LABEL
> changes with it** — `Remove all filters` becomes `Remove all filters and grouping` while a grouping
> is in force. The concern above was never the clearing, it was the silence; naming the action is the
> other way to keep the same promise. `isEmptyQuery` counts grouping from the same spec, so its
> refusal wording changed with it.

**The hook takes the tabs result rather than reading its own** — a deviation from the spec's
`useExplorationQuery(tabId)`. The history lives with the tab in `sessionStorage` (FR-006 AC3) and
`useExplorationTabs` owns that document, so a second instance would be a second writer to one key,
diverging on the first edit. The tab id still names which tab, because a description and the history
entry it pushes have to be written in **one** update — `updateTab(id, fn)` exists for that; written
through two calls, a tab switch between them files the entry against the wrong tab. For the same
reason there is **no `stage`**: the spec's staging channel is query-only while FR-005 AC3 requires
Cancel to discard the **presentation** changes too, so the settings dialog holds one draft object
containing both halves and `apply` takes the whole staged description. Split in two, half a draft
could survive a Cancel.

**A numeric value is refused at the INPUT, with the renderer's own predicate.** SPEC-178 emits a
numeric filter's value **bare** (Trino does not coerce) and throws `ExplorationRenderError` for a
value that is not a number — and that message names a column and an operator, which SPEC-106 forbids
rendering to anyone. So `isBareNumeric` is exported and both value inputs refuse with it, rather
than each growing a numeric rule of its own that can disagree with the renderer. The same predicate
drives a `Button.disabledReason` on *Filter by this value*, so a numeric column whose cell holds
something unfilterable refuses at the gesture instead of seconds later as a generic failure. The
value itself never reaches SQL unescaped either way: it rides on a `ColumnFilter` and is quoted by
`sqlLiteral` at render time, which is why the whole hazard — a cell containing `O'Brien` filtered by
`=` — is one test and not one code path per surface. Column names are **quoted, never validated**:
`CATALOG_IDENTIFIER_RE` describes names this app CREATES, and a column named `total amount` is
ordinary.

**A failure keeps the last good rows, and Athena's refusal had to be made into an error first.** A
query Athena rejects is not an error anywhere in the plumbing — `getQueryStatus` **resolves**, and
the reason arrives as `stateChangeReason` on a successful poll — so `useExploration` now surfaces a
`FAILED`/`CANCELLED` execution as `{code, message}`, the shape `toUserMessage` maps engine text
from; without it a syntax error surfaced one layer later as "couldn't read the results", a true
sentence about the wrong thing. And `ExplorationResultsRegion` was restructured so the query toolbar
and the expression bar render whatever the results are doing, with `useQueryResults` pointed at the
**last execution whose rows actually arrived** while the current one is failed. A failed apply has
to leave the user somewhere they can correct it, and a toolbar that disappears with the rows takes
the correction with it. The test for this is only meaningful because the failed execution's results
also fail — mocked to succeed, it passed with the fallback deleted.

**FR-006 AC4 needed a mechanism the spec did not name.** "Navigating history never re-runs a query
that failed" cannot come from the cache: SPEC-178 deliberately **evicts** a failed execution on the
way out, so restoring its description would start a fresh one. The tab keeps an in-memory set of
statements seen to fail this session, and a history step onto one **suspends** — `useExploration` is
handed nothing to run and a *Run it anyway* control is the retry. An `apply` always clears the
suspension, because an apply IS the user asking again. The set is not persisted: a failure from a
previous session should not stop this one from trying.

**Cost can only ever be reported, never predicted.** Athena will not say what a query will scan
before running it — no dry run, no `EXPLAIN` byte estimate, and the per-query statistics exist only
once the execution has finished — so a pre-flight "this looks expensive" confirm is **not
buildable**, and the guards are the workgroup's per-query cutoff plus this reporting. A cache hit
**says so** rather than repeating the figure the execution originally scanned, which is true about
the execution and false about the gesture; it is decided by reading the tab's ledger **during
render, before `recordScan` writes to it**, since after that write every execution looks known and
every apply would report itself free.

**A cost is only reportable once the execution is TERMINAL, and the fixtures hid the opposite.** A
`QUEUED`/`RUNNING` poll carries no `Statistics`, so `useExploration` reported a perfectly confident
0 B — and because the per-apply figure is captured once per execution (it must be, to read the ledger
before `recordScan` writes to it), that zero stuck for the life of the query while the running total
beside it said something else. Every test fixture in the feature returned `SUCCEEDED` on the first
call, so the AC's own test passed over a surface that was wrong for every real query. `cost` is now
null until the state is terminal.

Three implementation traps worth naming, because each looked correct and was silent.
`moveSortPriority` stamps priorities from the **array position** after the swap — re-stamping
through the shared "sort by priority, then number them" helper put the two entries straight back,
so the ↑/↓ controls were a no-op the dialog rendered as a success. **State that belongs to a tab
must be keyed by the tab**, and two pieces of it were not: `suspended` froze *every* tab, and the
last-good-execution fallback drew one tab's rows under another's error banner (visible only when the
failing tab had never succeeded — a tab with a good execution of its own falls back correctly either
way, which is why the first version of that test could not fail). And a `Modal` **does not portal**:
`FilterValueDialog` rendered inside a `<th>` would have been confined to that cell's stacking
context and painted under the sticky headers, which nothing in jsdom can see — the region raises it
and the header menu asks.

### A palette is measured, not chosen; a link's encoding depends on where the value lands (SPEC-184)

Everything this spec adds changes how a value *looks* and nothing about what is *fetched*. That is
SPEC-178's rule seen from the other side, and it is now asserted twice rather than promised: a
scripted UI sequence touching every rule and transformer leaves `runQuery` on the tab's opening
execution, and a transitive **import-closure walk** from `renderExplorationSql.ts` proves no module
this spec added is reachable from the renderer at all. The renderer's signature is a promise about
one function; the closure is a property of the whole graph.

### The palette is a bounded token set, because the contrast criterion is otherwise unassertable

FR-002 AC8 asks that every colour pairing meet contrast requirements. Nothing can promise that
about a colour picker, so the model narrows the spec's `foreground?: string` to a five-token union
(`text`, `text-2`, `accent-text`, `success`, `danger`) and its backgrounds to the four `*-soft`
tints, all of them tokens `index.css` already declares — this spec adds none.

**`warning` was measured out of the foreground set.** It clears 4.5:1 on white (5.02) and fails on
the soft backgrounds this spec introduces: **4.49 on `accent-soft`, 4.39 on `danger-soft`**. A
colour that is legible only sometimes is worse than one fewer colour, because nothing at the point
of choosing tells the user which case they are in. The test recomputes the full cross product, the
**sampled gradient** at every step it can quantise to — including the mixed shades between two
tints of different hues, where a "both ends are pale" argument breaks — and the exclusion itself,
so a token that moves reddens CI rather than quietly failing WCAG.

**The surfaces measured against include the SELECTION.** A formatted cell is still selectable, and
an inline background beats the class that paints a selected one — so the cell drops its formatting
fill while selected (`aria-selected` says so either way), and `accent-soft` is one of the three
base surfaces every foreground has to clear.

**Axe cannot carry this criterion.** `color-contrast` is disabled in `test/axe.ts` because jsdom
has no layout engine, so the axe pass over a coloured grid proves its markup and the computation
proves its contrast. Reporting "the axe pass is green" as evidence of contrast would be a claim
that tool never makes.

`FORMATTING_TOKEN_HEX` exists only because a gradient must interpolate values and contrast must be
computed from them; a second test pins every entry against `src/index.css` itself, since a copy
needs a guard. Vitest resolves a stylesheet `?raw` import **and** a raw `import.meta.glob` to an
empty string (measured), which would have made that guard pass by finding nothing — so it reads the
file, through a one-function ambient declaration rather than by adding `"node"` to the app's
`types` and handing every module in `src/` the Node surface.

### The URL transformer's encoding is position-dependent, and both simple rules are wrong

Encoding the value **unconditionally** is right inside a path or a query — a value must not climb
out of its segment, add a parameter or graft a fragment on — and wrong at the **start** of the
template, where `${value}` is the natural template for a column that already holds links: encoding
turns every legitimate `https://…` into `https%3A%2F%2F…`, so that column can never link at all. It
also makes FR-006 AC2's own worked example unreachable, since a `javascript:` cell would then fail
as "not a URL" rather than at the scheme check. Not encoding at all is the other wrong rule.

So the **leading** position substitutes raw and every later one is encoded, and the `https:`
allowlist — judged on the **resolved** URL, never the template — is what guards the leading case.
An allowlist rather than a blocklist, because the blocklist is the one that has to be complete.

The substitution is assembled part by part rather than with `String.replace`, whose replacement
string reads `$&`, `$'` and `` $` `` as patterns: a cell holding one would be expanded into
something other than itself *before* anything parsed it. Anchors carry `rel="noopener noreferrer"`
and `target="_blank"`; a refused scheme renders as plain text with its reason reachable.

**`isSafeInAppPath` is deliberately not used, and the call site records why.** That rule
(SPEC-061/167) governs IN-APP paths — it asks whether a link is a route inside this application and
answers by refusing anything not root-relative. Every URL here is external and absolute, so it
would reject all of them, and loosening it would have it answering a question it was never written
for. Reaching for a rule that sounds adjacent is how a confident category error ships.

### A rule's `scope` is a field the spec's model did not have

`ColourRule` carries `column?` — the spec read an absent column as "apply across the row", which
conflates what a rule TESTS with what it PAINTS and leaves the most ordinary rule inexpressible:
colour the whole row wherever `status` is `failed`. One optional `scope: 'cell' | 'row'` separates
them (SPEC-181's `valueKind` is the precedent), and an absent `column` keeps its own meaning — test
every cell in the row.

Precedence runs weakest to strongest — type tint, then band, then rules in order — and each layer
overrides only the **property** it sets. That is what makes "a later rule overrides an earlier one
on the same property" and "conditional rules win over both the type tint and the band" true without
a special case for either. **A NULL matches nothing, including `<>`**: NULL is the one value Athena
does not hand back as a string, and "is not 5" over a value that was never there would paint every
empty cell in the column.

### The raw value drives everything, and the transform lives at the cell

`transformCell` is called at the cell and nowhere upstream, so a filter, a colour rule, Calc and
copy all read the raw row — a transformed value reaching any of them is a silent wrong answer
rather than a visible one. The Calc assertion uses a **hex** transformer deliberately: `10` renders
as `3130`, which is itself a plain number, so a Calc reading the rendering would answer a wrong
number rather than fail visibly. NULL and the empty string are returned untransformed, because both
are absences the grid already names in words.

**The Text view stays raw** — no colours, no transformers. It is the drag-select-and-copy surface,
and its whole promise is that what is on screen is what is copied.

### A link in a grid is not a tab stop, and the app must not manufacture backtracking

Two review findings that generalise beyond this spec.

**`role="grid"` promises ONE tab stop**, which is why every cell but the cursor carries
`tabIndex={-1}` — so a URL transformer's anchor is `tabIndex={-1}` too, or a hundred rows put a
hundred stops inside the grid and Tab walks the column instead of leaving. The **Value panel
carries a focusable copy of the link**, which is what makes that cost a keyboard user nothing, and
the Record view — which already wraps every value in a button — renders the text without an anchor
at all, because an anchor inside a button is nested interactive content. No axe case had rendered a
transformed cell, which is how a `nested-interactive` violation reached review; the file now walks
both views, and the fix was verified by reverting it.

**A wildcard translated one for one manufactures catastrophic backtracking.** Mapping each `%` in a
`LIKE` pattern to its own `[\s\S]*` makes adjacent wildcards nested unbounded quantifiers:
`%%%%%%%%x` against a 60-character value measured at **31.7 s**, in a `useMemo` that runs once per
cell. A length cap bounds the input, not the runtime — and `%%%` is not a hostile regex, it is what
a user types believing it is a wildcard. Runs of `%` collapse to one: identical matches, 0 ms.

### A hidden column is still part of the row

Formatting is evaluated over EVERY column, not the visible ones. A rule reading `status` must keep
painting its row after `status` is hidden, and the dialogs are handed the same list, so what they
report as applicable is what the evaluator can actually see — judged over the visible columns, the
dialog called a rule fine while it silently did nothing, and striping turned itself off when every
chosen column was hidden. Formats for hidden columns are simply never looked up.

### A stored formatting block is discarded WHOLE

Unlike the field-by-field normalisation beside it, `formatting` is validated as a unit and replaced
with defaults if any part of it is wrong: a partially-applied colour set is a rule list the user
never built, and a rule that survived while the one meant to override it was dropped paints the
opposite of what was intended. The colours are validated against the **palette**, not merely
against `string` — a stored `#ff0000` would render verbatim as an inline style, and the contrast
the palette is measured for would no longer hold for it. A rule naming a column the current result
lacks is **kept and shown as inapplicable**: a grouping change replaces the column set wholesale, so
that is the ordinary case, and un-grouping brings the column back.

### Copy is the selection-shaped tool and export is the result-shaped one, and reusing the save path meant moving it (SPEC-185)

### The two ways out divide on the line the whole arc divides on

Copy takes the **cell selection**, which exists only in the browser: `renderCopy` is a pure function
over the rows already fetched, so copying — in any of six formats, with any options, however many
times — starts no execution and scans no bytes. Export copies the **execution's own results object**
with a server-side `CopyObject`, so what leaves is every row the statement returned rather than the
25 in the grid, again with no second query and no second bill.

That is why **exporting a selection is out of scope** rather than merely unbuilt. A partial export
would need either a second query — the one thing this feature spends ten specs avoiding — or a
client-side re-serialization of rows that are not all loaded, which is the scale lie the whole arc
was designed around. And it is why copy's formats are clipboard-only: the results object is Athena's
CSV, and converting it would mean reading it back through the browser.

Both surfaces say the asymmetry out loud, because it is not inferable. The advanced copy dialog
states that only the loaded page is copied and points at Export for the rest; the grid's status line
says `N cells selected on this page` every time it says anything, which is SPEC-182's rule for Calc
applied to the same fact.

### A NULL and an empty string stay apart in all six formats, and quoting is what disambiguates the WORD

FR-001 AC4 costs nothing in the three formats that have a null of their own — JSON emits `null`, SQL
emits the keyword, XML gets an explicit `null="true"` attribute rather than an empty element. The
delimited formats and Markdown have no such thing, so a NULL renders as the token `NULL` and an
empty string renders as nothing at all. Those two are always distinguishable.

What is **not** distinguishable in a delimited format is a NULL from a cell whose text is literally
`NULL`, and that is the honest limit rather than a defect: `quoteValues` is the answer, since a
quoted `"NULL"` is a value and a bare `NULL` is an absence. The dialog says so beside the control.

`quoteValues` is **inert** in JSON, SQL and XML, whose values are already delimited by the format —
so the checkbox is disabled there with its reason next to it, rather than offered as a control that
silently changes nothing. Two smaller rules fall out of the same reasoning: CSV still quotes what
the *format* requires (an unescaped comma is not ambiguous CSV, it is CSV with an extra column),
and a Markdown table keeps its header row with column names off, because a table without one renders
as a paragraph of pipes in every dialect.

### A discontiguous selection copies as a rectangle, and a SQL INSERT names a placeholder

A selection with gaps copies as its **bounding rectangle**, with the unselected cells blank. Packing
the selected cells together would silently move values into columns they were never in — a paste
that is wrong in a way nobody can see, where a hole is wrong in a way anybody can. It is stated in
the dialog rather than left to be discovered.

The `INSERT` names `"results"`, deliberately not the source table. These rows are what a filter, an
ordering and possibly a `GROUP BY` produced, so an INSERT naming the source would be valid, runnable
and wrong. Values go through `lib/sql.ts`'s `sqlLiteral` — the **Trino/DML** escaper that doubles
the quote, never `cpcommon.ddl.literal`'s backslash form (SPEC-178's rule; the wrong one fails
silently). XML puts the column name in an **attribute**: an Athena column name is not required to be
a valid XML name, and deriving element names from one produces documents that do not parse.

The copy reads the **raw row**, never `cellText` and never SPEC-184's `transformCell` — a
URL-transformed column pasted into a spreadsheet has to carry its value, not its link text. The test
that proves it uses a **hex** transformer on SPEC-182's precedent, because a URL transformer keeps
the raw value as its link text and the assertion could not have failed.

### Reuse required a MOVE, and the move closed a live flag defect

`useSaveResults` lived in `features/query/`, which `features/data-explorer/` may not import
(SPEC-176's sibling clause). "Reuse it unchanged" was therefore unreachable from where it sat, and
the two alternatives were a second implementation of a path with a collision round-trip in it, or the
move SPEC-176 and SPEC-177 already established. It went to `features/catalog/` — which owns the
Athena execution and results layer, and the results object is exactly that — with its body untouched,
`SaveResultsDialog` and `normalizeCsvName` with it, and `features/query/query.format.ts` deleted
because nothing else was in it.

**One thing about the hook did change, and it is why the move was worth more than the reuse.** It
built its own destination list from an unfiltered `useQuerySpaces()`, while every saved-query surface
beside it used a view-gated list — so with `sharedWorkspaces` off, the Query workspace's Save-results
dialog had been offering a colleague's space as a **write target**, unregistered and unnoticed since
SPEC-055. The destinations are now a **parameter** (SPEC-174's shape, and SPEC-177's), both views
hand it a gated list, and both instances have their own `GATED_SURFACES` row — SPEC-175's finding
that each selector instance needs one, applied to the instance that had been missing.

Export's refusal is judged on the **results location**, not on the grid: Athena reports it only for a
SUCCEEDED execution, so "nothing has finished running" and "there is nothing to export" are one fact
rather than two that can drift. A failed apply leaves the last good execution's rows on screen while
that field has already moved on, which is the case a rows-based test would get wrong.

### Every guide row before this spec lived in the section the Help page opens on

The walking test's guide recipe queried a guide card without selecting its owning section. That
worked for four rows by coincidence — all of them were in `files`, the default section — and would
have returned `null` in **both** flag states for a row anywhere else, which reads as "correctly
hidden" rather than as a recipe that cannot see its surface. The recipe now selects the section
first, and returns null only when the section itself is gone (the `files` shape, where a section row
and a guide row share one flag).

The Data Explorer gets **its own Help section** rather than guides folded into Query: it is a
primary nav destination with its own flag, and a user looking for it in Help should find it by name.
The section and each of its five guides get a registry row, on the `files` precedent — the section
row alone would suffice today and would go on passing if a later spec moved one guide into the Query
section, where it would then be visible with `dataExplorer` off.

The guides document only what is shipped and wired (SPEC-074 FR-005), which here means saying two
things plainly that the UI cannot: that **every filter and sort runs a real query against Athena and
scans data**, with the figures at the bottom as the cost signal; and that a saved exploration
**reopens in the Query workspace as SQL**, not back here as an exploration — SPEC-183 descoped the
loading half, so a guide promising otherwise would document a spec that has not been written.

---

### A default that an empty string can defeat is not a default (SPEC-186)

**Context.** A live-check session on 2026-08-14 discharged several long-owed checks and, in doing
so, found that a number of *other* owed checks could not be performed at all — not because the
behaviour was broken, but because the assertion they named was unreachable from any principal or
surface a human has. A check nobody can run is indistinguishable from a check that passes, which is
SPEC-138's "did not run is never clean" and SPEC-137's blind gates in a third place. The same
session found, by eye, that nine dialogs rendered at full viewport width.

### `??` does not fall back on `''`, and a helper returning `''` is a trap for every consumer

`cx()` returned `string` — never `undefined` — so `FormDialog`'s
`cx(scrollBody && '…', className)` handed `Modal` an **empty string** whenever its caller passed
neither prop, and `Modal`'s `className ?? 'max-w-md'` took that as a deliberate choice to have no
width. The panel's `w-full` then filled the viewport. **Nine dialogs**, one line: `New folder` and
`New shared connection` measured 1372px in a 1400px viewport with `max-width: none`, against
`Create table`'s correct 448px.

Fixed in the shared layer **twice**, deliberately: `cx` returns `undefined` when nothing is truthy
(so the trap is gone for the next `??` consumer anywhere in the app), and `Modal` uses `||` (so a
caller composing its own class string is still safe, which is what the AC's `className=""` test
requires). Widening `cx`'s return type to `string | undefined` type-checked at every call site with
no change — the two that wanted a string for `aria-describedby` already coerced with
`|| undefined`.

**Note the direction of the bypass.** The four dialogs that hand-roll their chrome pass an explicit
`max-w-lg` and were therefore *unaffected*; the nine that correctly used the abstraction were the
broken ones. That is an argument for fixing the shared layer, not for copying more.

### A refusal announced after the confirm is worse than no affordance at all

`fileBrowser.service.ts` always refused deleting `saved_queries/` — but only after the user read
*"Delete the folder "saved_queries" and everything inside it? … This can't be undone."* and pressed
Delete. The most alarming confirm in the app, shown for an action that was never possible.

`undeletableSelectionRefusal` feeds `Button.disabledReason` (SPEC-172's `aria-disabled` affordance),
and because `Button` swallows the click, **"no confirm is reachable" falls out of the mechanism**
rather than needing a second guard. `ConfirmDialog` gained `confirmDisabledReason` on the same
pattern for the refresh dialog's opt-in — `busy` still wins and stays natively `disabled`, because
an operation in flight is not a refusal.

The test asserts **`alertdialog`**, not `dialog`: the confirm carries the former, so querying for
the latter would have passed whatever happened. A negative assertion has to name the thing it is
denying.

### jsdom has no layout, so a containment property must be arithmetic

The suggestion listbox overhung the Add-members dialog by **97px** (3 of 8 options visible) because
its flip logic measured `window.innerHeight` — right for a combobox on a page, wrong for one inside
a dialog, where `Modal`'s panel is `overflow-y-auto` and is what actually clips it. The component
now walks to its nearest scrollable ancestor and caps the list to the room there is.

The AC asked for a numeric assertion (`listbox.bottom <= dialog.bottom`), and **jsdom reports every
rect as zero**, so the geometry moved into a pure `listPlacement()` and the test derives the list's
far edge from the returned placement — over the measured case and over a sweep of every field
position in a 600px dialog. The DOM test asserts only what the DOM can see: that the bound is a
*measurement* rather than the old fixed `max-h-60`.

The flip is deliberately **conservative** — it goes up only when below is cramped AND above is
roomier — because below is where the reading order expects the list.

### A procedure that cannot produce its claimed outcome invites a false bug report

Two live-check scripts described impossible procedures, and one of them was followed and read as a
defect until the code was checked.

**Schema inference samples exactly ONE object — the first key in listing order**
(`sample_by_format.setdefault(fmt, key)`, and S3 lists lexicographically). A column added in a file
that sorts *later* is invisible **by design** and the refresh correctly says `already up to date`.
The fixture must name a file that **sorts first**.

**Two UI submits cannot contend for SPEC-157's lock.** Two submits 2 s apart — the floor two
pre-armed tabs allow — both returned independently, because a small table's refresh completes inside
that window. The check needs an SQS double-send or a several-hundred-object folder.

**And SPEC-173's marker check was unrunnable as written**, which is the third instance: the portal
issues **zero** `DeleteObject` against the marker (hidden by basename, folder refused client-side),
so the bucket-policy Deny — the layer the check exists to prove — was never exercised. Split into
two separately-numbered checks, because neither layer's result says anything about the other's.

**Any procedure needing a raw ID token says so up front**, says where it is read from, and says it
must not be pasted into a shell command — it is a live credential and it lands in history.

---

### A persistent in-flight surface is NEW scope, with no precedent here (SPEC-190)

The three async planes already in the file browser — send, archive, restore — have **no in-flight
surface at all**. They push a toast and hand off to notifications, which is survivable for an action
the user chose to fire and forget. The upload queue is not the precedent it looks like either: its
provider is session-scoped at the shell so uploads survive navigation, but its list renders inside a
drawer that exists only while it is open.

This one is justified on its own merits, because these gestures **replaced synchronous ones**. A
user who copies a folder and watches nothing happen has no way to tell "accepted, running in the
background" from "the click missed" — where before, the listing simply updated. That is the
regression the surface exists to prevent, and it is the reason a citation would not have done.

It is session-scoped and **not persisted**. The notification is the durable channel; a stored queue
would be a second writer to state the plane owns, and it would outlive the only thing that can
settle it. Three bounds keep it from wedging the per-space submit gate: an entry settles when a
notification carrying its `requestId` arrives, every entry is user-dismissible, and every entry
expires at the machine's own `TimeoutSeconds` (mirrored in the browser and pinned to `locals.tf` by
a test). The dismiss is load-bearing rather than tidy — a request that dead-letters produces a
notification with no payload to correlate against, so it is the only thing that frees that space.

### There is no progress percentage, and there cannot be one (SPEC-190)

`onProgress` went with the browser's own copy loop: the plane reports outcomes at the END of a run
and nothing in between, so any percentage the browser drew would be invented. The surface says
**what** is running and **since when** instead. This is not a gap to fill later by polling the
execution — that would be a second read path to state the notification already reports, on a plane
whose whole point is that the browser stops watching.

### The kill switch is a flag key, and it is the sixth (SPEC-190)

Five flags are areas; `asyncFileOperations` is a switch over the file browser's copy/move/delete
routing. It earns a key rather than a build-time constant because its only other kill switch is
`files: false`, which removes the entire file browser — and because publishing a flag needs no app
build, which is what makes the largest user-visible change in the product survivable. Default **on**,
keeping the all-on fallback rule intact: an unreadable document must never change behaviour. Off,
every gesture keeps the browser's synchronous path exactly as it was.

Its two registry rows are the in-flight surface and the conflicts guide. **The conflict VIEW is
registered under `files` instead**, deliberately: throwing the switch must not strand a conflict
raised before it was thrown, and resolving one finishes work the plane already started rather than
beginning a new gesture — and it keeps the `Review conflicts` control already shipping on
notification rows from becoming a link to nothing. A row's `name` is its accessible name and
`RECIPES` keys are unique, so one control cannot hold a row under two flags; the choice had to be
made rather than hedged.

## Infrastructure, IAM and delivery

### IaC

OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.

### Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)

`deploy-infra.yml`'s `workflow_dispatch` takes an off-by-default `skip_refresh` boolean that adds `-refresh=false` to the apply. It exists because **the deploy role can lock itself out**: tighten (or widen) one of its own grants and the next refresh needs the permission the pending change would restore, so plan, apply **and revert** all fail on the same `AccessDenied`. Applying from cached state installs the fix and unblocks normal runs. **Deliberately unreachable from `push`** — skipping refresh means drift is not detected, so it must be a conscious act; the step emits a warning telling the operator to follow up with an ordinary run, and that follow-up is not optional (an apply that skipped refresh has proved nothing about drift). It replaces the out-of-band `aws iam put-role-policy` break-glass as the *preferred* escape, because it needs no AWS access outside CI — that break-glass stays as the fallback. First use: 2026-08-02, recovering from the SPEC-139 follow-up (`lambda:ListTags` removed from an event-source-mapping statement on the false assumption that the function-scoped grant covered it — a mapping ARN and a function ARN are different resource types). **Caveat worth knowing before trusting any single run:** during that incident `plan` passed twice while `apply` failed on the identical call with no policy change between them, so IAM's eventual consistency can make the deadlock look intermittent — a green plan is not evidence the permission problem is fixed. Full trap list: `architecture.md` → *Deploy-role IAM — adding a new resource type*.

### Response headers / CSP (SPEC-140)

> **Superseded in part by SPEC-194 (2026-08-27), on two points.** *Where the policy lives:* both
> CSP locals are at **root** now, not in `modules/app` — a check at root cannot read a local inside
> a module, and that module is deleted when the distribution is retired. The four-input shape
> described below is gone; `connect-src` is assembled at root from the same variables plus the API
> origin, and the module takes the assembled policy as an input. *Who emits it:* the container
> serves the same policy from nginx, with `connect-src` supplied by the task definition and every
> other directive baked in the image. The rules below are unchanged and inherited — enumerate from
> the hosts the app **fetches**, verify with a same-origin page script and a negative control, diff
> per alert ID. HSTS `preload` is dropped for the container's domain, re-decided.


One `aws_cloudfront_response_headers_policy` on the distribution's default cache behavior carries the browser-facing security posture — **enforcing** CSP, HSTS (`includeSubDomains`, **no `preload`**), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP — and strips `Server` and `x-amz-server-side-encryption`. Four decisions carry the weight. **(1) The CSP is assembled from variables, never literals.** `connect-src` *is* the app's network surface — there is no backend, so anything missing from it is a broken feature — and it is built from `var.aws_region`, the two bucket names and the Hosted UI domain, passed as **constructed strings from root locals** because `modules/app` is upstream of `base → data` and a module reference would be a dependency cycle. A hardcoded region or bucket would have to be hunted down during the client-environment transition. (**Correction 2026-08-04:** the Hosted UI domain was missing from the shipped list, and it broke sign-in outright once the policy went enforcing — Amplify's authorization-code exchange POSTs to `https://<hosted-ui-domain>/oauth2/token`, which is **not** `cognito-idp`, so the returning `?code=` was never redeemed and the app sat signed-out over a live Cognito session. Enumerate `connect-src` from the **hosts the app actually fetches**, not from the AWS services it uses.) **(2) Report-only first is not ceremony.** A CSP wrong about `worker-src` or `style-src` breaks the Monaco editor in production and nowhere else, because no unit test observes a CSP. It earned its keep twice: it caught that `src/index.css:1` `@import`s Inter from `fonts.googleapis.com` (Vite leaves remote `@import`s in built CSS, so an enforcing CSP would have stripped the typeface site-wide), and it exposed that **Safari refuses to evaluate a report-only policy naming no reporting endpoint** — logging "the policy will have no effect" and applying nothing, so a verification pass reports zero violations whether or not any occurred. Chrome and Firefox honour report-only without one, which is exactly why a Chromium-based harness cannot surface it; the same reason CDP `Runtime.evaluate` is useless for CSP probing, since it bypasses page CSP entirely (it reported `new Function` as *allowed* under `script-src 'self'`). Verify a CSP with a **same-origin page script**, and always include a negative control that proves enforcement is live. (**Correction 2026-08-04:** report-only also has a blind spot the promotion to enforcing walked straight into. Report-only **never blocks**, so the sign-in pass that "reported no violations" succeeded *because* the policy was inert, and the one violation it did raise was reported to an endpoint nobody read. A report-only pass proves a flow still works; it proves nothing about whether the flow would survive enforcement. **Read the violation reports, or re-run the flow against the enforcing policy before calling it verified.**) **(3) Three findings are accepted, not silenced.** `Cross-Origin-Embedder-Policy` is absent because `require-corp` buys cross-origin isolation this app cannot use (no `SharedArrayBuffer`, no high-resolution timers) at real risk to subresource loads. `preload` is absent because it declares an intent to submit to hstspreload.org that we do not have, on a shared-suffix `*.cloudfront.net` name a custom domain will replace, and it is near-irreversible once granted — this **fails Checkov `CKV_AWS_259`, whose sole objection is that flag**. (**Update 2026-08-03:** `preload` was flipped on, clearing `CKV_AWS_259` — it is inert without an hstspreload.org submission, so **never submit this `*.cloudfront.net` domain** to hstspreload.org.) `style-src 'unsafe-inline'` stays because Monaco injects `<style>` at runtime — this is a **new ZAP Medium introduced by the fix itself**, and removing it needs per-response nonces, impossible on a static S3+CloudFront origin without Lambda@Edge; `script-src` carries no such allowance, which is the one that matters. **(4) A finding total is not a signal.** `CKV2_AWS_32` clearing and `CKV_AWS_259` appearing cancelled at 305, so the Checkov total looked untouched; ZAP went 20 → 13 while gaining a Medium. Diff **per check ID and per resource**, never by count. Full account: `docs/spec-delivery/SPEC-140-cloudfront-response-headers.md`.

### Static-asset caching = three prefix-scoped sync passes (SPEC-141)

> **Superseded in part by SPEC-194 (2026-08-27).** Everything below is true of the S3 delivery
> path, which is now **one of two**. The container image IS the file set, so the `--delete`
> reconciliation pass and the accepted stale-root-object orphan class do not exist for it; it
> reproduces the per-class scheme in nginx and stops there. Both retire outright with the
> distribution.


`deploy-app.yml` uploads `dist/` in **three passes**: hashed assets under `assets/` as `public, max-age=31536000, immutable`, then the shell and root files as `no-cache`, then a repeat of the assets pass carrying the **one** `--delete`. Four things make that shape non-negotiable. **(1) The bug was the BROWSER cache, not the CDN.** The deploy already invalidates `/*`, so CloudFront never served a stale shell; with no `Cache-Control` anywhere, browsers applied **heuristic freshness** to `index.html`, and `--delete` had already removed the hashed bundle that shell referenced — **a white screen, not stale content**, on exactly the users whose cache was warm, and unreproducible with devtools caching disabled. Reach for the origin object's headers, not an invalidation, when the symptom is "some users see a broken app after a deploy." **(2) `--exclude` PROTECTS destination keys from `--delete` — it does not endanger them.** The CLI filters the reverse (destination) generator with the same patterns re-rooted at the destination (`awscli/customizations/s3/filters.py` builds `dst_patterns` beside `patterns`; `subcommands.py` gives `rev_generator` its own filter), so an excluded object is never a deletion candidate. The consequence: **a pass that excludes a prefix can never reconcile it** — `--delete --exclude 'assets/*'` keeps every stale chunk forever. Scope passes by **prefix** (`dist/assets/` → `s3://…/assets/`) so each owns a disjoint key set. (*Corrected 2026-08-04 by the SPEC-141 review, which read the CLI source: the original entry, the workflow comment, and SPEC-141:108-109 itself all stated this backwards — claiming an excluded `index.html` would be deleted. The implementation was never affected; only the reason was wrong.*) **(3) No file may be uploaded by two passes.** `sync` compares size and mtime, and a fresh CI checkout makes every local mtime newer than the bucket's — the first deploy re-uploaded all 108 assets on a byte-identical build, confirming a second pass over the same files would overwrite the immutable header with that pass's `--cache-control`. **(4) Deletions therefore live on their own pass, and the surviving orphan class is a SPEC CHOICE rather than a CLI constraint.** `--delete` scoped to `assets/` leaves stale **root-level** objects behind (harmless, unreferenced, removable by hand). Adding `--delete` to the shell pass **would** reconcile those — `--exclude` protects every asset key from that same deletion (verified against the CLI's `dst_patterns`), and the assets pass still reconciles chunks, so nothing would be retained. What forbids it is SPEC-141's AC "exactly one sync pass carries `--delete`", **written on the same mistaken reading of `--exclude` corrected in (2)**. Revisit the AC deliberately if the manual cleanup becomes annoying; the cost to weigh is that a root-scoped `--delete` removes anything in the bucket not produced by `dist/` (nothing else writes it today). `icons.svg` is the first such orphan. The residual race is **accepted and documented**: a tab already open that lazy-imports after the delete pass still 404s inside `Suspense` — **both** lazy routes are exposed, `/query` (which loads Monaco beneath it) and `/connections`, so a fix must not be scoped to Monaco; closing it needs retained bundles behind an S3 lifecycle rule. Rule of thumb for the whole area: **a content-hashed URL is immutable, a stable URL must revalidate**, and prefer a path prefix over an extension list — `dist/assets/` carries a `.ttf` that a js/css rule would miss. Full account: `docs/spec-delivery/SPEC-141-cache-control-headers.md`.

### A build stamp belongs to the artefact; an environment name belongs to the environment

Every structured log record shipped `"version": "0.0.0"` and `"env": ""` — fields that exist to
correlate a record to a deploy and filter by environment, both inert.

`ENV_NAME` is Tofu's to set and now ships on **every** Lambda from `var.environment`, the same
source of truth as the feature-flag document's `environments` keys. `BUILD_VERSION` is **not**:
Tofu owns the environment map, `update-function-configuration --environment` REPLACES it whole (so
a workflow write would race an apply or be reverted by the next one), and Deploy Infrastructure is
path-filtered to `infra/**` — so a Tofu-set sha would name the last *infra* commit rather than the
code that is running. The stamp travels **in the package** instead, written into every zip by
Deploy Lambdas and read once at import. A missing or unreadable stamp degrades to the sentinel and
**never raises**: this module is on the layer every control-plane verb attaches, and PR #196 is what
an import-time failure there costs.

### Consolidation is worth doing against a SWEEP, not against a list

The reuse pass found that the problem is not missing components — it is existing components being
bypassed and then drifting. Three chip lists were byte-identical until one grew a 24x24 remove
target and the other two stayed at **20x20**, under WCAG 2.2 SC 2.5.8's minimum; `Badge` shipped and
was used by two files while three others hand-rolled it, each differing by a token or two.

The spec enumerated six status-pill sites; the sweep found **seven** (`LandingPage`, whose own
comment said "Mirrors UploadList's StatusChip"). It counted eleven caption sites; the sweep found
**22 files** across three spellings. A `?raw` glob guard now holds each shape to one home, with a
guard-the-guard asserting every needle still matches its owner — because "found nowhere" reads
exactly like "consolidated".

Two deliberate visual changes, on SPEC-155 FR-007's precedent: neutral pills gain a border, and
`QueryHistoryRow`'s neutral dot brightens from `text-text-3` to `text-text-2` now that every dot is
`bg-current`. **Chip width is bounded** for the first time — a 63-character username
(`^[a-z][a-z0-9_]{2,62}$`) extrapolated to a ~610px chip inside a 448px dialog.

**`components/` may export only components** (react-refresh), which is why the shared class strings
live in `fieldStyles.ts` / `dialogChrome.ts` and `displayedMemberStatus` in `memberStatus.ts`.

### Configuration is a runtime document, and a production build has no fallback (SPEC-192)

The SPA reads `/config.json` at startup instead of the `VITE_*` values Vite inlines at build time.
The whole point is promotion: an artifact carrying one environment's bucket names, queue URLs and
Cognito ids can only reach the next environment through a rebuild, and a rollback through a rebuild
of an older commit. Twenty keys, every value a **string** — the task environment that renders the
document is strings, and a JSON number would add a second parse path with its own failure mode for
one key.

**A production build has NO fallback, and `configValue` THROWS before the load resolves.** Returning
`undefined` is the failure the classification exists to prevent — a generic SDK error about a bucket
named "undefined", surfacing far from its cause — so re-introducing it here would make the mechanism
decorative. A **dev** build falls back to `import.meta.env`, including when no load has happened at
all: that is what lets the existing suite read configuration with no bootstrap and without changing a
single `vi.stubEnv` call site. The consequence is that **the entire test suite exercises the arm that
will not exist in production**, which is why the production arm is tested by stubbing `DEV` false and
why the live checks are not optional.

**The fallback is ELIMINATED from the production bundle, and that is asserted on the built output.**
Guarding it is not enough: `readEnv`'s table and the key→variable map are tables of `VITE_` names as
*strings*, and they only disappear if every reference to them sits syntactically inside an
`import.meta.env.DEV` branch. `npm run check:bundle` fails if any `VITE_` name survives in
`dist/assets/*.js`, and it hard-fails on a missing bundle, because "did not run" is never "clean". It
detects the *table*, not an unported call site — Vite substitutes the variable's **value**, leaving no
name behind — so the call sites are pinned separately by a `?raw` sweep to exactly five files.

**A 200 carrying HTML is `unparseable`, not a success.** The distribution answers a missing object
with its own `index.html` under a **200**, so a deployment that never published the document gets a
successful response full of markup. A loader keyed on `response.ok` passes every other test and fails
that one; the fixture is the real `index.html`.

**The document and the feature-flag document look alike and their failure semantics are OPPOSITE.**
The flag document's degraded path is total and silent by design — an unusable one resolves the
compiled-in defaults and still reports ready. This one is a **hard boot failure**: `BootFailure`
renders, no route mounts, and one `console.error` carries the reason and, for a missing required key,
the key **NAMES** — never a value. That narrows the "production stays silent" rule deliberately: the
rule exists so a deployed app does not print its configuration, and a key name is not configuration,
it is the only diagnostic an operator staring at a failed task has.

**`no-store` is not left to the upload's flag.** A document answered from a cache populated in the
previous environment renders a working, fully-functional portal pointed at the wrong account, and
nothing on screen distinguishes it. CloudFront's `Managed-CachingOptimized` applies its **1 s MinTTL
even against an origin `no-store`**, and an object that ever reaches the edge without the header takes
the **24-hour DefaultTTL** — so `/config.json` has its own `Managed-CachingDisabled` behaviour, with
`response_headers_policy_id` re-attached because it is per-behaviour and **not inherited** (omitting
it would serve the document with no CSP or HSTS and stop stripping `Server: AmazonS3`). The
consequence, recorded rather than glossed: after that behaviour lands **no live check can distinguish
a present from a missing origin header**, so the `no-store` negative control was withdrawn and the
header is verified by direct read.

**The bootstrap is a DYNAMIC import, and awaiting the load is not enough on its own.** A module's
static imports are evaluated before its first statement runs, so `import App from './App.tsx'` would
evaluate the whole application graph before the document is fetched, and any module-scope read in it
would throw before the app could render its own failure — in production only, because the fallback
answers in dev and in CI. `main.tsx` therefore keeps five static imports, pinned by a sweep that fails
if the set **grows**, and reaches the app through `await import('./AppRoot')`. The three module-scope
reads that existed are converted as well (`isAmplifyConfigured`, `devS3Client()`, `maxUploadBytes()`),
belt and braces: the dynamic import also protects a read a later spec adds without thinking about boot
order. A **deadline** on the fetch ships with it, because nothing renders until the load settles and
an origin that accepts the connection and never answers would otherwise be a blank page with an empty
console.

Detail: `spec-delivery/SPEC-192`.

### There is no NAT gateway, and the endpoints are the whole outbound story (SPEC-193)

The private subnets carry no default route of any kind. A Fargate task reaches ECR through
`ecr.api`, `ecr.dkr` and `logs` interface endpoints with `private_dns_enabled`, and reaches the image
layers through an S3 **gateway** endpoint whose prefix-list route is what makes it reachable without
a default route at all. A NAT gateway would cost about $32/month per AZ before a byte moves, and —
the part that matters more — it would silently widen the blast radius of every future task from "the
AWS services we enumerated" to "the internet".

**The residual is a connect timeout, and it is the reason flow logs are on.** A destination nobody
added an endpoint for does not fail fast; it hangs, and a hang leaves nothing behind. Flow logs are
the only record of a rejected packet in a design whose premise is that certain traffic cannot leave.

**The no-NAT assertion is repo-wide rather than module-scoped**, because scoped to the network module
it would be satisfied by adding the gateway somewhere else — which is exactly what a quick fix for a
mysterious timeout looks like.

**Verified live, and only live.** `runningCount == 1` with no `CannotPullContainerError`, read
**beside** `describe-route-tables` showing local + prefix-list and no `0.0.0.0/0`. Without that
pairing, a pull that succeeded through a route somebody added reads as proof of the endpoints.

Detail: `spec-delivery/SPEC-193`.

### The API function is not in the VPC (SPEC-193)

The VPC exists for the container. Attaching the API function would need an interface endpoint per
service it later calls and would put ENI attachment on the cold-start path — and after the arc's
provider swap the token-verification host is a third party with **no AWS endpoint at all**, so a
function inside those subnets would stop verifying with no code change to blame.

Asserted as an **absence** (`vpc_config`, `aws_security_group`, `subnet_ids` forbidden in the module),
because a `vpc_config` added later shows up only as latency until the day it shows up as a timeout.

Detail: `spec-delivery/SPEC-193`.

### The image tag is the commit sha, and `:latest` does not exist (SPEC-193)

The ECR repository is `IMMUTABLE`. An image is therefore what its tag says it is for as long as the
revision referencing it exists, and a re-push under an existing sha cannot silently change what a
rolled-back task definition starts.

**The consequences are not cosmetic.** There is no `:latest` to point a task definition at, so the tag
is a **variable** (`spa_image_tag`) rather than a constant — a fixed placeholder tag could be pushed
exactly once, ever, and a bad first push would burn it. And a tag cannot be re-pushed after a bad
build: the fix is a new commit, not a retry.

**The service's `task_definition` is in `ignore_changes` and its `desired_count` is NOT**, which is a
division of ownership with teeth. CI owns which revision runs — so **CI must point the service**, and
a pipeline that only registers a revision leaves the service on the old one, failing with a
`CannotPullContainerError` that reads exactly like the endpoint failure this platform is tested for.
Terraform owns the count, because raising it from 0 to 1 is a verification step and an ignored
attribute would make that step a silent no-op.

Detail: `spec-delivery/SPEC-193`.

### The origins are admitted additively, and narrowed only at the cutover (SPEC-193)

The Cognito app client's callback and logout lists, CloudFront's `connect-src`, and the API's CORS
list each gained the new origin **beside** the existing one. Nothing was removed.

An allowlist naming one origin makes the other a rollback that cannot be exercised — and the
rollback is CloudFront, which is still production. The narrowing belongs to the spec that retires the
distribution, deliberately last. Each addition is verified to have removed nothing, because a
"replace" where an "add" was intended applies green and is invisible until the day it is needed.

Detail: `spec-delivery/SPEC-193`.

### A Fargate task volume cannot give a non-root container a writable path (SPEC-193)

`readonlyRootFilesystem: true` and a non-root `user` need writable mounts, and the mechanism is
**`linuxParameters.tmpfs`**, whose `mountOptions` take `uid`, `gid` and `mode`. It is measured, and it
reverses two earlier statements of the opposite.

**A task-level volume arrives as a fresh, EMPTY, root-owned directory and does not initialise from the
image.** The container printed `uid=101(nginx)` beside `drwxr-xr-x root root /var/cache/nginx` — a
path the base image ships owned by 101. nginx then died on `mkdir() "/tmp/proxy_temp" failed (13:
Permission denied)`, which reads as a container bug and is not one. `volumes` + `mountPoints`,
`readonlyRootFilesystem` and a non-root user are **any two of the three**.

**The uid is ONE value** feeding both the container's `user` and every mount option. Split, the mount
is silently unwritable by the process that needs it — which is this entire failure in one line — and a
test pins them together.

**Do not "fix" a permission error here by seeding the image or by widening the user.** Seeding `/tmp`
with an owned directory was tried and changed nothing, because nothing is copied.

Detail: `spec-delivery/SPEC-193`.

### The nginx configuration reproduces CloudFront's jobs, and three are divergences (SPEC-194)

The SPA moved from a distribution over an S3 origin to a container behind a load balancer. Producing the image is trivial — a Vite build served by nginx — and **that triviality is the trap**: the distribution was doing five other jobs, each configured once and then invisible, and **every one fails silently when it is wrong**. A missing fallback breaks only deep links and only on reload. A wrong cache header runs last week's bundle intermittently, on exactly the users whose cache is warm. A CSP missing one host breaks one flow days later. A health check that falls through to the shell makes the balancer call a broken container healthy and keep it in rotation forever. So each job is either reproduced or named as a divergence out loud, and the whole set is asserted **on responses** by a CI matrix — grepping the config passes on a config nginx never loaded, on a server block that lost to another on the same port, and on a header wiped by the inheritance rule below.

**`add_header` inheritance is what makes this configuration fragile in a way no review catches.** nginx inherits `add_header` from the enclosing level **only when the current level defines none of its own**. Each location sets its own `Cache-Control`, which on its own **wipes every security header from that location's responses** while the rest of the site looks perfect. Every location therefore `include`s one shared snippet, and every directive carries `always` — measured: without `always`, the `/assets/` 404 carried **no** `Cache-Control` and **not one** security header while the 200 beside it carried all of them. Two further shapes were measured rather than reasoned: `return 404;` with **no body string** emits nginx's stock HTML page and ignores `default_type` entirely; and a 404's content-type follows the **request's extension**, because nginx fixes it before `error_page` runs — so the criterion is "not HTML", never "is `text/plain`", which would redden truthfully and be "fixed" by weakening it.

**Responses generated before a location is resolved reach none of that.** A malformed request line, a malformed header field and an over-long URI are answered by nginx before it picks a location — measured, they came back as HTML with no `Cache-Control` and no security header at all, which is precisely the shape the per-location discipline exists to prevent, arriving by the one route it cannot reach. The set is declared at the **server** level as a floor, where the same inheritance rule works in our favour: a location setting its own header still overrides it, so every cache class is unchanged.

**The three divergences, each with its cost and its re-open trigger.**

1. **`Server: nginx` remains.** The distribution stripped the S3 origin's banner. nginx cannot: `server_tokens off` hides the *version* and nothing more, and removing the header needs the third-party `headers-more` module, which the official images do not ship. The alternative is a build stage compiling it against the runtime base's exact source, recompiled in lockstep with every base bump, where an ABI mismatch stops nginx starting — real maintenance coupling for a banner that now discloses only "nginx". The scanner alert that motivated the strip fires on a **version**, so it does not regress. Re-open trigger: a client security review objecting to the banner.
2. **gzip only, no brotli.** `gzip_static` over `.gz` siblings produced at build time gives every asset a maximum-ratio artefact at no per-request CPU. Brotli needs the same third-party compile stage, and accepting it there while refusing it above would be incoherent. **The residual is real and not papered over:** brotli-capable browsers — effectively all of them — receive gzip, so the bundle transfers roughly 15–20% larger than through the distribution. Moves with the trigger above.
3. **HSTS drops `preload`.** It was flipped on to clear a scanner check and is recorded as inert — browsers act on the preload list and entry needs a manual submission. Emitting it claims a submission this deployment has not made and does not intend; the grant is against the **registrable domain** and close to irreversible, and these are subdomains of a parent this repository does not own, so the claim would commit sibling services nobody asked. It costs no finding, though not for the reason it first appears: **`CKV_AWS_259` is a CloudFront check**, evaluated against `aws_cloudfront_response_headers_policy.portal` — which still carries HSTS with `preload` and still passes it. nginx's header is invisible to that check, so dropping `preload` on the container origin regresses nothing. **When the distribution is deleted, `CKV_AWS_259` must come off `.github/checkov-enforced.txt` in the same change**: an enforced check ID matching no finding is a hard error, which is the gate working as designed.

`x-amz-server-side-encryption` needed no decision and gets no criterion: it was the S3 origin's banner, there is no S3 origin, and there is no route by which nginx could emit it. An assertion about it could not fail, and stating it as evidence would misrepresent a consequence as a control.

### The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)

The S3 delivery path needs three prefix-scoped sync passes because one pass cannot both write a single `--cache-control` and reconcile deletions, and its single `--delete` is scoped to `assets/` — leaving an accepted orphan class of stale **root-level** objects removable only by hand. **A container has neither problem.** The image *is* the file set: nothing to reconcile, no key surviving a build, no pass ordering. Both the `--delete` pass and the orphan class cease to exist for that path — a settled decision retired by shipping rather than by argument.

**One improvement, and one residual that changes shape for the worse.** Under `/assets/` the container answers an **honest 404** for a missing hashed chunk, where the distribution returned `index.html` as `text/html` to a `<script type="module">` request — which failed the MIME check anyway, more confusingly, and with no way to tell "removed" from "never existed". At the root the 200-with-`text/html` trap is **preserved deliberately and pinned by a test**, so a later change to the fallback is visible rather than silent; it remains the reason a removal is never verifiable by status code here. The residual: on the S3 origin the bucket held the union of old and new until the delete pass ran, so an open tab lazy-importing a removed chunk had a window. A task serves exactly one image's file set, so during a rolling deployment a browser holding the **old** shell routed to a **new** task 404s immediately and deterministically. The `no-cache` shell means a reload recovers, as before. Accepted, and recorded so it is not rediscovered as a container defect.

### `connect-src` comes from the task definition; every other CSP directive is a property of the bundle (SPEC-194)

**The seam.** `connect-src` **is** the app's network surface and the only environment-shaped directive, so it arrives as one environment variable the task definition supplies. `default-src`, `script-src`, `style-src`, `img-src`, `font-src`, `worker-src`, `object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` all describe the **bundle** — what it may execute, style, fetch a font from, spawn a worker as — and ship baked in the image. Baking the whole policy would carry one environment's hosts everywhere, which is exactly the build-time-configuration failure the runtime-configuration document exists to end; supplying the whole policy from the task definition would put the bundle's own properties in the hands of whoever edits an environment map.

**Both CSP locals live at root, and that placement is load-bearing three ways.** A check at root **cannot read a local declared inside a module**, so the byte-identity and agreement assertions would have had no readable referent. `modules/app` is **deleted outright** when the distribution is retired, which would orphan the computation the container depends on. And one computation feeding both delivery paths is what stops them drifting into enforcing different policies while both are live. The move was proved to be a move: the directive list was compared term by term, in order, against a recorded copy of the **pre-move** string — a comparison re-derived from the new source would only assert that the file equals itself — and the plan against real state reported **no changes**. Two mutations initially escaped that guard and are worth keeping in mind for any similar check: an element regex reading **quoted strings only** was blind to `local.api_origin,` appended to the list, and nothing asserted the **join separator**, without which a policy joined on a space is one malformed directive with every other directive dropped by the browser and all twelve elements still present.

**Anything interpolated into nginx configuration must be validated, because nginx has no escaping mechanism.** Measured: a `connect-src` value carrying a `"` closes the directive it sits in — `object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` all silently gone — while a trailing `;` appends a directive of the attacker's choosing, on a container that **starts, reports healthy and enters the target group**. A value that does not parse is barely better: nginx dies with `[emerg]` naming no variable, which is the generic essential-container exit this image is otherwise written to avoid producing. Both interpolated values are validated against what they may contain rather than scanned for what they may not — an allowlist cannot be outflanked by a character nobody thought of. The same reasoning already governed the configuration document, which is rendered with `jq -n --arg` and never a heredoc.

**The removal-owner table matters as much as the list.** On the day the container shipped, `connect-src` was every host the response-headers policy enumerated **plus the API host**, because nothing had been ported. It shrinks one entry at a time as the porting specs land, and **it does not lose the Cognito hosts in this arc**: Amplify keeps running in the browser, so the User Pool endpoint and the Hosted UI domain are still fetched from. That is the highest-consequence mistake available here, and the reason a test names those two entries separately from any set comparison — a reader holding the arc's end state in mind deletes them on purpose, and would then update a whole-list assertion to match the mistake. The failure is **invisible to an already-signed-in session**: the authorization-code exchange is the only fetch to the Hosted UI host, a warm tab never makes it, so the portal looks perfect to whoever is testing while every new sign-in sits signed-out over a live session.

## Gates, scanners and tests

### Security scanning (SPEC-138)

Five classes of scan across all three surfaces — SAST (Semgrep `p/owasp-top-ten` + language rulesets), dependencies (`npm audit` at **two scopes**, `pip-audit` over glob-discovered requirements), secrets (`gitleaks`, full history, redacted), IaC (`checkov` on `infra/`) and DAST (OWASP ZAP baseline, weekly, unauthenticated). Three decisions carry the weight. **(1) Gating is data, not code:** one `GATE_*` value per scanner in `security.yml`, all `report` at ship, and an unrecognised value is a *hard error* — a typo must never silently mean "not enforcing". The exception is `eslint-plugin-security` + `no-unsanitized`, which run inside `npm run lint` (now `--max-warnings 0`) and therefore **block**: an injection sink in code being written now should stop the PR, not become a line in a report. **(2) Every scanner is version-pinned**, for the reason `pyproject.toml` already records — ruff 0.16.0 widened its defaults and reddened `main` with 500 findings in untouched files (#311); a scanner that gains rules on release does that to every open PR at once. **(3) "Did not run" is never "clean":** unparseable output, a scanner exit ≥ 2, or Checkov `parsing_errors > 0` fails the job *even under `gate=report`*, and Semgrep's partial-parse count is published beside its finding count. That is SPEC-137's failure mode — three gates all satisfied by an import that could never resolve — and a zero from a broken scanner reads as evidence, which is worse than no scanner. **Not available, not declined:** CodeQL, SARIF upload and the Security tab need GitHub Code Security, which a private repo on a personal account does not have — hence the job-summary-plus-artifact substitute and the fact that each run is a fresh snapshot with no cross-run deduplication. **Declined on merit:** OWASP Dependency-Check (NVD-centric, slower and less accurate than the ecosystem-native audits) and a second `bandit` (ruff already selects `S`). **Known blind spot:** Checkov parses `.tf`, so the `.tftpl` IAM policies that implement the whole `${aws:PrincipalTag/username}` isolation model are opaque strings to it — a green Checkov job says nothing about the authorization model, and closing that needs `checkov -f plan.json` against a `tofu plan`. First-run findings and their dispositions: `docs/security-baseline.md`.

### IAM policy scanning = the rendered plan, not the templates (SPEC-139)

SPEC-138's Checkov step reads `.tf` and therefore evaluates **zero** IAM policy-document checks, because every policy in this system is a `templatefile()` call it cannot resolve. `deploy-infra.yml`'s plan job now saves the plan, renders it with `tofu show -json`, and scans that with `--framework terraform_plan`: **431 IAM checks against 55 IAM resources**, where the `.tf` scan evaluates none. It lives in `deploy-infra.yml` rather than `security.yml` because the plan and the AWS credentials already are, and that workflow is now in **its own path filter** — otherwise a change to how we scan the infrastructure could merge having never run. **Renaming the `.tftpl` policies to `.json` was raised and REJECTED on measurement:** Checkov emits nothing — zero findings, exit 0 — for a standalone policy file containing `"Action": "*", "Resource": "*"`, because it evaluates `aws_iam_policy` *resources*, not loose documents. The extension was never the blocker; the unevaluated `templatefile()` in the `.tf` was. Keeping `.tftpl` also keeps the signal that `$${aws:PrincipalTag/username}` escaping applies, which is the most error-prone thing about these files. (51 of the 57 templates happen to parse as JSON; 6 do not.) **Two scanners, deliberately:** the `.tf` scan runs every PR + weekly and reports checks the plan scan does not; the plan scan is the only one that reads IAM. Neither is redundant. **The scan asserts its own coverage:** if the plan holds `aws_iam_policy` resources but no IAM check was evaluated, the job fails — a silent regression to the `.tf`-only state would otherwise look identical to a clean run, and that tripwire caught a real matcher bug (`^aws_iam_` never matches `module.data.aws_iam_policy.x`) before CI did. First-run result: the isolation policies are **clean**; all 6 IAM findings are deploy-role `lambda:*EventSourceMapping` statements on `Resource: "*"`, an action AWS does not allow to be resource-scoped — the available hardening is a `lambda:FunctionArn` condition key. Detail: `docs/security-baseline.md`.

### A scanner gate blocks on a narrowed count, never a total (2026-08-09, completes SPEC-138)

SPEC-138 shipped every scanner as `report` and `docs/security-baseline.md` proposed a threshold for
each. Four now block: `gitleaks` and `pip-audit` at a true zero (2026-08-02), and **Semgrep** and
**Checkov** here, plus `GATE_CHECKOV_PLAN` on the rendered-plan IAM scan. Semgrep needed one thing —
`--exclude-rule` for a Flask template-injection rule in a fleet with no Flask, excluded **by rule ID**
rather than by dropping `p/owasp-top-ten`, with a test asserting there is exactly one exclusion so a
second cannot arrive without a disposition. Checkov needed a shape.

**The shape is an ENFORCE list, not a suppression list.** Checkov reports 373 failures over 22 rules
on `infra/`, nearly all of them documented accepts — no VPC, no CMK, no X-Ray, no WAF. Gating that
total would mean suppressing 22 rules to enforce a handful, producing a file nobody reads and a gate
whose meaning drifts every time the scanner adds a rule. So `.github/checkov-enforced.txt` names the
**52 check IDs measured at zero**, and the gate counts failures on those; the rest publish and do not
block. **The criterion is "passes today", not "matters most"** — two entries are merely operational
(`CKV_AWS_216`, `CKV_AWS_305`) and are in because they pass. Deciding which checks *deserve*
enforcement is an argument to re-litigate on every infra change; holding everything already clean is
not, and it costs no remediation to turn on. Same ratchet-at-the-measured-level shape as the coverage
floors (SPEC-150) and the mypy baseline.

**The plan scan accepts by check ID AND resource, never by ID.** Its two permanent findings —
`CKV_AWS_290`/`CKV_AWS_355` on `module.base.aws_iam_role_policy.github_actions_deploy` — exist because
the deploy role must create resources that have no ARN yet and no applicable condition key. Keyed by
resource, the same two rules firing on any other policy still fail; keyed by ID alone, the exemption
would silently cover the isolation policies, which is the one thing this scan exists to watch.

**Three implementation facts that are not obvious and will bite again:**

- **`--quiet` strips `passed_checks`**, and without them an enforced ID that passed is
  indistinguishable from one that never ran. The flag is gone from the `.tf` scan (the plan scan had
  already learned this) and a test pins its absence.
- **An enforced ID evaluated against nothing is a hard error, not a pass** — and so is a plan-scan
  acceptance that matches no finding. A typo, a rename in a scanner bump, or a resource class
  leaving the repo all yield a line that enforces nothing while reading as enforcement: "did not run
  is never clean", turned on the gate's own configuration. **Neither Checkov gate can redden a
  production deploy:** `deploy-infra.yml`'s `plan` job is `pull_request`-only and `apply` does not
  depend on it, so both gates block PRs and nothing else.
- **A gate's count defaults to a NON-NUMERIC sentinel, and its narrowing step assigns before it
  echoes.** These two together are what make the hard errors above reachable, and the first draft
  had neither — every one of them arrived at the gate as a silent green. `echo "VAR=$(script)"` does
  **not** fail the step when the script fails: `echo` exits 0, `set -e` sees success, and the empty
  value it writes wins over any earlier record. Only an assignment's failed substitution trips
  `set -e`. And `${VAR:-0}` substitutes on **empty** as well as unset, so a numeric default converts
  "no count was written" into "clean" — `apply-gate.sh` rejects a non-numeric count, which is what an
  absent count is. ZAP's pre-existing `no-report` default is the same idea; it was there to be copied
  and wasn't. **A pessimistic pre-write does not substitute for either**, which is what the first
  draft believed.

**One exposure accepted, and it is not the Checkov one.** Semgrep's binary is pinned but its
`--config p/*` rulesets are fetched from the registry at scan time and are **not** — so an upstream
rule addition can redden every PR with no code change, the shape #311 made this repo pin everything
to avoid. Accepted because `pip-audit` already blocks on a live advisory database with exactly the
same property, and because the alternative (vendoring 157 rules) trades a rare interruption for a
permanent staleness. The Flask false positive is the demonstration that these rulesets misfire here;
if a second arrives, the answer is another `--exclude-rule` with a disposition, not a narrowed count.

**Still not blocking, by decision:** `npm audit` — `apply-gate.sh` has no severity threshold and the
runtime scope carries two accepted `dompurify` advisories (monaco pins the version exactly), so a
flip would redden every PR; ZAP — two Lows survive by decision, so gate by `riskcode >= 2` or not at
all. Record: `docs/security-baseline.md` → *Addendum — The Gates Went On*.

### Compiler and coverage defaults are declared, never inherited (SPEC-150)

`tsconfig.app.json` and `tsconfig.node.json` state `"strict": true` even though TypeScript 6 already
defaults it on, and both suites carry **literal** coverage floors. Adding the `strict` key changed
**zero** errors — that is the point, and a build that finds otherwise should stop and re-derive the
premise rather than "fix" the errors.

This reverses the implicit trade-off of leaving a default alone because it happens to be correct.
`pyproject.toml`'s ruff block is the precedent and says it outright — "THE RULE SET IS CHOSEN HERE,
NOT INHERITED" — after ruff 0.16 widened its own default set from 59 rules to 413 overnight and
turned `main` red with 500 findings in files nobody had touched (#311). A default is a decision
*someone else* gets to change; strict is this project's single most important type guarantee, and it
does not ride on one.

The coverage floors are the same principle pointed at a different kind of erosion: both suites
measured coverage and neither gated on it, so deleting tests passed CI identically to keeping them.
They are **ratchets at the measured level, not targets** — portal 91/86/89/93, lambdas 95 — and each
is a hard-coded literal on purpose. Nothing computes, inherits or reads them from a file, so lowering
one is a visible one-line diff in review rather than a number that drifted. Raise them when coverage
rises; never lower one to accommodate a regression.

**Do NOT read this as "enable strict"** — it was already on. The work is *declaring* an inherited
default, which is a much smaller and different thing.

**The typecheck gate itself is separate and already shipped** (#363): `ci.yml` runs `npm run build`
on every PR. Two traps are recorded in that file's header comment and should be read before touching
it — vitest does not typecheck, and `tsc --noEmit -p apps/portal/tsconfig.json` **exits 0 having
checked nothing**, because that config is solution-style (project references only, no
`files`/`include`). `tsc -b` is the only invocation covering the app *and* its `*.test.tsx` files.
SPEC-150 confirmed the gate empirically on a scratch PR: with the #361 defect reintroduced, Lint and
Format check passed, **Build failed**, and Test was skipped.

### `ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)

The repo invented this idiom in SPEC-110 (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`).
SPEC-153 makes it the standard way to record a **load-bearing premise that is corroborated but not
discharged**, and a **documented behaviour someone will later mistake for a bug**.

A tripwire test pins **today's behaviour**, names the reasoning in its docstring, and ends with the
same instruction every time: **if it starts failing, revisit the decision — do not delete the test.**
That is the whole point. A premise held only in prose degrades silently; a premise held in an
assertion tells you the day it stops being true.

Four now exist. Two pin premises:

- **Athena's column-name fold** (`test_apply_refresh.py`). AWS documents that Athena lowercases every
  column name it creates through DDL, which is why SPEC-149 hard-codes the fold — but 149's in-place
  `UpdateTable` bypasses Athena, so the fold is now **ours**. If the premise is wrong, the first
  refresh of a mixed-case table silently re-cases every column while `diff-schema`, which folds case
  to compare, reports them unchanged: a mutation no test and no notification would report. The
  tripwire pins that a live `Order_ID` becomes `order_id` and the carried comment survives. Still
  **corroborated, not discharged** — the `GetTable` read-back that would discharge it is an owed live
  check.
- **The projection round-trip** (`test_load_table_definition.py`). The existing round-trip builds its
  fixture from `ddl.projection_properties` and compares the reconstruction re-rendered through the
  same function: render → parse → render vs render. It proves the parser is a left inverse of the
  renderer **on the renderer's own image**, which is worth having and is not "reads tables this
  pipeline did not write". It was **kept and renamed to say so**, and a second fixture whose
  properties did not come from our renderer was added beside it, with a guard test that fails if the
  fixture ever becomes the renderer's output.

Two pin accepted behaviour:

- **A redelivered notification create writes a second inbox row** (`test_notifications_writer.py`).
  These pipelines are at-least-once and `apply_create` mints a fresh `uuid4` per invocation; FIFO's
  producer-side dedup window does not bound a visibility-timeout redelivery. **Accepted:** the blast
  radius is one duplicated line in a read-only, dismissible list, while the fix with teeth is a
  producer-supplied idempotency key — a contract change across four control planes and the browser
  producer. `dqcommon.index_store` handles the equivalent case by replacing the row, and the
  asymmetry is now stated rather than accidental.
- **The runs-index cap evicts by position, not by timestamp** (`test_index_store_dqcommon.py`). Once
  a replay has moved a row to the end, position order and timestamp order disagree and the next new
  run drops a row that is newer in time. **Accepted:** the code says at the cap that the dashboard
  sorts by timestamp itself, and every evicted run's report object is untouched.

A tripwire is **not** a licence to leave a defect. It is the difference between a project that knows
what it has not verified and one that has forgotten.
