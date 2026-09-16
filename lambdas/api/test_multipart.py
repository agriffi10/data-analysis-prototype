"""The multipart plan, the capability rules, and every fault's mapping.

**The plan's constant is computed here rather than asserted.** A hard-coded part size hides a
wrong model: the number is what the slowest supported uplink can move inside half a part's
window, so the test recomputes it from those three inputs and states the answer. Moving any input
moves a number a reader can see.

**The refusal tests count CALLS, not just codes.** A route that refuses after building a client
has already paid an ``AssumeRole``, and from outside the process that is indistinguishable from an
IAM denial — so every zero-cost refusal asserts the zero.
"""

import datetime
import json

import pytest
import router
from apicommon import identity, s3_config
from apicommon.envelope import ApiError
from apicommon.identity import AssumedCredentials
from conftest import bearer
from routes import objects_upload

_ALICE = {"kind": "personal", "name": "alice"}


class FakeS3:
    """An S3 client recording every call, and raising whatever a test configures.

    Attributes:
      calls: Operation names in order, so a create-before-check is visible by ORDER.
      signed: ``(operation, params, expires_in)`` per mint.
      assumes: How many times the identity door was opened.
      covering: The window the route asked the credential layer to cover.
    """

    def __init__(self, occupied=False, raises=None, upload_id="upload-1"):
        """Builds the fake.

        Args:
          occupied: Whether ``head_object`` reports an existing object.
          raises: ``{operation: error_code}`` for operations that should fail.
          upload_id: What ``create_multipart_upload`` returns.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls = []
        self.signed = []
        self.assumes = 0
        self.covering = None
        self.completed = []
        self._occupied = occupied
        self._raises = raises or {}
        self._upload_id = upload_id

    def _record(self, operation, kwargs):
        """Records a call and raises when the operation is configured to fail.

        Args:
          operation: The operation name.
          kwargs: Its keyword arguments.

        Returns:
          None.

        Raises:
          _AwsError: When the operation is configured to fail.
        """
        self.calls.append(operation)
        if operation in self._raises:
            raise _AwsError(self._raises[operation])

    def head_object(self, **kwargs):
        """Reports the configured occupancy.

        Args:
          **kwargs: The head request.

        Returns:
          A head response when occupied.

        Raises:
          _AwsError: When absent, or when configured to fail.
        """
        self._record("head_object", kwargs)
        if not self._occupied:
            raise _AwsError("NoSuchKey")
        return {"ContentLength": 1}

    def create_multipart_upload(self, **kwargs):
        """Creates the upload.

        Args:
          **kwargs: The create request.

        Returns:
          The upload id.

        Raises:
          _AwsError: When configured to fail.
        """
        self._record("create_multipart_upload", kwargs)
        return {"UploadId": self._upload_id}

    def complete_multipart_upload(self, **kwargs):
        """Assembles the parts.

        Args:
          **kwargs: The complete request.

        Returns:
          The assembled object's ETag.

        Raises:
          _AwsError: When configured to fail.
        """
        self.completed.append(kwargs)
        self._record("complete_multipart_upload", kwargs)
        return {"ETag": '"assembled"'}

    def abort_multipart_upload(self, **kwargs):
        """Abandons the upload.

        Args:
          **kwargs: The abort request.

        Returns:
          An empty response.

        Raises:
          _AwsError: When configured to fail.
        """
        self._record("abort_multipart_upload", kwargs)
        return {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        """Records and returns a URL carrying what a real SigV4 presign carries.

        Args:
          operation: The operation being signed.
          Params: The signed parameters.
          ExpiresIn: The window.

        Returns:
          The URL.

        Raises:
          None.
        """
        self.calls.append("generate_presigned_url")
        self.signed.append((operation, Params, ExpiresIn))
        return (
            f"https://s3.example/{Params['Key']}"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Expires={ExpiresIn}"
            "&X-Amz-Security-Token=test-session-token"
            "&X-Amz-Signature=deadbeef"
        )


class _AwsError(Exception):
    """A botocore-shaped failure carrying a service error code."""

    def __init__(self, code):
        """Builds it.

        Args:
          code: The service error code.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": ""}}


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


@pytest.fixture
def s3(monkeypatch):
    """Installs a fake on BOTH credential doors.

    Both, because the create route uses either depending on the mode it chooses, and a fixture
    installing one door lets the other reach a real ``AssumeRole`` in a test that thinks it is
    offline.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      A factory taking the fake and returning it.

    Raises:
      None.
    """

    def _install(fake, seconds_left=3600):
        credentials = AssumedCredentials(
            access_key_id="AK",
            secret_access_key="SK",
            session_token="ST",
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=seconds_left),
        )

        def _user_door(service, caller):
            fake.assumes += 1
            return fake

        def _signing_door(service, caller, *, covering):
            fake.assumes += 1
            fake.covering = covering
            return fake, credentials

        monkeypatch.setattr(identity, "user_client", _user_door)
        monkeypatch.setattr(identity, "signing_client", _signing_door)
        return fake

    return _install


def _post(path, body):
    """Drives one request through the router.

    Args:
      path: The route path.
      body: The request body.

    Returns:
      The gateway answer.

    Raises:
      None.
    """
    return router.route("POST", path, bearer(), "rq", body, None)


def _create_body(size, **over):
    """Builds a create request.

    Args:
      size: The declared object size.
      **over: Fields to replace.

    Returns:
      The body.

    Raises:
      None.
    """
    return {
        "space": _ALICE,
        "key": "alice/big.bin",
        "contentType": "application/octet-stream",
        "overwrite": False,
        "size": size,
        **over,
    }


