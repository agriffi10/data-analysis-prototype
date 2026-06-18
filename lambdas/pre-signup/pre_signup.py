"""Cognito pre-signup trigger (SPEC-012, extended by SPEC-030, tightened by SPEC-033).

Two checks run before the user is created, in order:

1. Username pattern (SPEC-012, tightened by SPEC-033 FR-001). This single string is
   reused, verbatim and unsanitised, as ALL of:
     - the user's S3 prefix          s3://<user-space>/<username>/...   (SPEC-013)
     - the ``username`` IAM principal/session tag value                (SPEC-011)
     - the user's Glue database name  database/<username>               (SPEC-033)
   They must never diverge, so the username has to be simultaneously S3-prefix-safe,
   IAM-tag-safe (no ``/``/spaces/``=``/``,``), AND a valid Glue/Athena identifier.
   Authoritative rule (FR-001):
       ^[a-z][a-z0-9_]{2,62}$
   i.e. 3-63 chars, starts with a lowercase letter, then lowercase letters, digits,
   or underscores. SPEC-033 tightened this from the original ``^[a-zA-Z0-9._@-]{3,64}$``
   (which allowed email-style ``@ . -`` usernames) so the Glue database name is legal;
   safe to change because no production users exist yet.

2. Disposable email domain blocklist (SPEC-030 FR-003). Bots commonly use
   throwaway inbox services to clear the email-verification step; rejecting the
   most common domains raises the cost of automated signups for free.

Pure validation -- no AWS API calls. The execution role grants logs only.
"""

import re

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Common disposable / throwaway email providers (SPEC-030 FR-003). Lowercase;
# the incoming domain is normalised before lookup.
DISPOSABLE_DOMAINS = frozenset(
    {
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
    }
)


def handler(event, context):
    # 1. Username rule (SPEC-012) — runs first.
    username = event.get("userName", "")
    if not USERNAME_PATTERN.fullmatch(username):
        # Raising fails the signup; Cognito surfaces this message on the Hosted UI.
        raise Exception(
            "Username must be 3-63 characters, start with a letter, and use only "
            "lowercase letters, numbers, and underscores"
        )

    # 2. Disposable email domain blocklist (SPEC-030). Skipped defensively when no
    #    email attribute is present (pool config requires it, so this shouldn't happen).
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain and domain in DISPOSABLE_DOMAINS:
        raise Exception(
            "Sign-ups from temporary email addresses are not allowed. "
            "Please use a permanent email address."
        )

    # Valid: return the event unchanged. Do NOT auto-confirm or auto-verify --
    # the normal email verification flow proceeds (SPEC-009).
    return event
