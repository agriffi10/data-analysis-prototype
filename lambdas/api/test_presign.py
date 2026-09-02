"""The presigned DOWNLOAD, and the fact a signed URL is a credential.

The upload half of this file moved to `test_multipart.py` when `objects.uploadUrl` retired — the
window, the clamp, the signed content type and the occupied-key refusal are all asserted there
against `objects.upload`. What is left here is the download route and the rules both share.

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
from apicommon import identity, s3_config
from apicommon.identity import AssumedCredentials
from conftest import bearer
from routes import objects_presign


class FakeSigner:
    """An S3 client that records what it was asked to sign.

    Attributes:
      signed: ``(operation, params, expires_in)`` per mint.
      calls: Operation names, in order.
      assumes: How many times the signing door was opened — an `AssumeRole` is an AWS call, and a
        refusal that costs one is not free. Invisible to ``calls``, which is why it is separate.
    """

    def __init__(self):
        """Builds the fake.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.signed = []
        self.calls = []
        self.assumes = 0

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        """Records and returns a URL.

        **Every parameter botocore emits is present, and that is the point.** A fake that emits
        only the two parameters an assertion happens to name cannot fail that assertion for the
        right reason: the guard below asks whether a presigned URL reached a log record, and a
        URL missing the fields a real one carries is not the artifact being guarded. This fake
        was previously two parameters wide while the client shipped SigV2, so the guard could
        not have caught a real leak.

        Args:
          operation: The operation being signed.
          Params: The signed parameters.
          ExpiresIn: The window.

        Returns:
          A URL carrying the query string a real SigV4 presign carries.

        Raises:
          None.
        """
        self.calls.append("generate_presigned_url")
        self.signed.append((operation, Params, ExpiresIn))
        return (
            f"https://s3.example/{Params['Key']}"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=test-credential%2F20260901%2Fus-east-1%2Fs3%2Faws4_request"
            "&X-Amz-Date=20260901T000000Z"
            f"&X-Amz-Expires={ExpiresIn}"
            "&X-Amz-SignedHeaders=host"
            "&X-Amz-Security-Token=test-session-token"
            "&X-Amz-Signature=deadbeef"
        )



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

    The stub hands back whatever it was built with, ignoring ``covering`` — deliberately, because
    these tests are about what the ROUTES do with the credentials they are given. It RECORDS the
    argument, though, and one test reads it: that the layer honours ``covering`` is
    `test_credential_cache_apicommon.py`'s subject, but that the routes ask for the right window is
    only checkable here, and a wrong argument is invisible to every other assertion in this file.

    The clamp stays the last line of defence for the case the force cannot fix: an AWS ceiling
    shorter than the ask, which role chaining makes real at one hour.

    Args:
      monkeypatch: The pytest fixture.
      fake: The signing client.
      credentials: What the FIRST read returns.

    Returns:
      None.

    Raises:
      None.
    """
    def _door(service, caller, *, covering):
        fake.assumes += 1
        fake.covering = covering
        return fake, credentials

    monkeypatch.setattr(identity, "signing_client", _door)
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

    @pytest.mark.parametrize(
        ("path", "body", "window"),
        [
            (
                "/v1/objects/download-url",
                {"space": {"kind": "personal", "name": "alice"}, "key": "alice/big.csv"},
                s3_config.DOWNLOAD_URL_EXPIRY_SECONDS,
            ),
        ],
        ids=["download"],
    )
    def test_the_download_route_ASKS_FOR_the_window_it_signs_for(self, monkeypatch, path, body, window) -> None:
        """The argument, not the clamp — and without it the fix is decorative.

        ``signing_client(covering=…)`` forces a fresh session when the cached one cannot span the
        window. Pass a `covering` of 1 and the guard is satisfied by every session that is not
        already dead, no force ever fires, and the route is back to signing for whatever happens to
        remain — **which is the production behaviour this whole change exists to remove, and it
        passes every other test in this file.** Measured: with `covering=1` at the call site the
        suite was green. The upload route's equivalent lives in `test_multipart.py`.

        Args:
          monkeypatch: The pytest fixture.
          path: The route under test.
          body: Its request.
          window: The constant that route's URL is signed for.

        Returns:
          None.

        Raises:
          AssertionError: If the route asks for a window other than the one it signs.
        """
        fake = FakeSigner()
        # A session that comfortably covers either window, so the only thing this can fail on is
        # the argument the route passed.
        _install(monkeypatch, fake, _credentials(s3_config.DOWNLOAD_URL_EXPIRY_SECONDS * 10))

        answer = router.route("POST", path, bearer(), "rq", body, None)

        assert answer["statusCode"] == 200
        assert fake.covering == window

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/v1/objects/download-url",
                {"space": {"kind": "personal", "name": "alice"}, "key": "alice/big.csv"},
            ),
        ],
        ids=["download"],
    )
    def test_the_download_route_clamps(self, monkeypatch, path, body) -> None:
        """A download URL that dies early costs a retry, and this is what stops it.

        The upload side is the half that matters more — an upload URL that dies early 403s at the
        TAIL of a long transfer, after the bytes were sent — and it is asserted in
        `test_multipart.py` now, against both the single-`PUT` branch and a part. Ignoring the
        clamped value at the signing call left the whole suite green.
        """
        fake = FakeSigner()
        _install(monkeypatch, fake, _credentials(20))
        answer = router.route("POST", path, bearer(), "rq", body, None)
        assert answer["statusCode"] == 200
        assert fake.signed[0][2] <= 20

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

    def test_there_is_exactly_one_clamp_definition_in_the_whole_api(self) -> None:
        """Two copies of one arithmetic is how one of them stops being clamped.

        **Swept over every API module, not over the presign one.** Scoped to a single file this
        guard could not see the copy it most needed to: the second presigning surface arrives in
        a DIFFERENT module, so a duplicated clamp would have been invisible while this stayed
        green. The clamp now lives in ``routes/_presign.py`` and both surfaces call it.

        Counted on the parsed module rather than on raw source: a string count treats a docstring
        mention as a call site and reddens for a comment, which is a guard that cries wolf. What
        proves the clamp is USED is the parametrized test above, which drives both routes.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If the clamp is defined anywhere other than exactly once.
        """
        import ast
        import pathlib

        root = pathlib.Path(objects_presign.__file__ or "").parent.parent
        modules = sorted(root.rglob("*.py"))
        assert modules, "the sweep found no modules, so an empty population would pass"

        definitions = [
            f"{module.relative_to(root)}::{node.name}"
            for module in modules
            for node in ast.walk(ast.parse(module.read_text()))
            if isinstance(node, ast.FunctionDef) and node.name in {"clamped", "_clamped"}
        ]
        assert definitions == ["routes/_presign.py::clamped"]


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
        for parameter in (
            "X-Amz-Signature",
            "X-Amz-Credential",
            "X-Amz-Security-Token",
            "AWSAccessKeyId",
            "x-amz-security-token",
            "Signature=",
        ):
            assert parameter not in blob, f"{parameter} reached an emitted record"
        assert "secret.csv" not in blob, "the key itself is not a field either"

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
        assert fake.assumes == 0, "the refusal opened the signing door"


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