class TestThePartSizeIsComputedNotChosen:
    """FR-002 — a hard-coded cap hides a wrong model, so the test carries the model."""

    def test_the_part_size_is_what_the_slowest_uplink_moves_in_half_a_window(self) -> None:
        """Recomputed from its three inputs, and it states the answer in MiB.

        The budget: a part must finish inside its own presigned window on the slowest connection
        this product undertakes to serve, with a factor of safety so a transient stall is not an
        expiry. Clamped to S3's published per-part limits.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If the constant stops agreeing with the model that sized it.
        """
        budget = (
            s3_config.MIN_SUPPORTED_UPLINK_BYTES_PER_SEC
            * s3_config.PART_URL_EXPIRY_SECONDS
            // s3_config.PART_WINDOW_SAFETY_FACTOR
        )
        expected = min(
            max(budget, s3_config.MULTIPART_MIN_PART_BYTES), s3_config.MULTIPART_MAX_PART_BYTES
        )

        assert expected == s3_config.MULTIPART_PART_BYTES
        # 2 Mbps × 900 s ÷ 2 = 112,500,000 bytes ≈ 107.3 MiB. Stated so a changed input is
        # visible as a changed number rather than as a still-passing test.
        assert s3_config.MULTIPART_PART_BYTES == 112_500_000
        assert round(s3_config.MULTIPART_PART_BYTES / (1024 * 1024), 1) == 107.3

    def test_the_threshold_is_the_part_size_and_not_a_second_constant(self) -> None:
        """One quantity: the largest object that can be trusted inside one window.

        Bound rather than restated, because two equal constants are two constants that can stop
        being equal.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If they are separate objects.
        """
        assert s3_config.MULTIPART_THRESHOLD_BYTES is s3_config.MULTIPART_PART_BYTES

    def test_the_carried_service_limits_are_the_published_values(self) -> None:
        """Carried across, explicitly NOT derived.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If one drifted.
        """
        assert s3_config.MULTIPART_MIN_PART_BYTES == 5 * 1024 * 1024
        assert s3_config.MULTIPART_MAX_PART_BYTES == 5 * 1024 * 1024 * 1024
        assert s3_config.MULTIPART_MAX_PARTS == 10_000

    def test_the_part_window_fits_inside_a_session(self) -> None:
        """A window no session can span forces an AssumeRole per part, silently and for ever.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If the part window reaches the role's own ceiling.
        """
        from apicommon import config

        assert s3_config.PART_URL_EXPIRY_SECONDS < config.ASSUME_ROLE_DURATION_SECONDS
        assert s3_config.PART_URL_EXPIRY_SECONDS == s3_config.UPLOAD_URL_EXPIRY_SECONDS


class TestThePlanIsDeterminate:
    """FR-002 — no range and no choice, so every boundary is assertable."""

    @pytest.mark.parametrize(
        ("size", "expected_parts"),
        [
            (s3_config.MULTIPART_THRESHOLD_BYTES + 1, 2),
            (s3_config.MULTIPART_PART_BYTES * 2, 2),
            (s3_config.S3_SINGLE_PUT_MAX_BYTES, 48),
        ],
    )
    def test_the_plan_for_a_multipart_size(self, size, expected_parts) -> None:
        """Part size is the constant; the count follows from it.

        Args:
          size: The declared object size.
          expected_parts: How many parts the plan must have.

        Returns:
          None.

        Raises:
          AssertionError: If the plan is not the stated one.
        """
        part_size, part_count = objects_upload.part_plan(size)

        assert part_size == s3_config.MULTIPART_PART_BYTES
        assert part_count == expected_parts

    def test_the_last_part_is_allowed_below_the_minimum(self) -> None:
        """One byte over the threshold makes a 1-byte second part, which S3 permits.

        The arithmetic produces this constantly, so a plan refusing it would refuse almost every
        real file.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If the plan does not produce the tiny last part.
        """
        size = s3_config.MULTIPART_THRESHOLD_BYTES + 1
        part_size, part_count = objects_upload.part_plan(size)
        last = size - part_size * (part_count - 1)

        assert last == 1
        assert last < s3_config.MULTIPART_MIN_PART_BYTES

    def test_a_size_no_plan_can_serve_is_refused_rather_than_shipped(self, monkeypatch) -> None:
        """FR-002's one real conflict is a REFUSAL, not a tie-break.

        Driven by moving the CONSTANTS, because no file size reaches this while the browser
        clamps to S3's single-PUT ceiling. Letting the upper bound win instead would produce
        sub-5-MiB parts that S3 refuses at complete with ``EntityTooSmall`` — shipping the
        failure rather than refusing it.

        Args:
          monkeypatch: The pytest fixture.

        Returns:
          None.

        Raises:
          AssertionError: If it does not refuse, or refuses without naming the limit.
        """
        monkeypatch.setattr(s3_config, "MULTIPART_MAX_PARTS", 10)
        monkeypatch.setattr(s3_config, "MULTIPART_PART_BYTES", 1_000)
        monkeypatch.setattr(s3_config, "MULTIPART_THRESHOLD_BYTES", 1_000)

        with pytest.raises(ApiError) as raised:
            objects_upload.part_plan(10_001)

        assert raised.value.code == "PayloadTooLarge"
        assert raised.value.params == {"limit": 10_000}

    def test_the_refusal_costs_no_aws_call(self, monkeypatch, s3) -> None:
        """"Before any S3 call" is asserted by COUNT, not left to the reading order.

        Args:
          monkeypatch: The pytest fixture.
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the refusal reached AWS or cost an AssumeRole.
        """
        monkeypatch.setattr(s3_config, "MULTIPART_MAX_PARTS", 10)
        monkeypatch.setattr(s3_config, "MULTIPART_PART_BYTES", 1_000)
        monkeypatch.setattr(s3_config, "MULTIPART_THRESHOLD_BYTES", 1_000)
        fake = s3(FakeS3())

        answer = _post("/v1/objects/upload", _create_body(10_001))

        assert answer["statusCode"] == 413
        assert json.loads(answer["body"])["error"]["code"] == "PayloadTooLarge"
        assert fake.calls == [], "the refusal reached AWS"
        assert fake.assumes == 0, "the refusal cost an AssumeRole"


