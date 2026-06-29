"""Lazy, cached AWS + JWKS client factories (SPEC-062 shared layer).

SDK clients are created once per warm container and reused across invocations
(§5 cold-start). Heavy deps (boto3, PyJWT) are imported lazily inside the factory
so a function that doesn't need a client never pays for it.

Tests patch the cached globals directly (e.g. ``clients._s3 = FakeS3()``); each
factory returns the global if already set, so no real AWS client is constructed.
"""

_s3 = None
_glue = None
_lf = None
_cognito = None
_sqs = None
_jwks = None


def s3():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def glue():
    global _glue
    if _glue is None:
        import boto3

        _glue = boto3.client("glue")
    return _glue


def lf():
    global _lf
    if _lf is None:
        import boto3

        _lf = boto3.client("lakeformation")
    return _lf


def cognito():
    global _cognito
    if _cognito is None:
        import boto3

        _cognito = boto3.client("cognito-idp")
    return _cognito


def sqs():
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs")
    return _sqs


def jwks(url):
    """Cached PyJWKClient for the User Pool JWKS endpoint (SPEC-056 token verify)."""
    global _jwks
    if _jwks is None:
        from jwt import PyJWKClient

        _jwks = PyJWKClient(url)
    return _jwks
