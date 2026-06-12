"""Cognito pre-signup trigger (SPEC-012).

Rejects any registration whose username falls outside the allowed pattern,
before the user is created. The username becomes the user's S3 prefix and the
value of the ``username`` IAM principal tag (SPEC-011/013), so it must be safe
for both: no ``/`` (prefix delimiter), no spaces, no ``=`` or ``,`` (IAM tag
syntax).

Authoritative rule (FR-001), kept in sync with the SPEC-009 landing-page text:
    ^[a-zA-Z0-9._@-]{3,64}$

Pure validation -- no AWS API calls. The execution role grants logs only.
"""

import re

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._@-]{3,64}$")


def handler(event, context):
    username = event.get("userName", "")
    if not USERNAME_PATTERN.fullmatch(username):
        # Raising fails the signup; Cognito surfaces this message on the Hosted UI.
        raise Exception(
            "Username must be 3-64 characters using only letters, numbers, . _ @ -"
        )
    # Valid: return the event unchanged. Do NOT auto-confirm or auto-verify --
    # the normal email verification flow proceeds (SPEC-009).
    return event