class TestTheServerChoosesThePath:
    """FR-005 — the browser never learns the threshold, so a test has to watch the fork."""

    @pytest.mark.parametrize(
        ("size", "mode"),
        [
            (s3_config.MULTIPART_THRESHOLD_BYTES - 1, "single"),
            (s3_config.MULTIPART_THRESHOLD_BYTES, "single"),
            (s3_config.MULTIPART_THRESHOLD_BYTES + 1, "multipart"),
        ],
    )
    def test_the_comparison_is_strictly_greater_than(self, s3, size, mode) -> None:
        """A file of exactly the threshold takes one PUT, so an off-by-one is visible.

        Args:
          s3: The client fixture.
          size: The declared size.
          mode: The path the server must choose.

        Returns:
          None.

        Raises:
          AssertionError: If the fork lands on the wrong side.
        """
        s3(FakeS3())

        answer = _post("/v1/objects/upload", _create_body(size))
        body = json.loads(answer["body"])

        assert answer["statusCode"] == 200
        assert body["mode"] == mode

    def test_a_single_upload_answers_a_url_and_no_plan(self, s3) -> None:
        """The single branch is one API call, exactly as before this spec.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If it leaks plan members or creates an upload.
        """
        fake = s3(FakeS3())

        body = json.loads(_post("/v1/objects/upload", _create_body(1024))["body"])

        assert body["mode"] == "single"
        assert body["url"].startswith("https://s3.example/")
        assert "uploadId" not in body
        assert "create_multipart_upload" not in fake.calls

    def test_a_multipart_upload_answers_a_plan_and_no_url(self, s3) -> None:
        """The multipart branch mints nothing at create — each part is minted as it is sent.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If it mints a URL or omits the plan.
        """
        fake = s3(FakeS3())
        size = s3_config.MULTIPART_PART_BYTES * 3

        body = json.loads(_post("/v1/objects/upload", _create_body(size))["body"])

        assert body["mode"] == "multipart"
        assert body["uploadId"] == "upload-1"
        assert body["partSize"] == s3_config.MULTIPART_PART_BYTES
        assert body["partCount"] == 3
        assert "url" not in body
        assert fake.signed == [], "create minted a URL for a multipart upload"


class TestNothingIsCreatedForAnOccupiedKey:
    """FR-001 — a route that creates first has already made something needing an abort."""

    def test_an_occupied_key_refuses_before_the_upload_exists(self, s3) -> None:
        """Asserted by call ORDER: the head must precede the create, and the create must not run.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If an upload was created for a refused request.
        """
        fake = s3(FakeS3(occupied=True))
        size = s3_config.MULTIPART_PART_BYTES * 2

        answer = _post("/v1/objects/upload", _create_body(size))
        body = json.loads(answer["body"])

        assert answer["statusCode"] == 409
        assert body["error"]["code"] == "Conflict"
        assert body["error"]["params"] == {"name": "big.bin"}
        assert fake.calls == ["head_object"], "an upload was created for a refused key"

    @pytest.mark.parametrize(
        # `assert_replaceable` refuses FOUR things, and a guard driven on one of them is a guard
        # that survives being swapped for the weaker `assert_writable` — measured: it did.
        "key",
        [
            "alice/system_settings/archive/secret.bin",
            "alice/reports/DO_NOT_DELETE.txt",
            "alice/system_settings/athenaresults/secret.bin",
            "alice/_data-quality-reports/7f3ac19d/manifest.json",
        ],
    )
    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/v1/objects/upload",
                {"contentType": "text/plain", "overwrite": True, "size": 1024},
            ),
            ("/v1/objects/upload/part", {"uploadId": "upload-1", "partNumber": 1}),
        ],
    )
    def test_no_route_mints_for_a_protected_location(self, s3, path, body, key) -> None:
        """A URL is minted only after EXACTLY the authorization the direct call would have had.

        Driven on the part route as well as on create, and the part route is the one that needed
        saying: it cannot be reached without an ``uploadId`` that create refuses to issue for
        these keys, and the bucket Denies the write underneath — so a mint here is not redeemable
        and the omission was invisible to every other assertion. The rule is about where the mint
        happens, not about whether this particular mint could be spent.

        Args:
          s3: The client fixture.
          path: The route under test.
          body: The rest of its request.
          key: A write-locked location, a marker key, a key in the query results folder and one in
            the data-quality reports folder — the four things the check refuses.

        Returns:
          None.

        Raises:
          AssertionError: If either route mints for a write-locked location.
        """
        fake = s3(FakeS3())

        answer = _post(path, {"space": _ALICE, "key": key, **body})

        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.signed == [], "a URL was minted for a write-locked location"
        assert fake.assumes == 0

    @pytest.mark.parametrize("overwrite", [True, False])
    def test_a_marker_key_is_never_uploadable(self, s3, overwrite) -> None:
        """The stricter rule at BOTH settings, and nothing is created either way.

        Carried onto this route rather than left behind on ``objects.uploadUrl``: the guard that
        states it lives beside the route that mints, so retiring the old route must not retire
        the rule. A marker object would sit at a key the listing hides by basename and nobody can
        ever remove.

        Args:
          s3: The client fixture.
          overwrite: Driven at BOTH settings, because the stricter rule applies at both and a
            single setting cannot show that.

        Returns:
          None.

        Raises:
          AssertionError: If a marker key reaches AWS or mints anything.
        """
        fake = s3(FakeS3())

        answer = _post(
            "/v1/objects/upload",
            _create_body(1024, key="alice/reports/DO_NOT_DELETE.txt", overwrite=overwrite),
        )

        assert answer["statusCode"] == 403
        assert "url" not in json.loads(answer["body"])
        assert fake.calls == []
        assert fake.assumes == 0


