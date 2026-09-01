# Completed Spec — SPEC-208: Shared-Space Ownership Transfer

## What was completed?

A shared space can now change hands. The owner picks an existing member from the Manage drawer and
hands them the space; the former owner stays on as an ordinary member, and everything else — the
prefix, the Glue database, the roster, the data — is untouched.

- **The verb.** `shared-space-transfer-ownership`, reached by a new `Choice` branch.
  `registry.set_owner` rewrites the owner under compare-and-swap, re-checking the **expected**
  owner inside the transform, and corrects `acknowledged` in the same write.
- **The authorization.** `auth.transfer_refusal` and `auth.operator_refusal` in
  `shared-space-common`, both pure, both returning `(code, message)` rather than raising.
- **The browser.** `TransferOwnershipDialog`, `useTransferOwnership`, a per-member **Make owner**
  control on `MembersList` (owner's drawer only), wired through `ConnectionsPage`.
- **The operator path.** `shared-space-transfer-reader`, a scheduled Lambda with its **own IAM
  role**, reading `<admin-bucket>/ownership-transfers/inbox/` and enqueuing one request per CSV row
  onto the plane's existing queue.
- **Help.** One guide under Shared connections. Nothing documents the operator path.

### Deliberate deviations

- **FR-008 was authored against an `idToken` on the wire, which SPEC-201 retired.** Built against
  the nested `identity` block instead: an operator message carries no identity block, and "both
  credentials" means an origin plus a block. The spec is amended in place.
- **`origin` is NOT declared on the API's request type.** The contract refuses an undeclared body
  key, and that is the only thing stopping a signed-in caller claiming operator origin — declaring
  it to satisfy the envelope sweep would have deleted the property. The sweep is answered by a
  named exemption instead, on the notifications writer's precedent.
- **The acting identity rides as `origin`, not as `actor`.** `"operator"` passes
  `CATALOG_IDENTIFIER_RE`, and `notifications-writer` builds an S3 key from `actor` with no
  validation — so it would have addressed a prefix a real user could own. `actor` carries the
  space's current owner: the named victim of a forgery, and the right recipient of a fault.
- **The reader attaches only `cpcommon`, not the domain layer.** `shared-space-common`'s config
  requires `PORTAL_ROLE_ARN` at import and the reader has no use for it; attaching it would buy one
  constant at the price of a cold-start crash. Its `SCHEMA_VERSION` and message group are local,
  each cross-checked against the real source by a test.

## What changed from earlier specs?

- **`cpcommon.events.sender_id`** — SPEC-206's reader moved out of `notifications-writer` into the
  shared layer, now that two boundaries read it; the writer delegates and its behaviour is
  unchanged. `notifications-writer`'s singleton import allowlist gained `events`, which reaches
  only `clients` and `errors` — both already granted.
- **`CLAUDE.md`'s digest clause** on plane trust said "only the API may write these queues". That is
  now false for shared-space; replaced in place at net −1 byte.
- **`infra/modules/base/README.md`** read an `events:` grant as evidence of a `TimeoutSeconds`.
  Shared-spaces has one for a **schedule** and no ceiling anywhere; three other planes were already
  schedules, so the rule had drifted before this spec.
- **`messages._ACTION_PHRASES`** gained an enumeration test against `config.VALID_ACTIONS`. Its own
  docstring claimed an action added without a phrase was "visibly missing"; nothing enforced it.

## Verification

Locally green: `format:check`, `lint`, `build` (`tsc -b`), vitest, pytest, `ruff`, `mypy`,
`validate_docs.py`, `tofu validate`, and the contract regeneration diff. The expected-owner CAS
guard was mutation-tested — removing it reddens exactly one test and nothing else.

Deferred to a signed-in session: the end-to-end transfer, folded into
[`../testing/e2e.md`](../testing/e2e.md). The operator CSV path is **owed** — it needs an
admin-bucket write no browser session can make — and is recorded in
[`../testing/owed.md`](../testing/owed.md).
