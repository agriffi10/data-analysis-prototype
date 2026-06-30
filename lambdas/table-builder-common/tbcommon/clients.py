"""Lazy, cached AWS + JWKS client factories (SPEC-067 table-builder layer).

Clients are created once per warm container and reused (cold-start hygiene). Heavy
deps (boto3, PyJWT) are imported lazily so a verb that doesn't need a client never
pays for it. Tests patch the cached globals directly (e.g. ``clients._s3 = Fake()``).
"""

_s3 = None
_sqs = None
_jwks = None


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


def jwks(url):
    """Cached PyJWKClient for the User Pool JWKS endpoint (token verification)."""
    global _jwks
    if _jwks is None:
        from jwt import PyJWKClient

        _jwks = PyJWKClient(url)
    return _jwks