class TestTheUploadIdIsACapabilityAndNotAnAuthorization:
    """FR-006 — the id looks like authorization, which is exactly what makes this easy to miss."""

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/v1/objects/upload/part",
                {"key": "bob/big.bin", "uploadId": "upload-1", "partNumber": 1},
            ),
            (
                "/v1/objects/upload/complete",
                {
                    "key": "bob/big.bin",
                    "uploadId": "upload-1",
                    "parts": [{"partNumber": 1, "etag": '"a"'}],
                    "overwrite": False,
                },
            ),
            ("/v1/objects/upload/abort", {"key": "bob/big.bin", "uploadId": "upload-1"}),
        ],
    )
    def test_a_valid_upload_id_against_a_foreign_space_refuses_with_no_aws_call(
        self, s3, path, body
    ) -> None:
        """Space resolution runs from CLAIMS on every route, never from the id.

        The id here is real and well-formed. What refuses the request is that alice's claims do
        not authorize bob's space — and the refusal must cost nothing, because a refusal issued
        after a successful AssumeRole is indistinguishable from an IAM denial.

        Args:
          s3: The client fixture.
          path: The route under test.
          body: A well-formed request naming a foreign space.

        Returns:
          None.

        Raises:
          AssertionError: If a foreign space is served, or refused at a cost.
        """
        fake = s3(FakeS3())

        answer = _post(path, {"space": {"kind": "personal", "name": "bob"}, **body})

        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.calls == [], "the refusal reached AWS"
        assert fake.assumes == 0, "the refusal cost an AssumeRole"

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/v1/objects/upload",
                {
                    "key": "bob/theirs.bin",
                    "contentType": "application/octet-stream",
                    "overwrite": False,
                    "size": 1024,
                },
            ),
            (
                "/v1/objects/upload/part",
                {"key": "bob/theirs.bin", "uploadId": "upload-1", "partNumber": 1},
            ),
            (
                "/v1/objects/upload/complete",
                {
                    "key": "bob/theirs.bin",
                    "uploadId": "upload-1",
                    "parts": [{"partNumber": 1, "etag": '"a"'}],
                    "overwrite": False,
                },
            ),
            ("/v1/objects/upload/abort", {"key": "bob/theirs.bin", "uploadId": "upload-1"}),
        ],
    )
    def test_an_escaping_key_is_refused_on_every_route(self, s3, path, body) -> None:
        """Containment runs on ALL FOUR routes, and this is the half that needs its own case.

        The foreign-SPACE cases above cannot reach containment: they name bob's space, so every
        one is refused at ``space_from_body`` and the key is never examined. Dropping
        ``contained`` from create, complete or abort left the whole suite green until this test
        existed — which is FR-006 AC1's second clause, "space resolution **and key containment**
        run on part, complete and abort exactly as on create".

        The space here is the caller's OWN, so only the key can refuse it. And the refusal must
        be ``AccessDenied``: ``protected.contained_key`` wraps ``assert_inside_root`` precisely
        because the bare call raises a ``TerminalError`` the classifier does not recognise, which
        answers 500 where the requirement is 403 — it fails SAFELY, so an assertion counting AWS
        calls passes straight over it. Assert the reason code.

        Args:
          s3: The client fixture.
          path: The route under test.
          body: A well-formed request whose key escapes the caller's root.

        Returns:
          None.

        Raises:
          AssertionError: If a key outside the caller's root is served, or refused as a fault.
        """
        fake = s3(FakeS3())

        answer = _post(path, {"space": _ALICE, **body})

        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.calls == [], "the refusal reached AWS"
        assert fake.assumes == 0, "the refusal cost an AssumeRole"

    def test_no_emitted_field_carries_the_upload_id_or_a_signature(self, monkeypatch, s3) -> None:
        """FR-006 AC3 — an upload id in the log store is a capability in the log store.

        Driven across every one of the four routes, because one unstamped route is the whole
        leak. The span may carry the key's LENGTH and the part number; it may not carry the id,
        the key or anything from a signed URL.

        Args:
          monkeypatch: The pytest fixture.
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If any emitted value contains the id or a signature.
        """
        emitted: list[dict] = []
        monkeypatch.setattr(
            "cpcommon.observability.stamp", lambda **fields: emitted.append(fields)
        )
        s3(FakeS3())
        secret = "upload-1"

        _post("/v1/objects/upload", _create_body(s3_config.MULTIPART_PART_BYTES * 2))
        _post(
            "/v1/objects/upload/part",
            {"space": _ALICE, "key": "alice/big.bin", "uploadId": secret, "partNumber": 2},
        )
        _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": secret,
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": True,
            },
        )
        _post(
            "/v1/objects/upload/abort",
            {"space": _ALICE, "key": "alice/big.bin", "uploadId": secret},
        )

        assert emitted, "nothing was stamped, so this would pass over an unstamped fleet"
        values = [str(value) for fields in emitted for value in fields.values()]
        assert not [value for value in values if secret in value]
        assert not [value for value in values if "X-Amz-Signature" in value]
        assert not [value for value in values if "alice/big.bin" in value]
        assert any(fields.get("key_length") == len("alice/big.bin") for fields in emitted)
        assert any(fields.get("part_number") == 2 for fields in emitted)

    def test_a_part_url_is_signed_for_the_part_window_and_clamped_to_its_session(
        self, s3, monkeypatch
    ) -> None:
        """A part URL is a bearer token, so it inherits the single PUT's every rule.

        Twenty seconds of session must not mint fifteen minutes of URL.

        **The part window is moved before asserting on it.** It and the upload window are both
        900 today, so against the shipped values this assertion cannot tell which constant the
        route read — signing parts with the upload window would satisfy it exactly. Moving one
        makes the two distinguishable, which is the only way the assertion means anything while
        FR-002 deliberately keeps them equal.

        Args:
          s3: The client fixture.
          monkeypatch: The pytest fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the URL outlives its signature, or the wrong window was requested.
        """
        monkeypatch.setattr(s3_config, "PART_URL_EXPIRY_SECONDS", 777)
        fake = s3(FakeS3(), seconds_left=20)

        answer = _post(
            "/v1/objects/upload/part",
            {"space": _ALICE, "key": "alice/big.bin", "uploadId": "upload-1", "partNumber": 1},
        )

        assert answer["statusCode"] == 200
        assert fake.covering == 777, "the route signed a part with a different window"
        assert fake.signed[0][0] == "upload_part"
        assert fake.signed[0][1]["PartNumber"] == 1
        assert fake.signed[0][2] <= 20


