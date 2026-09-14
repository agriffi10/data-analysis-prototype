# Completed Spec — SPEC-201: The Lambda Trust Boundary

## What was completed?

The eight control planes stopped verifying a Cognito ID token out of the queue message. They read
the verified actor out of the `identity` block the API stamps, through one reader —
`cpcommon.actor.trusted_actor` — and **every authorization check they had is unchanged**.

- `cpcommon/actor.py`: `Actor`, `trusted_actor`, `ASSURANCE_INTERACTIVE`, `ACCEPTED_ASSURANCE`.
  It cannot verify: no `jwt`, no `cpcommon.auth`, no network, no environment, asserted by an
  import sweep over the module.
- Thirteen `auth.verified_username*` call sites moved; `shared-space-common/auth.py::verified_username`
  and `notifications_writer.py::verified_username` deleted.
- The whole Cognito arm of `cpcommon/auth.py` deleted. What survives is the provider-agnostic seam
  the API uses.
- `unsupported_assurance` registered in `cpcommon.messages` as a base reason.
- The API stopped writing the token (step two): `Redacted`, `reveal`, `RequestContext.bearer`,
  `principal.bearer`, `EnqueueRoute.token_field`, the 8 KB bearer allowance, and shared-space's
  advisory top-level `actor`.

**Two merges, in order** — [#560](https://github.com/agriffi10/data-analysis-prototype/pull/560)
(step one, deployed `ff3a76b6`) then [#561](https://github.com/agriffi10/data-analysis-prototype/pull/561)
(step two, deployed `73812e06`), with the live pass between them. Step two is the one that cannot
be rolled back.

### Deliberate deviations

- **Four timeout doors, not three.** Arc A's `fo_notify_failure` was added after the spec was
  drafted. All four moved; leaving the fourth would have been an `AttributeError` at first timeout.
- **The whole Cognito arm went, not two entry points.** Once `verified_username` and the two
  wrappers were gone, `verify_id_token`, `_verify`, `_cognito_detail`, `_cognito_config` and the
  claim literal had no callers. Leaving `_cognito_config` reading a deleted `config` attribute
  would have been FR-005 AC3's own trap pointed inward. `verify_exp` went with them — no caller
  wants a relaxation, so there is no flag to turn expiry off.
- **`COGNITO_*` was on twelve Terraform modules, not eight.** `COGNITO_APP_CLIENT_ID` had no reader
  and is deleted. **`COGNITO_USER_POOL_ID` could not follow**: `cpcommon/cognito.py` and
  `shared-space-common/membership.py` read it for `AdminGetUser`, which FR-004 requires to survive.
  It moved out of the fleet-wide `_REQUIRED_VARS` to a lazy `config.require` and stays in Terraform
  on **shared-spaces, file-send and table-share** only. `test_pool_id_reaches_its_readers.py` pins
  both sets; the delivery cost is that a missing value now raises **mid-request** rather than at
  cold start, which is why the live pass aimed at it deliberately.
- **SPEC-200's tripwires were inverted, not deleted.** FR-005 AC7 says "deleted in the same
  commit". One says in its own docstring that this commit removes it and it does; the other now
  asserts the body carries *neither* token field name, which is strictly stronger.
- **`EnqueueRoute.token_field` is a fifth edit under `lambdas/api/`**, where Out of Scope named
  four and called a fifth a review stop. Taken as a reversible technical call — nothing else reads
  the field and the generated TypeScript does not move — and the spec's sentence was amended in the
  same commit.
- **SPEC-206's `SenderId` boundary was NOT re-pointed.** The spec's preamble says it belongs here;
  no FR requires it and there is no live exposure. It retires with the portal role in SPEC-202 —
  and that spec must re-point it, because `UNTRUSTED_SENDER_ID` empty makes `_create_sender_refusal`
  refuse **every** create.

### Two acceptance criteria were wrong and are amended in the spec

- **FR-006 AC4's staged message does not dead-letter.** Every plane's Pipe is `FIRE_AND_FORGET`, so
  `StartExecution` succeeds, the Pipe deletes the message, and the refusal happens *inside* the
  execution. A request DLQ only receives what the Pipe could not **deliver**. The criterion asked
  for a `logs/service=dlq-drain/` body that cannot exist, and a session looking for one would
  reasonably conclude the drain was broken.
- **FR-006's step-one rollback is clean only in the INVERSE order.** The env comes out with the
  code, so redeploying the previous Lambda zips alone restores a verifier reading a variable that
  is gone — a `RuntimeError` on the first request of every plane, worse than what is being rolled
  back. **Infra first, then code.**

## What changed from earlier specs?

- **SPEC-195's Premise 3** is void: `verify_id_token_ignoring_expiry` is for nothing and both
  `*_ignoring_expiry` entry points are deleted.
- **SPEC-126's drain** takes its recipient from `identity.actor`, trusted because SPEC-200 FR-008
  made the API the only writer. `Source.token_field` is gone. Its redaction did **not** go: it now
  blanks the two legacy top-level token fields, because a stale message still carries one.
- **SPEC-161's timeout doors** no longer describe an expired token; there is none.
- **SPEC-164's flat-`actor`** reasoning still holds and now explains why the identity block is
  *nested*.
- **SPEC-197's Premise 6** returns to its un-narrowed form; the marker was removed, not re-worded.
- **`transition_plan.md` §6.1** drops from five `cognito:username` readers to two, neither of them
  a control plane. A sweep now fails if any shipped Lambda module writes a provider's claim name as
  a literal.

## Verification

`ruff`, `mypy`, `pytest` (1895 passed, coverage 88.28%), `validate_docs.py`, `tofu fmt -check`,
`tofu validate` and the contract regeneration all exit 0 on both merges.

**FR-004 AC3's deliberate-violation run: 1, 1, 1, 1, 1, 1, 1, 2 tests redden** — one authorization
branch deleted per plane. It answered **zero on four planes first**, every time because the fixture
was caught by a *neighbouring* branch returning the same reason code. Archive's was the worst: every
negative there named a shared space, so the check deciding whether one user may archive out of
another's prefix — on the plane where a mistake is unrecoverable — was asserted nowhere. All four
are closed.

Mutations planted and reverted, each confirming the guard it names: the actor shape rule (seven
cases redden, and **every plane's suite stays green**, which is what says the shape rule is the
guard and the call sites cannot be); `trusted_actor` hoisted above `notifications_writer`'s branch
(six redden — that is the change that silently refuses every notification the fleet produces);
pointing the drain's redaction at `identity`; blanking the table-share door's recovery; tightening
any one plane's allowed-field set.

**Live, and this is the half no offline gate reaches** ([`sessions.md`](../testing/sessions.md),
2026-08-30). Step one: all eight planes, ten verbs, each a cold start, each reaching its normal
terminal state with its normal notification — and **both** notification branches, since a run that
only checks mark-read reports success over an inbox nothing can write to. Step two: four verbs
covering both envelope shapes.

The single most valuable line was a refusal — *"Couldn't send to user 'nosuchuser_spec201': there
is no user with that name."* That is `admin_get_user` running through the lazy `config.require`, on
one of the three modules that kept the variable. A wrong mapping would have surfaced there and
nowhere earlier.

**Owed** ([`owed.md`](../testing/owed.md)): H.2's non-member and foreign-prefix negatives need a
second account; H.4, H.5 and H.7 need `sqs:SendMessage`, which after SPEC-200 is the API execution
role's alone. **Corrected 2026-09-14:** that role trusts only `lambda.amazonaws.com`, and the
operator CLI identity can send because it holds `AdministratorAccess`; `owed.md` §2.2 has the
detail. Safari is owed — this was Chromium.
