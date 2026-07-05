"""Cognito User Pool lookups for recipient validation.

A ``kind:'user'`` share recipient must be an existing account (SPEC-089 FR-003) —
the same AdminGetUser check the shared-spaces add-members verb uses. Unknown user is
a normal False (annotated per-recipient, not fatal); anything else is transient so
the Step Function retries rather than mis-reporting a throttle as "no such user".
"""

from . import clients, config
from .errors import TransientError


def user_exists(username: str) -> bool:
    """True iff ``username`` is an existing User Pool account."""
    client = clients.cognito()
    try:
        client.admin_get_user(UserPoolId=config.USER_POOL_ID, Username=username)
        return True
    except client.exceptions.UserNotFoundException:
        return False
    except Exception as exc:  # noqa: BLE001 - throttle/5xx → retry, never a false "unknown user"
        raise TransientError(f"AdminGetUser failed for {username!r}: {exc}") from exc
