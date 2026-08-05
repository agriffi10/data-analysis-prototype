"""Lazy, cached AWS + JWKS client factories (SPEC-107 — the union of the twins).

Clients are created once per warm container and reused. Heavy deps (boto3, PyJWT) are
imported lazily so a verb that doesn't need a client never pays for it. Tests patch the
cached globals directly (e.g. ``clients._s3 = Fake()``). This is the UNION of what the
table-builder and table-share layers used: s3, sqs, glue, athena, cognito, and the
memoized User Pool JWKS client (per-container cache, matching the old tbcommon/clients).

SPEC-125 completes the union with ``lf()``, the one factory ``shared-space-common`` had
that this module lacked — so the shared-space verbs can drop their own copy of this file.
"""

_s3 = None
_sqs = None
_glue = None
_athena = None
_cognito = None
_lf = None
#: Keyed BY URL (SPEC-151 FR-009): one client per JWKS endpoint, not one overall.
_jwks = {}


def s3():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def sqs():
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs")
    return _sqs


def glue():
    global _glue
    if _glue is None:
        import boto3

        _glue = boto3.client("glue")
    return _glue


def athena():
    global _athena
    if _athena is None:
        import boto3

        _athena = boto3.client("athena")
    return _athena


def cognito():
    global _cognito
    if _cognito is None:
        import boto3

        _cognito = boto3.client("cognito-idp")
    return _cognito


def lf():
    """Lake Formation client. Used by the shared-space verbs (LF-Tag + permission grants)."""
    global _lf
    if _lf is None:
        import boto3

        _lf = boto3.client("lakeformation")
    return _lf


def jwks(url):
    """Return the cached PyJWKClient for ``url`` (per-container, keyed BY URL).

    Keyed on the argument rather than caching the first client and ignoring every later
    one (SPEC-151 FR-009). The single-pool case is unaffected — the same URL still yields
    the same client — but a second URL used to be silently served the FIRST pool's client,
    which would verify tokens against the wrong JWKS. Latent while there is one pool, and
    exactly the kind of thing the transition to Identity Center could surface as an
    inexplicable signature failure.
    """
    if url not in _jwks:
        from jwt import PyJWKClient

        _jwks[url] = PyJWKClient(url)
    return _jwks[url]
