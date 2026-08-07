"""Cognito pre-signup trigger: username validation and a disposable-email blocklist.

The username string is reused verbatim and unsanitised as the user's S3 prefix, the username
IAM principal tag value, and the user's Glue database name. Those must never diverge, so the
username has to be simultaneously S3-prefix-safe, IAM-tag-safe — no slashes, spaces, equals
signs or commas — and a valid Glue/Athena identifier.

The disposable-domain blocklist raises the cost of automated signups: bots commonly use
throwaway inbox services to clear the email-verification step.

Pure validation, with no AWS API calls. The execution role grants logs only. The service name
is ``auth`` for both Cognito triggers: they are not a control plane and not verbs, and one
signup touches both, so one queryable set is the useful grouping.

Attributes:
  USERNAME_PATTERN: 3-63 characters, a lowercase letter first, then lowercase letters, digits
    or underscores.
  DISPOSABLE_DOMAINS: Common throwaway email providers, lowercase. The incoming domain is
    normalised before lookup.
"""

import logging
import re

from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="auth")

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

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


@observability.traced("pre-signup")
def handler(event, context):
    """Rejects invalid usernames and disposable email domains, and passes anything else through.

    The username check runs first. A missing email attribute skips the domain check
    defensively, since the pool configuration requires one.

    Only the domain is ever recorded, never the address: the domain is what the rule turns on
    and is shared by every user of that provider, while the local part is what makes an address
    a personal contact detail, and the log store is retained forever. The raw event is never
    recorded either — it carries the address, so logging it would publish that without any field
    ever being named for it.

    Both refusals raise a bare exception rather than a bespoke class: Cognito surfaces only the
    message, never the type, so a custom class would add a name nothing reads.

    Args:
      event: The Cognito trigger event.
      context: The Lambda context, unused.

    Returns:
      The event unchanged. Never auto-confirms or auto-verifies, so the normal
      email-verification flow proceeds.

    Raises:
      Exception: When the username does not match the pattern, or the email domain is on the
        blocklist. Raising fails the signup, and Cognito surfaces the message on the hosted UI.
    """
    username = event.get("userName", "")
    if not USERNAME_PATTERN.fullmatch(username):
        raise Exception(  # noqa: TRY002
            "Username must be 3-63 characters, start with a letter, and use only "
            "lowercase letters, numbers, and underscores"
        )

    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain and domain in DISPOSABLE_DOMAINS:
        observability.warning(
            "signup rejected", username=username, reason="disposable-domain", domain=domain
        )
        raise Exception(  # noqa: TRY002
            "Sign-ups from temporary email addresses are not allowed. "
            "Please use a permanent email address."
        )

    return event
