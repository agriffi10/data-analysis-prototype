"""The bounded S3 client, read back off the client botocore builds rather than off its arguments."""

from cpcommon import clients


def test_the_bounded_client_is_built_with_the_bounds_its_constants_name(monkeypatch):
    """The client makes the attempts its constant names, and waits the bounds it names.

    botocore reads a client config's ``max_attempts`` as the number of retries, so passing the
    constant under that key made one attempt more than it names. The normalised config on the
    built client is what botocore acts on.
    """
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(clients, "_s3_bounded", None)

    config = clients.s3_bounded().meta.config

    assert config.retries == {"mode": "standard", "total_max_attempts": clients.BOUNDED_MAX_ATTEMPTS}
    assert config.connect_timeout == clients.BOUNDED_CONNECT_SECONDS
    assert config.read_timeout == clients.BOUNDED_READ_SECONDS
