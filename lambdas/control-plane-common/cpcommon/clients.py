"""Lazy, cached AWS and JWKS client factories shared by every control-plane verb.

Clients are created once per warm container and reused. Heavy dependencies (boto3, PyJWT)
are imported inside each factory so a verb that never needs a client never pays for it.
Tests patch the cached module globals directly (``clients._s3 = Fake()``).
"""

_s3 = None
_sqs = None
_glue = None
_athena = None
_cognito = None
_lf = None
_jwks = {}


def s3():
    """Returns the per-container S3 client, creating it on first use.

    Args:
      None.

    Returns:
      The cached boto3 S3 client.

    Raises:
      None.
    """
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def sqs():
    """Returns the per-container SQS client, creating it on first use.

    Args:
      None.

    Returns:
      The cached boto3 SQS client.

    Raises:
      None.
    """
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs")
    return _sqs


def glue():
    """Returns the per-container Glue client, creating it on first use.

    Args:
      None.

    Returns:
      The cached boto3 Glue client.

    Raises:
      None.
    """
    global _glue
    if _glue is None:
        import boto3

        _glue = boto3.client("glue")
    return _glue


def athena():
    """Returns the per-container Athena client, creating it on first use.

    Args:
      None.

    Returns:
      The cached boto3 Athena client.

    Raises:
      None.
    """
    global _athena
    if _athena is None:
        import boto3

        _athena = boto3.client("athena")
    return _athena


def cognito():
    """Returns the per-container Cognito Identity Provider client, created on first use.

    Args:
      None.

    Returns:
      The cached boto3 cognito-idp client.

    Raises:
      None.
    """
    global _cognito
    if _cognito is None:
        import boto3

        _cognito = boto3.client("cognito-idp")
    return _cognito


def lf():
    """Returns the per-container Lake Formation client, created on first use.

    Used by the shared-space verbs for LF-Tag and permission grants.

    Args:
      None.

    Returns:
      The cached boto3 lakeformation client.

    Raises:
      None.
    """
    global _lf
    if _lf is None:
        import boto3

        _lf = boto3.client("lakeformation")
    return _lf


def jwks(url):
    """Returns the per-container PyJWKClient for a JWKS endpoint, keyed by URL.

    Keyed on the argument rather than caching the first client and ignoring later ones: a
    second URL would otherwise be served the first pool's client and verify tokens against
    the wrong JWKS. Latent while there is one user pool, and a likely source of
    inexplicable signature failures once Identity Center federation lands.

    Args:
      url: The JWKS endpoint to build or look up a client for.

    Returns:
      The cached PyJWKClient for that URL.

    Raises:
      None.
    """
    if url not in _jwks:
        from jwt import PyJWKClient

        _jwks[url] = PyJWKClient(url)
    return _jwks[url]
