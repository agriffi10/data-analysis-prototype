# Completed Spec - SPEC-030 Cognito Bot Signup Protection

## What was completed from this spec?

Two free, IaC-managed hardening layers (no WAF, no Advanced Security Features):

1. **User Pool Client — `prevent_user_existence_errors = "ENABLED"`**
   (`infra/modules/auth/cognito.tf`, `aws_cognito_user_pool_client.spa`). Sign-in now returns
   an identical generic error for "user not found" and "wrong password", closing the account
   enumeration vector (FR-001).
2. **Password policy — `temporary_password_validity_days = 7`** added to the existing
   `password_policy` block (FR-002). `minimum_length = 12` and all `require_*` flags were
   already in place from SPEC-006, so only the validity-days value was added.
3. **Pre-signup Lambda — disposable email blocklist** (`lambdas/pre-signup/pre_signup.py`,
   FR-003). After the existing username-pattern check, the handler extracts
   `request.userAttributes.email`, normalises the domain to lowercase, and rejects it with a
   user-readable message if it is in the module-level `DISPOSABLE_DOMAINS` frozenset (Mailinator,
   Guerrilla Mail, 10minutemail, etc.). An empty/absent email skips the check defensively.
4. **`lambdas/pre-signup/test_pre_signup.py`** — new tests covering valid email passes,
   disposable rejected, empty email passes, uppercase-domain normalisation, and that the
   username check runs first. 6 tests, all passing locally.

## What has changed?

- **No empty `user_pool_add_ons {}` block was added.** FR-001's acceptance snippet showed an
  empty `user_pool_add_ons {}` block on the pool with a clarifying note that the real setting
  (`prevent_user_existence_errors`) lives on the **client**. An empty `user_pool_add_ons` block
  is misleading (it relates to Advanced Security Features, which the spec deliberately avoids)
  and unnecessary, so only the client attribute was set — which achieves FR-001's actual intent.
- **Test runner.** ~~`test_pre_signup.py` runs under `pytest` *or* as a plain script
  (`python3 test_pre_signup.py`)~~ — **no longer true; pytest is the only runner.** The plain-script
  mode was removed fleet-wide once it was measured: of the 92 files carrying a runner, 35 died at
  `ModuleNotFoundError` and one reported a pass over half its tests. Note `deploy-lambdas.yml` zips
  `lambdas/pre-signup/*.py`, so the test file is bundled into the function package; it is inert
  (never the handler) and only a few KB.

## Deploy / verification notes

- `infra/` changed → the PR's **Deploy Infrastructure** job ran `tofu plan` against live AWS;
  the plan was confirmed to be **in-place updates only** (User Pool Client + User Pool), no
  replacements, before merge. On merge to `main`, `tofu apply -auto-approve` applied them and
  `deploy-lambdas.yml` rebuilt + redeployed the pre-signup function.
- `tofu fmt -check -recursive` passes (matches the workflow's format gate).
- Post-deploy manual checks (per spec): non-existent-user sign-in returns the same error as a
  wrong password; signup with a `@mailinator.com` address is rejected; a real email proceeds to
  verification.