class TestEveryFaultMapsOntoTheClosedEnum:
    """FR-008 — S3's multipart faults have names the enum does not carry, and it stays closed."""

    @pytest.mark.parametrize(
        ("path", "body", "operation"),
        [
            (
                "/v1/objects/upload/complete",
                {
                    "space": _ALICE,
                    "key": "alice/big.bin",
                    "uploadId": "gone",
                    "parts": [{"partNumber": 1, "etag": '"a"'}],
                    "overwrite": True,
                },
                "complete_multipart_upload",
            ),
            (
                "/v1/objects/upload/abort",
                {"space": _ALICE, "key": "alice/big.bin", "uploadId": "gone"},
                "abort_multipart_upload",
            ),
        ],
    )
    def test_an_expired_upload_id_is_a_404_and_never_a_403(self, s3, path, body, operation) -> None:
        """``NoSuchUpload`` must NOT go through the denial classifier.

        ``errors.DENIAL_CODES`` maps membership to 403 unconditionally, so adding this code there
        would tell a user they lack a permission when their upload simply expired. The mapping is
        a per-route raise for exactly that reason.

        Args:
          s3: The client fixture.
          path: The route under test.
          body: The request.
          operation: The S3 call that fails.

        Returns:
          None.

        Raises:
          AssertionError: If an absent upload is reported as a denial.
        """
        s3(FakeS3(raises={operation: "NoSuchUpload"}))

        answer = _post(path, body)

        assert answer["statusCode"] == 404
        assert json.loads(answer["body"])["error"]["code"] == "NotFound"

    @pytest.mark.parametrize("code", ["InvalidPart", "InvalidPartOrder", "EntityTooSmall"])
    def test_a_part_list_that_does_not_assemble_is_a_400(self, s3, code) -> None:
        """Three codes share one answer, so they are discriminated by FIXTURE.

        Asserting the shared code against one fixture would pass with the other two unmapped —
        each would fall through to the generic ``InternalError``. Driving each code separately is
        what makes removing any one of them from the mapping redden exactly one case.

        Args:
          s3: The client fixture.
          code: The S3 error code under test.

        Returns:
          None.

        Raises:
          AssertionError: If this particular code is unmapped.
        """
        s3(FakeS3(raises={"complete_multipart_upload": code}))

        answer = _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": True,
            },
        )

        assert answer["statusCode"] == 400
        assert json.loads(answer["body"])["error"]["code"] == "InvalidRequest"

    def test_an_unmapped_fault_is_not_dressed_up_as_something_specific(self, s3) -> None:
        """Without a mapping a fault stays unclassified and becomes the generic code ABOVE here.

        Which is what makes the per-route raise load-bearing: it is the only thing that turns a
        nameable failure into an authored sentence, and everything it does not name must keep
        arriving as ``InternalError`` rather than borrowing a neighbour's code.

        The observable at THIS layer is the propagation: ``router.route`` re-raises whatever
        ``errors.for_exception`` declines to classify, and the decorator outside the span mints
        the 500. Asserting a status here would be asserting the wrong layer — what this catches is
        a broad ``except`` in the route mapping ``SlowDown`` onto a code it does not mean.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If an unrecognised fault is classified, or classified wrongly.
        """
        from apicommon import errors

        s3(FakeS3(raises={"abort_multipart_upload": "SlowDown"}))

        with pytest.raises(_AwsError):
            _post(
                "/v1/objects/upload/abort",
                {"space": _ALICE, "key": "alice/big.bin", "uploadId": "upload-1"},
            )

        assert errors.for_exception(_AwsError("SlowDown"), "rq") is None, (
            "an unmapped multipart fault acquired a classification it does not have"
        )

    def test_no_new_code_was_added_to_the_enum(self) -> None:
        """FR-008 AC1 — the enum is closed, and this spec maps onto it rather than growing it.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If a multipart-shaped code reached the wire vocabulary.
        """
        from apicommon import contract

        codes = set(contract.walk(contract.ErrorCode).literals)

        assert not codes & {
            "NoSuchUpload",
            "InvalidPart",
            "InvalidPartOrder",
            "EntityTooSmall",
            "UploadNotFound",
        }


