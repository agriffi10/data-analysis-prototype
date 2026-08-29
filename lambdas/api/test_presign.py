"""The presign routes, and the fact a signed URL is a credential.

**The clamp test is the one that matters, and it is written to catch the implementation that looks
right.** Reading the expiry with a second `assume_user_role` is the obvious way to write it, it
passes any test using a long-lived credential, and it mints a URL advertising fifteen minutes when
the session signing it has twenty seconds left. So the test drives a near-dead credential and a
layer that hands back a fresh one on a second ask — which is exactly what the real layer does,
because a session with under half a minute left is refused as unusable.
"""

import datetime
import json

import pytest
import router
from apicommon import identity
from apicommon.identity import AssumedCredentials
from conftest import bearer
from routes import objects_presign


class FakeSigner:
    """An S3 client that records what it was asked to sign.

    Attributes:
      signed: ``(operation, params, expires_in)`` per mint.
      calls: Operation names, so a mint-before-check can be spotted by ORDER.
    """

    def __init__(self, occupied=False):
        """Builds the fake.

        Args:
          occupied: Whether ``head_object`` should report an existing object.

        Returns:
          None.

        Raises:
          None.
        """
        self.signed = []
        self.calls = []
        self._occupied = occupied

    def head_object(self, **kwargs):
        """Reports the configured occupancy.

        Args:
          **kwargs: The head request.

        Returns:
          A head response when occupied.

        Raises:
            _Missing: When not occupied.
        """
        self.calls.append("head_object")
        if not self._occupied:
            raise _Missing()
        return {"ContentLength": 1}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        """Records and returns a URL.

        Args:
          operation: The operation being signed.
          Params: The signed parameters.
          ExpiresIn: The window.

        Returns:
          A URL carrying a signature-shaped query string.

        Raises:
          None.
        """
        self.calls.append("generate_presigned_url")
        self.signed.append((operation, Params, ExpiresIn))
        return f"https://s3.example/{Params['Key']}?X-Amz-Signature=deadbeef&X-Amz-Expires={ExpiresIn}"


class _Missing(Exception):
    """A botocore-shaped absence."""

    def __init__(self):
        """Builds it.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__("NoSuchKey")
        self.response = {"Error": {"Code": "NoSuchKey", "Message": ""}}


def _credentials(seconds_left):
    """Builds credentials expiring in the given number of seconds.

    Args:
      seconds_left: How long the session has.

    Returns:
      The credentials.

    Raises:
      None.
    """
    return AssumedCredentials(
        access_key_id="AK",
        secret_access_key="SK",
        session_token="ST",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds_left),
    )


@pytest.fixture(autouse=True)
def _buckets(monkeypatch):
    """The bucket variables every route reads.

    Args:
      monkeypatch: The pytest fixture.

    Yields:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "user-bucket")
    monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bucket")
    yield


