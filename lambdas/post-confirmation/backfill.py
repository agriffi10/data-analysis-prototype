"""Backfill the per-user Glue database for an already-confirmed user (SPEC-033 FR-004).

The post-confirmation Lambda (post_confirmation.py) provisions a user's Glue database
+ Lake Formation grant the moment they confirm sign-up. Users confirmed BEFORE that
Lambda existed (none in production yet) never got one. This script runs the exact same
provisioning logic for a given username — it imports ``provision_user`` from the Lambda
handler rather than duplicating it, so the two can never drift.

It is idempotent (create-if-absent + LF grant), so re-running it on an
already-provisioned user is a no-op-equivalent and safe.

Run with admin/operator credentials (NOT the Lambda role) that can call
``glue:CreateDatabase`` and ``lakeformation:GrantPermissions``, and that is a Lake
Formation admin. The portal role ARN is read from the same ``PORTAL_ROLE_ARN`` env var
the Lambda uses, so set it before running:

    export PORTAL_ROLE_ARN="arn:aws:iam::<account-id>:role/dat-portal-user-role"
    python3 backfill.py <username> [<username> ...]

To enumerate existing confirmed users to backfill:

    aws cognito-idp list-users --user-pool-id <pool-id> \
      --query "Users[?UserStatus=='CONFIRMED'].Username" --output text
"""

import sys

from post_confirmation import provision_user


def main(argv):
    """Provisions each named user, reporting per-user outcomes and continuing past failures.

    Args:
      argv: The process argument vector; the program name followed by one or more usernames.

    Returns:
      0 when every user was provisioned, 1 when any failed, 2 when no username was given.

    Raises:
      None. A per-user failure is printed and the run continues to the next user.
    """
    usernames = argv[1:]
    if not usernames:
        print(f"usage: {argv[0]} <username> [<username> ...]", file=sys.stderr)
        return 2

    failures = []
    for username in usernames:
        try:
            provision_user(username)
            print(f"ok - provisioned {username}")
        except Exception as exc:  # noqa: BLE001 - report and continue to the next user
            print(f"FAILED - {username}: {exc}", file=sys.stderr)
            failures.append(username)

    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"\n{len(usernames)} provisioned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