class TestTheCompleteTimeCollisionCheck:
    """FR-001 — the create-time check answers about a moment hours before the object exists."""

    def test_a_non_overwriting_complete_asks_s3_to_decide_at_write_time(self, s3) -> None:
        """``If-None-Match: *`` is what makes the second check race-free.

        A read-then-write here would re-open the very window it is meant to close.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the condition is absent.
        """
        fake = s3(FakeS3())

        _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": False,
            },
        )

        assert fake.completed[0]["IfNoneMatch"] == "*"
        assert "head_object" not in fake.calls, "a read-then-write reopens the race"

    def test_an_overwriting_complete_carries_no_condition(self, s3) -> None:
        """Overwrite is a live path, so an unconditional condition would fail every deliberate one.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If a deliberate overwrite is conditioned.
        """
        fake = s3(FakeS3())

        answer = _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": True,
            },
        )

        assert answer["statusCode"] == 200
        assert "IfNoneMatch" not in fake.completed[0]

    def test_losing_the_race_is_a_conflict_naming_the_file(self, s3) -> None:
        """S3 answers 412; the user is told the destination is occupied, not that something broke.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the race's loser gets an unactionable failure.
        """
        s3(FakeS3(raises={"complete_multipart_upload": "PreconditionFailed"}))

        answer = _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": False,
            },
        )
        body = json.loads(answer["body"])

        assert answer["statusCode"] == 409
        assert body["error"]["code"] == "Conflict"
        assert body["error"]["params"] == {"name": "big.bin"}


def test_a_200_carrying_an_error_body_does_not_read_as_success() -> None:
    """FR-008 AC4 — this repo's ``delete_objects`` trap, one service over.

    ``CompleteMultipartUpload`` can answer **200 OK** with an ``<Error>`` body, and a client that
    reads the status alone reports a failed assembly as a written object. botocore rewrites that
    status to 500 before parsing, so it surfaces as a failure — but boto3 is **deliberately
    unpinned** here, so this is a TRIPWIRE against whatever version is installed rather than a
    check of a pinned one. A bump that changed this behaviour would turn a failed assembly into a
    reported success with the whole suite green.

    Asserted against the real operation model and the real handler, because the API's fakes never
    reach a parser and a ``Stubber`` supplies an already-parsed response — under either, this
    would pass while proving nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If botocore stops converting the embedded error.
    """
    import botocore.session
    from botocore import handlers

    operation = botocore.session.get_session().get_service_model("s3").operation_model(
        "CompleteMultipartUpload"
    )
    response = {
        "status_code": 200,
        "headers": {},
        "body": b"<?xml version='1.0' encoding='UTF-8'?><Error><Code>InternalError</Code>"
        b"<Message>We encountered an internal error.</Message></Error>",
    }

    assert handlers._should_handle_200_error(operation, response), (
        "botocore no longer inspects this operation's 200 bodies"
    )
    handlers._handle_200_error(operation, response)
    assert response["status_code"] == 500, (
        "a 200 carrying an error body now reads as success — a failed assembly would be "
        "reported as a written object"
    )


class TestEveryRefusalIsExercised:
    """The half of the system no user drives, and a coverage number is blind to it.

    Each ``raise`` here is one line, so the happy path keeps the percentage high while the whole
    input-validation surface goes unasserted. Measured before these existed: deleting the entire
    upper bound from ``_part_number`` passed 2309 tests.
    """

    @pytest.mark.parametrize(
        ("path", "body", "why"),
        [
            ("/v1/objects/upload", {"size": -5}, "a negative size"),
            ("/v1/objects/upload", {"size": "4"}, "a size that is not a number"),
            ("/v1/objects/upload", {}, "no size at all"),
            ("/v1/objects/upload", {"size": True}, "a bool, which is an int in Python"),
        ],
    )
    def test_an_unusable_declared_size_is_refused(self, s3, path, body, why) -> None:
        """The size is a planning input, and an absent one must not read as zero.

        A missing ``size`` defaulting to 0 would send a 4 GiB file down the single-``PUT`` path
        silently — the plan would be computed for nothing at all.

        Args:
          s3: The client fixture.
          path: The route.
          body: The size field under test.
          why: What makes this size unusable.

        Returns:
          None.

        Raises:
          AssertionError: If an unusable size is planned against.
        """
        fake = s3(FakeS3())
        request = _create_body(0)
        request.pop("size")

        answer = _post(path, {**request, **body})

        assert answer["statusCode"] == 400, why
        assert json.loads(answer["body"])["error"]["code"] == "InvalidRequest"
        assert fake.calls == []

    @pytest.mark.parametrize(
        ("field", "value"),
        [("uploadId", ""), ("uploadId", None), ("partNumber", 0), ("partNumber", -1)],
    )
    def test_an_unusable_capability_or_part_number_is_refused(self, s3, field, value) -> None:
        """Both are read before any client is built, so neither costs an AssumeRole.

        Args:
          s3: The client fixture.
          field: Which field is unusable.
          value: Its unusable value.

        Returns:
          None.

        Raises:
          AssertionError: If it is accepted, or refused at a cost.
        """
        fake = s3(FakeS3())
        body = {
            "space": _ALICE,
            "key": "alice/big.bin",
            "uploadId": "upload-1",
            "partNumber": 1,
            field: value,
        }

        answer = _post("/v1/objects/upload/part", body)

        assert answer["statusCode"] == 400
        assert json.loads(answer["body"])["error"]["code"] == "InvalidRequest"
        assert fake.assumes == 0

    def test_a_part_number_past_s3s_ceiling_is_refused(self, s3) -> None:
        """The UPPER bound specifically, which no other case reaches.

        Deleting ``<= MULTIPART_MAX_PARTS`` from the predicate passed the entire suite before
        this existed — the lower bound alone satisfied every other assertion.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If a part number past S3's ceiling is signed.
        """
        fake = s3(FakeS3())

        answer = _post(
            "/v1/objects/upload/part",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "partNumber": s3_config.MULTIPART_MAX_PARTS + 1,
            },
        )

        assert answer["statusCode"] == 400
        assert json.loads(answer["body"])["error"]["code"] == "InvalidRequest"
        assert fake.signed == [], "a part past S3's ceiling was signed"

    @pytest.mark.parametrize(
        ("parts", "why"),
        [
            ([], "an empty list assembles nothing"),
            ("not-a-list", "a string is not a part list"),
            ([{"partNumber": 1}], "a part with no etag"),
            ([{"partNumber": 1, "etag": ""}], "a part with an EMPTY etag"),
            ([{"etag": '"a"'}], "a part with no number"),
            (["not-a-dict"], "a part that is not an object"),
        ],
    )
    def test_a_part_list_that_cannot_be_shaped_is_refused(self, s3, parts, why) -> None:
        """The three raises in the shaper share one message, so they discriminate by FIXTURE.

        The empty-etag case is the one that matters most: an absent ``ETag`` response header
        reads as an empty string rather than as an error, so this is the shape a CORS regression
        would actually produce.

        Args:
          s3: The client fixture.
          parts: The malformed part list.
          why: What makes it malformed.

        Returns:
          None.

        Raises:
          AssertionError: If a malformed part list reaches S3.
        """
        fake = s3(FakeS3())

        answer = _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": parts,
                "overwrite": True,
            },
        )

        assert answer["statusCode"] == 400, why
        assert json.loads(answer["body"])["error"]["code"] == "InvalidRequest"
        assert fake.calls == []

    def test_an_upload_s3_created_without_an_id_is_a_fault(self, s3) -> None:
        """S3 answering without an ``UploadId`` must not become an empty-string capability.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If an empty upload id reaches the browser as a usable plan.
        """
        s3(FakeS3(upload_id=""))

        answer = _post(
            "/v1/objects/upload", _create_body(s3_config.MULTIPART_PART_BYTES * 2)
        )

        assert answer["statusCode"] == 500
        assert json.loads(answer["body"])["error"]["code"] == "InternalError"

    def test_a_deliberate_overwrite_skips_the_occupancy_check_entirely(self, s3) -> None:
        """The short-circuit, which nothing exercised — and whose loss 409s every overwrite.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If a deliberate overwrite is refused or costs a HEAD.
        """
        fake = s3(FakeS3(occupied=True))

        answer = _post(
            "/v1/objects/upload",
            _create_body(s3_config.MULTIPART_PART_BYTES * 2, overwrite=True),
        )

        assert answer["statusCode"] == 200
        assert fake.calls == ["create_multipart_upload"], "an overwrite paid for a HEAD"


