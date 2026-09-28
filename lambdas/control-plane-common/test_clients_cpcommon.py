"""The bounded clients, read back off the clients botocore builds rather than off their arguments."""

import pytest
from cpcommon import clients


@pytest.mark.parametrize(
    ("factory", "cached", "service"),
    [
        ("s3_bounded", "_s3_bounded", "s3"),
        ("athena_bounded", "_athena_bounded", "athena"),
        ("sqs_bounded", "_sqs_bounded", "sqs"),
    ],
)
def test_the_bounded_client_is_built_with_the_bounds_its_constants_name(
    monkeypatch, factory, cached, service
):
    """The client makes the attempts its constant names, and waits the bounds it names.

    botocore reads a client config's ``max_attempts`` as the number of retries, so passing the
    constant under that key made one attempt more than it names. The normalised config on the
    built client is what botocore acts on.
    """
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(clients, cached, None)

    client = getattr(clients, factory)()
    config = client.meta.config

    assert client.meta.service_model.service_name == service
    assert config.retries == {"mode": "standard", "total_max_attempts": clients.BOUNDED_MAX_ATTEMPTS}
    assert config.connect_timeout == clients.BOUNDED_CONNECT_SECONDS
    assert config.read_timeout == clients.BOUNDED_READ_SECONDS
