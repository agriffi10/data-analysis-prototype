"""Cognito user pool lookups for recipient validation.

A user-kind share recipient must be an existing account — the same check the shared-spaces
add-members verb uses.
"""

from cpcommon import clients, config
from cpcommon.errors import TransientError


def user_exists(username: str) -> bool:
    """Reports whether a username is an existing user pool account.

    An unknown user is a normal False, annotated per recipient rather than fatal. Anything
    else is transient so the Step Function retries rather than mis-reporting a throttle as
    "no such user".

    Args:
      username: The recipient to look up.

    Returns:
      True when the account exists.

    Raises:
      TransientError: On any fault other than the user genuinely not existing.
    """
    client = clients.cognito()
    try:
        client.admin_get_user(UserPoolId=config.USER_POOL_ID, Username=username)
        return True
    except client.exceptions.UserNotFoundException:
        return False
    except Exception as exc:
        raise TransientError(f"AdminGetUser failed for {username!r}: {exc}") from exc