def test_the_part_ceiling_boundary_is_exact(monkeypatch) -> None:
    """The largest size the PART ceiling can serve is served and the next byte is refused.

    Probing well past the boundary cannot see an off-by-one: with the refusal written ``>=``
    instead of ``>``, the largest servable size would be refused and every far-side probe would
    still pass. Both sides, one byte apart.

    The upload ceiling is lifted for this test, because it now refuses first — at 5 GiB, three
    orders of magnitude below where the part ceiling bites. Two refusals share one code, so each
    needs the other moved out of its way to be seen at all.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      None.

    Raises:
      AssertionError: If the boundary moves by a byte.
    """
    largest = s3_config.MULTIPART_PART_BYTES * s3_config.MULTIPART_MAX_PARTS
    monkeypatch.setattr(s3_config, "S3_SINGLE_PUT_MAX_BYTES", largest + 1)

    part_size, part_count = objects_upload.part_plan(largest)
    assert part_size == s3_config.MULTIPART_PART_BYTES
    assert part_count == s3_config.MULTIPART_MAX_PARTS

    with pytest.raises(ApiError) as raised:
        objects_upload.part_plan(largest + 1)
    assert raised.value.code == "PayloadTooLarge"
    assert raised.value.params == {"limit": largest}


def test_the_upload_ceiling_is_enforced_server_side_and_is_exact() -> None:
    """The ceiling multipart must not quietly raise, and the server is what holds it now.

    Before this route existed S3 enforced it **unforgeably**: a ``PutObject`` over the
    single-``PUT`` cap was refused by the service. A multipart upload has no such limit, so
    without a server-side check the API would accept a plan 209 times larger than the ceiling the
    product states — from any client that does not ask the browser first, which is every client
    that is not the browser.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the ceiling moves by a byte, or stops being enforced here.
    """
    ceiling = s3_config.S3_SINGLE_PUT_MAX_BYTES

    part_size, part_count = objects_upload.part_plan(ceiling)
    assert part_size == s3_config.MULTIPART_PART_BYTES
    assert part_count == 48

    with pytest.raises(ApiError) as raised:
        objects_upload.part_plan(ceiling + 1)
    assert raised.value.code == "PayloadTooLarge"
    assert raised.value.params == {"limit": ceiling}


def test_an_astronomically_large_size_is_a_refusal_and_not_a_fault(s3) -> None:
    """A huge declared size is refused, whichever guard gets to it first.

    The behaviour, end to end. The ceiling above is what actually answers this today; the
    companion below is what pins the arithmetic underneath it, because with the ceiling in place
    this test passes whether the division is integer or not.

    Args:
      s3: The client fixture.

    Returns:
      None.

    Raises:
      AssertionError: If a huge declared size faults instead of refusing.
    """
    fake = s3(FakeS3())

    answer = _post("/v1/objects/upload", _create_body(10**400))

    assert answer["statusCode"] == 413
    assert json.loads(answer["body"])["error"]["code"] == "PayloadTooLarge"
    assert fake.calls == []
    assert fake.assumes == 0


