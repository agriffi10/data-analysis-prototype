# Completed Spec — SPEC-248: A Name Is One User's or One Space's, and Only the Plane Writes a Membership

Two merges on 2026-11-17: #1042 (`114f977`) gave both app clients their attribute lists, and #1044
(`9f26aba`) changed the create verb, the teardown and the card, and added the collision report.
`main` was green on both. Sign-up is not guarded, by decision: the target environment has none.

## What was completed?

- **FR-001, no client can write a slot.** Both clients, `server` and `dev`, declare
  `write_attributes = ["email"]` and `read_attributes = local.client_read_attributes` (`email`,
  `email_verified`, every `custom:shared_space_k`, over the pool schema's own range).
  `test_every_app_client_declares_both_attribute_lists` sweeps every client in the tree and pins the
  local's whole expression; it refuses `.tf.json` and `.tofu` sources, another client resource type
  and `ignore_changes`. The mirror test's absent-lists assertion is gone.
- **FR-002, a space cannot be named after a user.** `create_space._refuse_a_user_name` asks the pool
  after the reservation and before any prefix, database or slot. All three taken-name refusals raise
  `registry.NameTaken` (`name already taken`); the creator's card carries `retryable: false` for that
  type alone, and `ConnectionsPage` drops Retry on the flag for a failed create. Help says so.
  `teardown.revoke_portal_role` acts only when `owns_database` is `True`.
- **FR-003, no slot before the database.** The database step runs before `assign_or_find_slot`.
- **FR-004, the report.** `lambdas/shared-space-name-collisions/` (a one-shot in the shared-space
  plane's function map) and `.github/workflows/report-name-collisions.yml`. The orchestrator gained
  `lakeformation:ListLakeFormationOptIns`; the deploy role gained `lambda:InvokeFunction` on that one
  function name. It is probed on deploy and refuses an event with no `requestId` before any read.
  `teardown.carries_marker` is the marker rule over a record in hand, shared with `owns_database`.
- **Decisions:** `docs/decisions/control-planes/a-space-named-after-a-user-finds-that-users-database-and-a-teardown.md`
  (rewritten in place) and `docs/decisions/identity-and-access/a-membership-slot-is-an-authorization-input-only-because-no-app-client.md`.

### Deliberate deviations

- **The spec was revised before building** for the clients on `main`: SPEC-262 had destroyed the
  public `spa` client, so P5, P6, FR-001's probe and its control name the `server` and `dev` clients,
  both with a secret. Review added a criterion: `list-user-pool-clients` must return only those two.
- **The report's lists are `null`, not empty, when a read they depend on failed**, and a slot counts
  as backed only by a real space whose roster includes the user — a refused reservation's roster is
  its creator, so a roster alone would have hidden a self-written slot. The spec's Data Model says so.
- **The eight-template statement comparison** in `lambdas/test_plane_grants_one_template.py` was
  retired, as its own docstring said the first deliberate plane-grant change would retire it.

## Live results

- **Probe before the apply** (Andrew, dev client, SRP, user `agriffith`, an empty slot set to `""`):
  `UpdateUserAttributes` **succeeded — WRITABLE**. So the report run below was required.
- **CI plan** (Deploy Infrastructure run 44163166680): both clients updated in place; 0 to add, 2 to
  change, 0 to destroy.
- **After the apply:** `list-user-pool-clients` returned exactly `dat-prod-server-client` and
  `dat-prod-dev-client`; `describe-user-pool-client` showed `WriteAttributes` `[email]` and
  `ReadAttributes` `email`, `email_verified` and all ten slots on both (none was set before).
- **Probe after the apply:** `NotAuthorizedException: A client attempted to write unauthorized
  attribute` — **NOT WRITABLE**.
- **Controls after the apply** (built-in browser; Claude in Chrome was unreachable): through the dev
  client under `next dev` and through the server client in the deployed portal, `agriffith`'s
  shared-space listing answered 200 and the session carried the email. A space created after the
  apply, `spec248_slot_check`, went Active, and after a new sign-in its listing answered 200, so the
  plane's admin write still lands. That space is left in place as a test space.
- **Report** (run 44182806449, 2026-11-17T21:43Z): passed; (a) 0, (a′) 0, (b) 0, (c) 0, (d) 0,
  (e) 0, (f) 0, and (g) **no Lake Formation opt-ins**, so P3's catalog-only reading holds as the
  account stands; the `analytics/lakeformation.tf` comment that described credential vending is
  corrected. Nothing needed handling by hand.

## Verification

Prettier, ESLint, Vitest, `npm run build -- --analyze`, check:bundle, check:pages, ruff, mypy,
pytest, the contract, `validate_docs` and its corpus, the queue's hook corpora, the flag and path
validators and `tofu fmt`, green by exit code before each push. Mutations each turned their test red
and were reverted: the seven FR-001 plants and three review escapes; the slot moved back before the
database; the pool check moved before the reservation; a revoke on a missing database; the flag on
every `ProvisioningError`; and, in the report, a failed read as empty, the inheritance comparison
reversed, every record real, a write call, a roster-only backing, the ever-active and marker clauses
dropped, and names in the log record. Each PR had a security-frame and a conformance-frame review.
Not measured, by decision: `SignUp` and Managed Login sign-up against the write list.
