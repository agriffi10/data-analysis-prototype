# Completed Spec — SPEC-217: Operator-Driven Shared-Space Membership

## What was completed?

An operator's CSV in the admin bucket can now **add members to a shared space and remove them**, as
well as transfer it. The rows become ordinary requests on the plane's existing queue, so an
operator-driven add is the same verb, the same authorization and the same notifications as an
owner-driven one.

- **`auth.member_refusal`** — one pure predicate deciding `add_members` and `remove_members` for
  **both** origins, returning a `(code, message)` pair. Both actions left `OWNER_ONLY_ACTIONS`;
  `authorize` gained one branch covering both **and a terminal `raise`**, because with two
  actions deliberately allowed there and gated elsewhere the fall-through stopped being unreachable
  and became the failure mode.
- **A member refusal now reaches the requester.** It used to raise in the validator, whose `Catch`
  nulls the actor, so the notifier stayed silent — a member change that refused was a request the
  user watched disappear. It travels as a value through the plane's existing `RefusedSeed` arm,
  which needed no ASL change: that branch was already action-independent, and a test now pins that
  it stays so.
- **The four request-level refusals collapse to one sentence for a requester** while keeping
  distinct codes on the execution record. Four true sentences delivered to whoever asked, for any
  space name they care to try, is an existence oracle over every shared space.
- **`OPERATOR_ACTIONS` widened to three actions**, the three origin refusal sentences became
  action-neutral, and both member verbs gained the refusal fence and `origin` stamp
  `transfer_ownership` already carried. `remove_members` gained an actor on its event.
- **The operator CSV** — `<admin-bucket>/operator-requests/inbox/`, header `space,action,username`,
  `action` one of `add` / `remove` / `transfer`. Rows sharing a `(space, action)` coalesce into
  **one** message; one space takes one action per file; `space` and `username` are held to
  `CATALOG_IDENTIFIER_RE`.
- **Two computed caps and three chosen numbers**, each pinned where it was argued, plus a
  **file-size ceiling checked from the listing** before the object is fetched at all.

### Deliberate deviations

- **The dedup id is ETag-salted, not random.** FR-002 said random; random reintroduced a different
  fault. EventBridge invokes the sweep asynchronously with no `maximum_retry_attempts`, so Lambda's
  own retries fire **inside** the five-minute deduplication window — unlike the hourly schedule the
  criterion reasons about — and a duplicate `transfer_ownership` refuses as `TransferTargetIsOwner`,
  telling the new owner it failed a minute after telling them it worked. The criterion is **amended
  in place** in the spec with that reasoning; its own argument for not using the request id is
  unchanged and is why the salt exists.
- **`transfer_ownership`'s existence oracle is not fixed.** `transfer_refusal` still discriminates
  the same four facts to a non-owner. The spec declined to inherit it into two more actions and
  declined to fix it in passing; it is a named follow-up in the register, and `_refusal` already
  takes the `wording=` argument the narrowing needs.
- **An `add_members` naming only the space's owner stays a silent no-op.** The owner is already a
  member, and FR-004 keeps an add of an existing member idempotent because replay safety is worth
  more than the diagnostic. Pinned by test so the decision is visible.
- **The reader, its role and `TRANSFER_READER_ROLE_ID` are not renamed.** The role's unique id is
  half the `SenderId` comparison, so renaming rotates the value the boundary compares against and
  any file consumed in that window is refused wholesale.

## What changed from earlier specs?

- **SPEC-205's emptied-record mechanism is superseded for two actions.** They no longer rest on the
  cleared `owner` field; `member_refusal` refuses on `emptiedAt` **before any actor is consulted**.
  The inertness test keeps its discrimination by pairing the emptied assertion with a live-record
  one. The register entry and the CLAUDE.md digest clause were amended in place.
- **SPEC-208's "every other refusal raises" is no longer true**, and its operator CSV shape is
  retired. Its spec, delivery doc, register entry, the plane page, `ARCS.md` and `architecture.md`
  carry superseded markers, as does SPEC-205 at both sites that state the mechanism this changed.
- **The `ownership-transfers/` prefix is retired** — reader, IAM and both lifecycle rules — gated on
  a listing confirming all three sub-prefixes empty, re-run immediately before each of the two
  merges that depended on it. Confirmed applied: the live bucket carries the two
  `operator-requests/` rules and no rule naming the old prefix.

## Two bugs the reviews caught that would have shipped

- **A malformed CSV wedged the operator door permanently.** `csv` raises on a field over its size
  limit (one unmatched quote in a file over 128 KB) and on lone-CR endings; that escaped `_process`,
  so the file never reached `rejected/`, sat in a prefix with no expiry, and — files being swept
  lexicographically — blocked every later-named file on every subsequent tick. **The same wedge was
  reachable by SIZE**, since the parse materialises the file before the row cap can count it, and
  the peak is a large multiple of the file's own bytes against a 128 MB function. A file is now
  refused on its size from the listing, before it is fetched; the ceiling's own derivation is
  beside the constant, where anyone can re-run it.
- **The ETag salt was asserted by nothing.** The test supplied the salt on both sides, so producer
  and consumer agreed with each other and with nothing else — deleting the production wire left the
  whole suite green.

## Verification

Local, by exit code: `pytest lambdas/`, `ruff` over all three trees, `mypy`, `validate_docs.py` and
its corpus, `tofu fmt -recursive`, `tofu validate`, and the portal's `lint` / `format:check` /
`build` / `test:coverage`. CI stopped running lint, the suites, prettier and mypy partway through
this spec (#632), so the later PRs were gated entirely on the local run.

Three code PRs plus this one, each reviewed in a fresh context before its push — two frames on PRs 1
and 2, a third round on PR 2's revision because it changed a mechanism rather than a line, and one
each on PR 3 and this. Mutations were planted on every new guard in each round and every survivor
was closed and re-planted to confirm. The three that mattered: the owner check itself, the ETag
wire, and a set of fixtures whose filenames supplied their own assertion fragment.

The operator path **cannot** be exercised from a signed-in session — the inbox is in the admin
bucket, which the portal role cannot write — so it stays in [`owed.md`](../testing/owed.md),
rewritten there for the new prefix, header and vocabulary.
