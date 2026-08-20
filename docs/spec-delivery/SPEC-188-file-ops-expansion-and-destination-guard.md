# Completed Spec — SPEC-188: File Operations — Source Expansion, the Copy Plan & the Destination Guard

## What was completed?

The file-operations plane can now say **what** an operation will touch and **whether** each selected
item may proceed. Nothing is copied or deleted; the machine still ends in placeholders SPEC-189
replaces. Nothing user-visible changed — no gesture in the browser reaches this plane until SPEC-190.

- **`file-ops-inspect-source`** — expands every selected item, pages a folder past its 1,000-key
  boundary, re-checks containment on every key S3 returns, derives each object's destination, and
  writes the plan to `{admin_bucket}/file-ops/{requestId}/plan.json`. Only the key and the counts
  ride on the state.
- **`file-ops-check-destinations`** — heads every derived destination key at concurrency 8 and
  records a **per-item** conflict with a bounded sample. Merging into an existing folder is
  deliberately not a conflict; a 403 is; `overwrite` cannot short-circuit.
- **`focommon.plan`** — `plan_key` / `write` / `load` / `assert_describes` /
  `assert_request_id_unused`, plus the caps and the outcome vocabulary in `config` and `outcomes`,
  and the **one** destination builder `paths.destination_key` (an AST sweep forbids a second).
- **`cpcommon.s3_listing.list_data_records`** — the ETag-carrying listing; `list_data_objects` is now
  a projection of it, so the fleet still has one paginator and five callers are unchanged.
- Infra: the two functions in `locals.tf` and the deploy table, the ASL's two new Tasks with their
  catches, the admin-prefix grant, the admin bucket's fifth lifecycle rule, and **the role's first
  read grant on the data buckets** with an explicit Deny on every write verb.

### Deliberate deviations

- **The execution role reads both data buckets.** FR-008 grants only the admin prefix, but the
  expansion lists the source and the guard heads the destination, so without it every run fails
  `AccessDenied`. Read-only, and `NoDataObjectWrite` denies `s3:Put*`/`s3:Delete*`/`s3:Restore*`/
  `AbortMultipartUpload` on both buckets so the absence of a write is a rule rather than a state.
  `test_the_execution_role_names_NO_data_bucket` was replaced by a narrower pair.
- **`request_id_reused` compares the EXECUTION, not the presence of an object.** FR-007 AC4's literal
  reading — refuse a prefix that already holds a plan — would have the machine's own three-attempt
  `Retry` refuse the request it had just planned. The plan carries `executionArn` for it.
- **The module names are plane-qualified** (`file_ops_inspect_source.py`), against the spec's
  structure block: four other planes ship an `inspect_source.py` and they would collide on
  `sys.modules` under one pytest run. `locals.tf` already states the fleet rule.
- **The conflict sample is 3 paths shortened from the middle to 120 characters**, not FR-006 AC6's
  literal "pick the sample size to fit" — measured, the state budget admits **one** full-length path
  per conflicted item. Escalated and decided by the user.
- **`CopyPlaceholder`/`MovePlaceholder` became one `TransferPlaceholder`**, and the placeholder test
  became a rule over every `*Placeholder` state rather than a list of names.
- **No component-inventory row.** That router covers `apps/portal/src`; this spec added no browser
  code, as SPEC-187 did not.

## What changed from earlier specs?

- **`cpcommon.s3_listing`** gained `list_data_records`; `list_data_objects` now delegates to it.
  Behaviour for table-builder, table-share, data-quality, file-send and archive is unchanged.
- **`focommon.paths.derived_destination_key`** (SPEC-187) now calls the new `destination_key` rather
  than composing its own — one builder, not two that agree.
- **`focommon.messages`** gained ten reason codes; **`focommon.outcomes`** gained four members,
  `carry_forward` and `decided_keys`.
- **The layer-discipline rule on `put_object`** was replaced by a stricter one: no module may make a
  write CONDITIONAL, and exactly one module writes at all.
- **The ASL** routes all three operations through the expansion, and `ChooseOperation` is now a
  validity gate. `NeedsDestinationGuard` branches on `$.operation`, **not** on `$.destination`
  `IsPresent` — a delete carries an explicit `null`, and `IsPresent` is true for a present-but-null
  field.

## Verification

`pytest lambdas/` (4,217 passed), `ruff`, `mypy`, `tofu validate`, `tofu fmt -check` and
`scripts/validate_docs.py` all green locally. Two fresh-context reviews of the plan and two of the
diff; every finding fixed or recorded.

**Help & guides sweep: checked and skipped.** Nothing a user can see changed — the file browser
still runs its existing synchronous paths and no gesture reaches this plane — so there is no shipped,
wired-end-to-end behaviour to document. SPEC-190 and SPEC-191 own the visible change.

**Owed:** two live checks against the deployed plane — a folder past the 1,000-key pagination
boundary planning every one of its objects, and a per-item conflict against a real destination
(including the 403 case). Both need a hand-crafted envelope, since nothing in the browser reaches
this plane yet. `docs/testing/owed.md` §1.
