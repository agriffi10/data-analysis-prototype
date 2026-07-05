"""Lazy, cached AWS + JWKS client factories.

Clients are created once per warm container and reused. Heavy deps (boto3, PyJWT)
are imported lazily so a verb that doesn't need a client never pays for it. Tests
patch the cached globals directly (e.g. clients._s3 = Fake()).
"""

_s3 = None
_cognito = None
_glue = None
_jwks = None


def glue():
    global _glue
    if _glue is None:
        import boto3

        _glue = boto3.client("glue")
    return _glue


def s3():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def cognito():
    global _cognito
    if _cognito is None:
        import boto3

        _cognito = boto3.client("cognito-idp")
    return _cognito


def jwks(url):
    """Return the cached PyJWKClient for the User Pool JWKS endpoint."""
    global _jwks
    if _jwks is None:
        from jwt import PyJWKClient

        _jwks = PyJWKClient(url)
    return _jwks