def test_the_assembled_etag_is_encoded_like_every_other_written_object(s3) -> None:
    """One ``ObjectWrittenResponse`` must not reach the browser in a different encoding.

    S3 returns an ETag wrapped in literal double quotes. Every other route emitting this type
    strips them, so a caller comparing or storing the value would get a string that only
    sometimes carries quotes — invisible to TypeScript, since both are ``string``, and invisible
    to the closed vocabulary.

    Args:
      s3: The client fixture.

    Returns:
      None.

    Raises:
      AssertionError: If the quotes reach the wire.
    """
    s3(FakeS3())

    body = json.loads(
        _post(
            "/v1/objects/upload/complete",
            {
                "space": _ALICE,
                "key": "alice/big.bin",
                "uploadId": "upload-1",
                "parts": [{"partNumber": 1, "etag": '"a"'}],
                "overwrite": True,
            },
        )["body"]
    )

    assert body["etag"] == "assembled"
    assert '"' not in body["etag"]


def test_the_conditional_complete_parameter_exists_in_the_installed_botocore() -> None:
    """``IfNoneMatch`` is what makes the complete-time collision check race-free.

    A tripwire rather than a version check, for the same reason as the 200-body one: boto3 is
    deliberately unpinned and the Lambda runtime supplies its own. If a runtime's botocore did
    not carry this input member, botocore would raise ``ParamValidationError`` for **every
    non-overwrite complete** — the default path — and it would surface as a generic
    ``InternalError`` with the whole suite green, because the fakes never reach parameter
    validation.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the parameter stops existing.
    """
    import botocore.session

    operation = (
        botocore.session.get_session()
        .get_service_model("s3")
        .operation_model("CompleteMultipartUpload")
    )

    assert "IfNoneMatch" in operation.input_shape.members, (
        "the conditional complete is unsupported here; every non-overwrite upload would fault"
    )


def test_the_plan_arithmetic_never_converts_a_declared_size_to_float(monkeypatch) -> None:
    """The ceiling is lifted so the arithmetic underneath it can be seen at all.

    ``json.loads`` builds Python ints of unbounded size, so ``size / n`` on a 400-digit value
    raises ``OverflowError`` — turning an expected refusal into a 500 that writes an error stack
    into a store retained for ever, repeatably, from one small body. An expected refusal is a
    return value; only unpredicted faults raise.

    **Measured: with the ceiling in place, restoring the float division passes every other test
    in this file**, because nothing reaches the division any more. So the ceiling is the live
    defence and this is the one that keeps the arithmetic honest if the ceiling ever moves —
    which it will, since raising it is a stated product decision rather than a technical one.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      None.

    Raises:
      AssertionError: If the plan arithmetic overflows instead of refusing.
    """
    monkeypatch.setattr(s3_config, "S3_SINGLE_PUT_MAX_BYTES", 10**500)

    with pytest.raises(ApiError) as raised:
        objects_upload.part_plan(10**400)

    assert raised.value.code == "PayloadTooLarge"


class TestTheSingleBranchKeepsWhatTheRetiredRouteHad:
    """Every property `objects.uploadUrl`'s tests held, now held here.

    Written BEFORE that route was deleted, not after: the retirement removes the only assertions
    for a mint's window, its clamp, its signed content type and its occupied-key refusal, and a
    deletion leaves nothing behind for a reviewer to read. These are re-pointed, not re-invented —
    each is the retired test's own claim, driven against the route that replaced it.
    """

    def test_it_asks_for_the_upload_window_and_clamps_to_the_signing_session(
        self, s3, monkeypatch
    ) -> None:
        """Twenty seconds of session must not mint fifteen minutes of URL.

        The window is moved before asserting on it, for the same reason the part window is: the
        upload and download windows are both 900, so against the shipped values the assertion
        cannot tell which constant the route read.

        Args:
          s3: The client fixture.
          monkeypatch: The pytest fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the URL outlives its signature, or the wrong window was requested.
        """
        monkeypatch.setattr(s3_config, "UPLOAD_URL_EXPIRY_SECONDS", 888)
        fake = s3(FakeS3(), seconds_left=20)

        answer = _post("/v1/objects/upload", _create_body(1024))

        assert answer["statusCode"] == 200
        assert fake.covering == 888, "the route signed an upload with a different window"
        assert fake.signed[0][2] <= 20

    def test_the_advertised_expiry_never_outlives_the_url(self, s3) -> None:
        """`expiresAt` is what the caller trusts, so it must not describe a longer life.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the advertised expiry exceeds the signing session's.
        """
        s3(FakeS3(), seconds_left=30)

        body = json.loads(_post("/v1/objects/upload", _create_body(1024))["body"])
        expires_at = datetime.datetime.fromisoformat(body["expiresAt"])

        assert expires_at <= datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=31)

    def test_it_signs_the_content_type_the_caller_declared(self, s3) -> None:
        """A different type at redemption fails the signature and 403s as a permissions problem.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If the declared content type is not what was signed.
        """
        fake = s3(FakeS3())

        _post("/v1/objects/upload", _create_body(1024, contentType="text/csv"))

        operation, params, _seconds = fake.signed[0]
        assert operation == "put_object"
        assert params["ContentType"] == "text/csv"
        assert params["Key"] == "alice/big.bin"

    def test_an_occupied_key_mints_NO_url_on_the_single_path_either(self, s3) -> None:
        """A route that mints first has already handed out the capability.

        The multipart branch has its own version of this; the single branch reaches a different
        few lines and had none once the retired route's test went.

        Args:
          s3: The client fixture.

        Returns:
          None.

        Raises:
          AssertionError: If a URL is minted for an occupied key.
        """
        fake = s3(FakeS3(occupied=True))

        answer = _post("/v1/objects/upload", _create_body(1024))
        body = json.loads(answer["body"])

        assert answer["statusCode"] == 409
        assert body["error"]["code"] == "Conflict"
        assert body["error"]["params"] == {"name": "big.bin"}
        assert "url" not in body
        assert fake.signed == [], "a URL was minted for an occupied key"
