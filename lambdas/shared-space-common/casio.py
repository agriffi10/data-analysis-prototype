"""The shared-space plane's door to the fleet's compare-and-swap loop.

The loop, the precondition predicate and the attempt cap all live in ``cpcommon.cas`` since
 — they were written three times, here and in the data-quality runs index and
the log sweep, and the three had already drifted. What remains here is the re-export, so this
plane's nine call sites keep naming ``casio`` and the module that owns the discipline is the
one that implements it.

``error_code`` is re-exported for the same reason it always was: the registry and cache
classify absent-vs-error by code and reach it through this module.

Attributes:
  MAX_CAS_ATTEMPTS: ``cpcommon.cas.MAX_ATTEMPTS``, under the name this plane already used.
"""

from cpcommon.cas import MAX_ATTEMPTS, CasExhausted, cas_mutate, is_precondition
from cpcommon.errors import error_code

MAX_CAS_ATTEMPTS = MAX_ATTEMPTS

__all__ = [
    "MAX_CAS_ATTEMPTS",
    "CasExhausted",
    "cas_mutate",
    "error_code",
    "is_precondition",
]
