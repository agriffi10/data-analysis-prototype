"""Cognito pre-signup trigger (SPEC-012, extended by SPEC-030).

Two checks run before the user is created, in order:

1. Username pattern (SPEC-012). The username becomes the user's S3 prefix and the
   value of the ``username`` IAM principal tag (SPEC-011/013), so it must be safe
   for both: no ``/`` (prefix delimiter), no spaces, no ``=`` or ``,`` (IAM tag
   syntax). Authoritative rule (FR-001), kept in sync with the landing-page text:
       ^[a-zA-Z0-9._@-]{3,64}$

2. Disposable email domain blocklist (SPEC-030 FR-003). Bots commonly use
   throwaway inbox services to clear the email-verification step; rejecting the
   most common domains raises the cost of automated signups for free.

Pure validation -- no AWS API calls. The execution role grants logs only.
"""

import re

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._@-]{3,64}$")

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
            "Username must be 3-64 characters using only letters, numbers, . _ @ -"
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