def _install(monkeypatch, fake, credentials):
    """Installs a signer whose second assume returns a FRESH session.

    That asymmetry is the real layer's behaviour, not a contrivance: `_usable` refuses a cached
    session with under half a minute left, so a second ask re-assumes. A clamp that asks twice
    reads the fresh one and signs with the stale one.

    Args:
      monkeypatch: The pytest fixture.
      fake: The signing client.
      credentials: What the FIRST read returns.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setattr(identity, "signing_client", lambda service, caller: (fake, credentials))
    monkeypatch.setattr(identity, "assume_user_role", lambda caller, force=False: _credentials(3600))
    monkeypatch.setattr(identity, "user_client", lambda service, caller: fake)


class TestTheUrlNeverOutlivesTheSessionThatSignedIt:
    """The defect that ships green and fails after the bytes are sent."""

    def test_a_near_dead_credential_clamps_the_window(self, monkeypatch) -> None:
        """Twenty seconds of session must not mint fifteen minutes of URL."""
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(20))
        answer = router.route(
            "POST",
            "/v1/objects/download-url",
            bearer(),
            "rq",
            {"space": {"kind": "personal", "name": "alice"}, "key": "alice/big.csv"},
            None,
        )
        assert answer["statusCode"] == 200
        assert fake.signed[0][2] <= 20

    def test_the_advertised_expiry_matches_the_signed_window(self, monkeypatch) -> None:
        """`expiresAt` is what the caller trusts; it must not describe a longer life than the URL has."""
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(30))
        answer = router.route(
            "POST",
            "/v1/objects/download-url",
            bearer(),
            "rq",
            {"space": {"kind": "personal", "name": "alice"}, "key": "alice/big.csv"},
            None,
        )
        expires_at = datetime.datetime.fromisoformat(json.loads(answer["body"])["expiresAt"])
        assert expires_at <= datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=31)

    def test_a_healthy_credential_gets_the_full_window(self, monkeypatch) -> None:
        """The control: the clamp must not shorten every URL to nothing."""
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(3600))
        router.route(
            "POST",
            "/v1/objects/download-url",
            bearer(),
            "rq",
            {"space": {"kind": "personal", "name": "alice"}, "key": "alice/big.csv"},
            None,
        )
        assert fake.signed[0][2] == 900

    def test_both_routes_read_the_same_clamp(self) -> None:
        """Two copies of one arithmetic is how one of them stops being clamped."""
        source = (
            __import__("pathlib").Path(objects_presign.__file__ or "").read_text()
        )
        assert source.count("def _clamped") == 1
        assert source.count("_clamped(") == 3, "one definition, one call per route"


class TestAUrlIsABearerToken:
    """A capability, so everything true of a credential is true of it."""

    def test_no_signature_reaches_an_emitted_record(self, monkeypatch) -> None:
        """A debug field stamping the URL would look like good telemetry."""
        emitted: list[dict] = []
        monkeypatch.setattr(
            "cpcommon.observability.stamp", lambda **fields: emitted.append(fields)
        )
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(3600))
        router.route(
            "POST",
            "/v1/objects/download-url",
            bearer(),
            "rq",
            {"space": {"kind": "personal", "name": "alice"}, "key": "alice/secret.csv"},
            None,
        )
        blob = json.dumps(emitted)
        assert "X-Amz-Signature" not in blob
        assert "secret.csv" not in blob, "the key itself is not a field either"

    def test_an_occupied_key_mints_NO_url(self, monkeypatch) -> None:
        """A route that mints first and checks after has handed out the capability already."""
        fake = FakeSigner(occupied=True)
        _install(monkeypatch, fake, _credentials(3600))
        answer = router.route(
            "POST",
            "/v1/objects/upload-url",
            bearer(),
            "rq",
            {
                "space": {"kind": "personal", "name": "alice"},
                "key": "alice/taken.csv",
                "contentType": "text/csv",
                "overwrite": False,
            },
            None,
        )
        assert answer["statusCode"] == 409
        assert "url" not in json.loads(answer["body"])
        assert fake.signed == []
        assert "generate_presigned_url" not in fake.calls

    def test_a_protected_location_mints_no_url_and_costs_no_assume(self, monkeypatch) -> None:
        """Refused server-side, not only by the browser's affordance."""
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(3600))
        answer = router.route(
            "POST",
            "/v1/objects/upload-url",
            bearer(),
            "rq",
            {
                "space": {"kind": "personal", "name": "alice"},
                "key": "alice/archive/receipt.json",
                "contentType": "application/json",
                "overwrite": True,
            },
            None,
        )
        assert answer["statusCode"] == 403
        assert fake.calls == []

    def test_a_foreign_space_mints_no_url(self, monkeypatch) -> None:
        """The isolation refusal reaches the presign routes too."""
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(3600))
        answer = router.route(
            "POST",
            "/v1/objects/download-url",
            bearer(),
            "rq",
            {"space": {"kind": "personal", "name": "bob"}, "key": "bob/secret.csv"},
            None,
        )
        assert answer["statusCode"] == 403
        assert fake.calls == []


class TestTheDispositionHeaderIsEscapedInTheRightOrder:
    """S3 permits `\"` in a key, and an unescaped one ends the quoted string early."""

    def test_a_quote_is_escaped(self) -> None:
        """Otherwise the rest of the filename is read as header parameters."""
        header = objects_presign.content_disposition('my"file.csv')
        assert 'filename="my\\"file.csv"' in header

    def test_a_backslash_is_escaped_BEFORE_the_quote(self) -> None:
        """Escaping quotes first double-escapes the backslash it just introduced."""
        header = objects_presign.content_disposition('a\\b"c.csv')
        assert 'filename="a\\\\b\\"c.csv"' in header

    def test_the_utf8_form_is_percent_encoded(self) -> None:
        """RFC 6266's second form carries what the quoted one cannot."""
        header = objects_presign.content_disposition("réport .csv")
        assert "filename*=UTF-8''r%C3%A9port%20.csv" in header
