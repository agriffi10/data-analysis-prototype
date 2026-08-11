"""Cognito user pool lookups for recipient validation.

A user-kind share recipient must be an existing account — the same check the shared-spaces
add-members verb uses.

**The implementation moved to ``cpcommon.cognito`` (SPEC-164).** File-send needs the identical
lookup, and a third copy of it is exactly the fork SPEC-156 exists to prevent, so the
algorithm went to the shared layer and this module keeps the name its callers and their tests
already patch. Behaviour is unchanged.
"""

from cpcommon.cognito import user_exists

__all__ = ["user_exists"]
