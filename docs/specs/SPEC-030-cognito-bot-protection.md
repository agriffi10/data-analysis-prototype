# Spec: Cognito Bot Signup Protection

**ID:** SPEC-030  
**Status:** Completed  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-006 (Cognito User Pool IaC), SPEC-012 (Pre-Signup Lambda)

## Overview

The Cognito User Pool's Hosted UI signup endpoint is publicly reachable. For a demo application, the goal is to make automated bot signups difficult without incurring any additional AWS cost. Two free, IaC-manageable layers achieve this:

1. **User Pool hardening** — two configuration changes to the existing `aws_cognito_user_pool` resource: prevent account enumeration and tighten the password policy. Both are free Cognito features.
2. **Pre-signup Lambda extension** — extend the existing SPEC-012 Lambda (`lambdas/pre-signup/pre_signup.py`) to reject registrations from known disposable email domains. No new infrastructure is needed.

Neither AWS WAF nor Cognito Advanced Security Features are used — both incur per-month charges that are unnecessary at demo scale.

## Scope

### In Scope

- `infra/modules/auth/cognito.tf` — add `prevent_user_existence_errors` and tighten `password_policy`.
- `lambdas/pre-signup/pre_signup.py` — add disposable email domain check alongside the existing username validation.
- `.github/workflows/deploy-lambdas.yml` — no structural change; the existing workflow deploys the updated Lambda code automatically.
- Deploy role permissions — no new permissions required (Lambda `UpdateFunctionCode` is already granted by SPEC-012).

### Out of Scope

- AWS WAF — costs money; out of scope for demo.
- Cognito Advanced Security Features (ASF) — costs money above 50 MAUs; out of scope.
- IP-based rate limiting — not achievable for free in the pre-signup trigger (the `event` object does not reliably carry the client IP in all Hosted UI flows).
- CAPTCHA — requires WAF or a third-party service; deferred.
- Admin-only user creation (`allow_admin_create_user_only`) — would prevent self-service signup entirely; out of scope.

---

## Background: Why these two layers

**Email verification (already in place):** The User Pool's `auto_verified_attributes = ["email"]` means every new account requires email confirmation before it is usable. This already forces bots to control a real inbox for each signup — the most effective free barrier.

**`prevent_user_existence_errors`:** Without this, Cognito's "Incorrect username or password" message differs from "User does not exist", letting an attacker enumerate which usernames/emails are registered. Enabling it makes both responses identical, closing the enumeration vector.

**Disposable email domains:** Bots commonly use services like Mailinator, Guerrilla Mail, and 10minutemail to receive verification emails. A blocklist in the pre-signup Lambda rejects these before Cognito sends the verification email.

---

## Functional Requirements

### FR-001: Prevent user existence errors

#### Description

Cognito must return a generic error for both "user not found" and "wrong password" so that sign-in attempts cannot be used to enumerate registered accounts.

#### Acceptance Criteria

- [ ] `aws_cognito_user_pool` in `infra/modules/auth/cognito.tf` includes:
  ```hcl
  user_pool_add_ons {
    # Advanced security is OFF (free tier). prevent_user_existence_errors
    # is a separate Cognito feature and does not require ASF.
  }
  ```
  **Note:** `prevent_user_existence_errors` is set on the **User Pool Client** (`aws_cognito_user_pool_client`), not the pool itself. Update every `aws_cognito_user_pool_client` resource in the module:
  ```hcl
  prevent_user_existence_errors = "ENABLED"
  ```
- [ ] `tofu plan` shows in-place update on the User Pool Client(s), not a replacement.
- [ ] After apply: attempting to sign in with a non-existent username returns the same error message as a wrong password attempt.

### FR-002: Tighten password policy

#### Description

The password policy should require a minimum of 12 characters with mixed complexity to make credential stuffing and brute force less viable.

#### Acceptance Criteria

- [ ] `password_policy` block on `aws_cognito_user_pool`:
  ```hcl
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }
  ```
