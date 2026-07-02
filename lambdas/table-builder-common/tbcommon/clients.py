"""Lazy, cached AWS + JWKS client factories.

Clients are created once per warm container and reused. Heavy deps (boto3, PyJWT)
are imported lazily so a verb that doesn't need a client never pays for it. Tests
patch the cached globals directly (e.g. clients._s3 = Fake()).
"""

_s3 = None
_sqs = None
_glue = None
_athena = None
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


def athena():
    global _athena
    if _athena is None:
        import boto3

        _athena = boto3.client("athena")
    return _athena


def sqs():
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs")
    return _sqs


def jwks(url):
    """Return the cached PyJWKClient for the User Pool JWKS endpoint."""
    global _jwks
    if _jwks is None:
        from jwt import PyJWKClient

        _jwks = PyJWKClient(url)
    return _jwks
