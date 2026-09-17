"""Unit tests for dqcommon.run_claim — one request id, one execution.

The fake S3 enforces the conditional create the way S3 does: a write under ``If-None-Match: *``
to a key that exists fails ``412``. A fake that ignored the condition would pass every test here
without exercising the claim at all.
"""

import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CPCOMMON = os.path.join(_HERE, "..", "control-plane-common")
sys.path.insert(0, _CPCOMMON)
sys.path.insert(0, _HERE)

from cpcommon import clients
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError, TransientError
from dqcommon import messages, run_claim

REQUEST_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
RUN_1 = "arn:aws:states:eu-west-2:111122223333:execution:dq:run-1"
RUN_2 = "arn:aws:states:eu-west-2:111122223333:execution:dq:run-2"


class _ClientError(Exception):
    """Shaped like botocore's, which is all ``cpcommon.errors.error_code`` reads."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """An S3 that refuses a conditional create over an existing key."""

    def __init__(self, objects=None, put_error=None):
        self.objects = dict(objects or {})
        self.put_error = put_error
        self.puts = []
        self.gets = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        if self.put_error:
            raise _ClientError(self.put_error)
        if kwargs.get("IfNoneMatch") == "*" and kwargs["Key"] in self.objects:
            raise _ClientError("PreconditionFailed")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        return {"Body": _Body(self.objects[Key])}


def _arm(**kwargs):
    fake = _FakeS3(**kwargs)
    clients.s3 = lambda: fake
    return fake


def _refusal(request_id, execution_arn):
    with pytest.raises(TerminalError) as caught:
        run_claim.claim(request_id, execution_arn)
    return caught.value


def test_the_first_claim_is_a_conditional_create_naming_this_execution():
    """The write is conditional, in the admin bucket, and records the execution rather than the request."""
    fake = _arm()

    run_claim.claim(REQUEST_ID, RUN_1)

    (put,) = fake.puts
    assert put["Bucket"] == cpconfig.ADMIN_BUCKET
    assert put["Key"] == f"data-quality/claims/{REQUEST_ID}.json"
    assert put["IfNoneMatch"] == "*"
    assert json.loads(put["Body"])["executionArn"] == RUN_1


def test_the_same_execution_finds_its_own_claim_and_another_is_refused():
    """A Task retry carries on; a second execution with the same id is refused and changes nothing."""
    fake = _arm()
    run_claim.claim(REQUEST_ID, RUN_1)
    stored = fake.objects[run_claim.claim_key(REQUEST_ID)]

    run_claim.claim(REQUEST_ID, RUN_1)
    refused = _refusal(REQUEST_ID, RUN_2)

    assert refused.reason == messages.REQUEST_ID_REUSED
    assert RUN_1 in refused.detail
    assert fake.objects[run_claim.claim_key(REQUEST_ID)] == stored


@pytest.mark.parametrize(
    "stored",
    [b"not json", b"[]", json.dumps({"requestId": REQUEST_ID}).encode()],
    ids=["unparseable", "not-an-object", "no-holder"],
)
def test_a_claim_that_names_no_holder_is_refused_rather_than_taken(stored):
    """Only this plane writes a claim, so one it cannot read is not evidence the id is free."""
    _arm(objects={run_claim.claim_key(REQUEST_ID): stored})

    assert _refusal(REQUEST_ID, RUN_1).reason == messages.REQUEST_ID_REUSED


@pytest.mark.parametrize(
    ("put_error", "raised"),
    [("ConditionalRequestConflict", TransientError), ("SlowDown", TransientError), ("AccessDenied", _ClientError)],
    ids=["interrupted", "throttled", "denied"],
)
def test_a_write_that_did_not_reach_a_holder_never_counts_as_claimed(put_error, raised):
    """Only a 412 is evidence about the holder. A 409 or a throttle retries; a denial fails the run.

    A denied write is what the role sees if the grant lands after the code, and treating it as
    claimed would run every check unclaimed with nothing going red.
    """
    fake = _arm(put_error=put_error)

    with pytest.raises(raised) as caught:
        run_claim.claim(REQUEST_ID, RUN_1)

    assert type(caught.value) is raised
    assert fake.gets == []


@pytest.mark.parametrize(
    ("request_id", "execution_arn"),
    [
        (REQUEST_ID.upper(), RUN_1),
        (REQUEST_ID.replace("-", ""), RUN_1),
        (f" {REQUEST_ID}", RUN_1),
        (f"{REQUEST_ID}/..", RUN_1),
        (12345, RUN_1),
        (None, RUN_1),
        (REQUEST_ID, ""),
        (REQUEST_ID, None),
    ],
    ids=["upper-case", "no-hyphens", "padded", "suffixed", "not-a-string", "absent", "blank-arn", "no-arn"],
)
def test_a_non_canonical_id_or_a_missing_arn_is_refused_before_any_write(request_id, execution_arn):
    """A table's name is the id without hyphens and Glue folds case, so only one spelling may claim."""
    fake = _arm()

    refused = _refusal(request_id, execution_arn)

    assert refused.reason == messages.INVALID_REQUEST
    assert fake.puts == []


def test_the_silent_reason_is_raisable_with_only_this_domain_imported():
    """The shared layer registers the code, and a deployed function imports only its own domain.

    The suite imports every domain into one process, where a code one of them registers validates
    for all of them. A fresh interpreter with only ``dqcommon`` on the path is what production is.
    """
    script = (
        "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
        "from dqcommon import messages\n"
        "from cpcommon.errors import TerminalError\n"
        "TerminalError(messages.REQUEST_ID_REUSED, 'held by another execution')\n"
    )

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script, _CPCOMMON, _HERE],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert messages.REQUEST_ID_REUSED not in messages._BODIES