- [ ] If this block already exists in `cognito.tf`, update `minimum_length` to `12` and verify all `require_*` flags are `true`. Do not replace the existing block — change only the values that differ.
- [ ] `tofu plan` shows in-place update on the User Pool.

### FR-003: Disposable email domain blocklist in pre-signup Lambda

#### Description

Extend `lambdas/pre-signup/pre_signup.py` to extract the email address from the signup event and reject it if the domain is in a hardcoded blocklist of common disposable email services.

The pre-signup trigger event contains `event["request"]["userAttributes"]["email"]` when email is collected at signup. The check runs after the existing username validation so valid usernames from disposable providers are still caught by the first check.

#### Acceptance Criteria

- [ ] `pre_signup.py` extracts the email: `email = event.get("request", {}).get("userAttributes", {}).get("email", "")`.
- [ ] The domain is extracted: `domain = email.split("@")[-1].lower() if "@" in email else ""`.
- [ ] A `DISPOSABLE_DOMAINS` frozenset at module level contains at minimum:
  ```python
  DISPOSABLE_DOMAINS = frozenset({
      "mailinator.com", "guerrillamail.com", "guerrillamail.net",
      "guerrillamail.org", "guerrillamail.biz", "guerrillamail.de",
      "guerrillamail.info", "sharklasers.com", "guerrillamailblock.com",
      "grr.la", "spam4.me", "yopmail.com", "yopmail.fr",
      "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc", "nomail.xl.cx",
      "mega.zik.dj", "speed.1s.fr", "courriel.fr.nf", "moncourrier.fr.nf",
      "10minutemail.com", "10minutemail.net", "10minutemail.org",
      "trashmail.com", "trashmail.me", "trashmail.net", "trashmail.at",
      "trashmail.io", "dispostable.com", "tempmail.com", "temp-mail.org",
      "throwam.com", "mailnull.com", "spamgourmet.com", "maildrop.cc",
      "discard.email", "filzmail.com", "nwytg.com", "spamhereplease.com",
  })
  ```
- [ ] If the domain matches, the Lambda raises with a user-readable message: `"Sign-ups from temporary email addresses are not allowed. Please use a permanent email address."`.
- [ ] If `email` is empty (e.g. sign-up without email attribute — should not occur given pool config but is handled defensively), the check is skipped without error.
- [ ] The username validation from SPEC-012 runs first; the email domain check runs second. Both checks must pass for signup to proceed.
- [ ] A unit test `lambdas/pre-signup/test_pre_signup.py` is updated to cover: valid email passes, disposable domain rejected, empty email passes (defensive), uppercase domain normalised correctly.

---

## Data Model

_No new TypeScript types. No new IaC variables._

---

## File & Folder Structure

```
lambdas/
└── pre-signup/
    ├── pre_signup.py          ← extend with email domain check + updated tests
    └── test_pre_signup.py     ← update existing tests

infra/modules/auth/
└── cognito.tf                 ← add prevent_user_existence_errors on client(s),
                                  update password_policy
```

---

## Implementation Phases

### Phase 1: User Pool Client and password policy (IaC)

Update `cognito.tf`. Run `tofu validate` then `tofu plan`. Confirm the plan shows only in-place updates to the User Pool and User Pool Client — no replacements (replacements would invalidate existing user sessions).

#### Checkpoint

`tofu plan` shows `~ update in-place` for the User Pool and User Pool Client, with `Plan: 0 to add, 2 to change, 0 to destroy`. Apply and verify in the AWS Console: Cognito → User Pool → App clients → "Prevent user existence errors" is "Enabled". Sign-in tab shows minimum password length of 12.

### Phase 2: Disposable email domain check (Lambda)

Update `pre_signup.py` and `test_pre_signup.py`. Push to `main` — `deploy-lambdas.yml` builds and deploys the updated function automatically.

#### Checkpoint

`python -m pytest lambdas/pre-signup/test_pre_signup.py` passes locally. After deploy: attempt to sign up via the Hosted UI using a `@mailinator.com` address — the signup is rejected with the readable error message. Sign up with a real email — proceeds to email verification normally.

---

## Open Questions

_None — both changes are free and safe to apply to a demo environment._
