"""User pool lookups shared by every control plane that validates a recipient.

One implementation, on the shared layer, for the reason SPEC-156 gives: a domain layer holds
its plane's tables and wording, never its own copy of an algorithm. "Does this user exist?" is
an algorithm — one API call and a three-way classification of the outcome — and getting the
third branch wrong is what makes it worth having once. ``tscommon.cognito`` re-exports this
name; SPEC-164's file-send verbs call it directly rather than adding a third copy.

``shared-space-common.membership`` is deliberately NOT folded in here: its lookup is embedded
in slot bookkeeping rather than being the same function under another name, and SPEC-156's
record says not to merge the domain layers wholesale.
"""

from . import clients, config
from .errors import TransientError


def user_exists(username: str) -> bool:
    """Reports whether a username is an existing user pool account.

    The three-way classification is the point. An unknown user is a normal ``False`` — the
    callers annotate that recipient and carry on rather than failing the request. Anything
    else is TRANSIENT, so the Step Function retries: reporting a throttle as "no such user"
    would tell a sender their colleague does not exist, which is both wrong and unactionable.

    Args:
      username: The username to look up.

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
