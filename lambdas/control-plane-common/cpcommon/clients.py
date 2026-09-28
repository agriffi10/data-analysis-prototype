"""Lazy, cached AWS and JWKS client factories shared by every control-plane verb.

Clients are created once per warm container and reused. Heavy dependencies (boto3, PyJWT)
are imported inside each factory so a verb that never needs a client never pays for it.
Tests patch the cached module globals directly (``clients._s3 = Fake()``).

Attributes:
  BOUNDED_CONNECT_SECONDS: How long ``s3_bounded`` waits to connect before a call gives up.
  BOUNDED_READ_SECONDS: How long it waits for a response once connected.
  BOUNDED_MAX_ATTEMPTS: How many attempts one call makes in all, under the standard retry mode —
    one retry, so a single dropped connection is survived and a stalled endpoint is waited on at
    most twice. Passed as ``total_max_attempts``: botocore reads a client config's
    ``max_attempts`` as the number of RETRIES, so the same number there makes one attempt more.
"""

BOUNDED_CONNECT_SECONDS = 1

BOUNDED_READ_SECONDS = 2

BOUNDED_MAX_ATTEMPTS = 2

_s3 = None
_s3_bounded = None
_sqs = None
_sfn = None
_glue = None
_athena = None
_cognito = None
_lf = None
_jwks: dict = {}


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


def s3_bounded():
    """Returns an S3 client whose every call gives up within seconds, for work that is optional.

    The default client waits a minute for a response and makes five attempts, which is right for a
    verb's own work and wrong for a convenience riding along after it: a stalled endpoint would
    hold the verb past its Lambda timeout, and a timeout is outside every ``Retry`` and lands in
    the failure path of a run whose real work already succeeded. A caller of this client catches
    what it raises and moves on. The bounds limit each wait inside a call, not the call — the TLS
    handshake, a PUT's wait for ``100 Continue`` and the retry each add waits of their own — so a
    caller that must finish in time also runs each call under ``cpcommon.budget``.

    Args:
      None.

    Returns:
      The cached, bounded boto3 S3 client.

    Raises:
      None.
    """
    global _s3_bounded
    if _s3_bounded is None:
        import boto3
        from botocore.config import Config

        _s3_bounded = boto3.client(
            "s3",
            config=Config(
                connect_timeout=BOUNDED_CONNECT_SECONDS,
                read_timeout=BOUNDED_READ_SECONDS,
                retries={"mode": "standard", "total_max_attempts": BOUNDED_MAX_ATTEMPTS},
            ),
        )
    return _s3_bounded


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


def sfn():
    """Returns the per-container Step Functions client, creating it on first use.

    Args:
      None.

    Returns:
      The cached boto3 Step Functions client.

    Raises:
      None.
    """
    global _sfn
    if _sfn is None:
        import boto3

        _sfn = boto3.client("stepfunctions")
    return _sfn


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

    The client is a ``CooldownJWKClient`` rather than a bare ``PyJWKClient``: it carries an
    explicit HTTP timeout and rate-limits the cache-bypassing refetch that an unknown ``kid``
    triggers. Both of PyJWT's defaults were harmless while the only caller was a Step Functions
    verb and neither is once an unauthenticated caller can reach the verifier — see ``jwks``.

    Args:
      url: The JWKS endpoint to build or look up a client for.

    Returns:
      The cached JWKS client for that URL.

    Raises:
      None.
    """
    if url not in _jwks:
        from .jwks import CooldownJWKClient

        _jwks[url] = CooldownJWKClient(url)
    return _jwks[url]
