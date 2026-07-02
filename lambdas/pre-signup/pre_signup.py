"""Cognito pre-signup trigger: username validation + disposable-email blocklist.

The username string is reused verbatim and unsanitised as the user's S3 prefix, the
``username`` IAM principal/session-tag value, and the user's Glue database name. Those
must never diverge, so the username has to be simultaneously S3-prefix-safe,
IAM-tag-safe (no ``/``, spaces, ``=``, ``,``), AND a valid Glue/Athena identifier —
hence ``^[a-z][a-z0-9_]{2,62}$`` (3-63 chars, lowercase letter first, then lowercase
letters, digits, or underscores).

The disposable-domain blocklist raises the cost of automated signups: bots commonly
use throwaway inbox services to clear the email-verification step.

Pure validation — no AWS API calls. The execution role grants logs only.
"""

import re

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Common disposable / throwaway email providers. Lowercase; the incoming domain is
# normalised before lookup.
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
    """Reject invalid usernames and disposable email domains; otherwise pass through.

    Raising fails the signup; Cognito surfaces the exception message on the Hosted UI.
    On success the event is returned unchanged — never auto-confirm or auto-verify, so
    the normal email-verification flow proceeds. The username check runs first.
    """
    username = event.get("userName", "")
    if not USERNAME_PATTERN.fullmatch(username):
        raise Exception(
            "Username must be 3-63 characters, start with a letter, and use only "
            "lowercase letters, numbers, and underscores"
        )

    # A missing email attribute skips the domain check defensively (pool config
    # requires email, so this shouldn't happen).
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain and domain in DISPOSABLE_DOMAINS:
        raise Exception(
            "Sign-ups from temporary email addresses are not allowed. "
            "Please use a permanent email address."
        )

    return event
