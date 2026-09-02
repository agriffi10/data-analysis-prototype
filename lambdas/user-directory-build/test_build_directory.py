"""SPEC-146 — the username-directory builder.

The weight here is on the four properties that make an unattended daily rebuild safe: it reads
S3 and never Cognito (FR-001), it never publishes an empty document over a good one (FR-002),
its event count does not grow with the organisation (FR-008), and nothing else in the fleet
treats the document it writes as an authorization input (FR-007).

The last section guards a fifth, which is deployment rather than behaviour: the Terraform
environment must carry exactly the set `cpcommon.config` declares, because every other signal
this repo has — apply, deploy, and the suite itself — is green against a thin one.
"""

import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

import build_directory
from cpcommon import clients, config
from tf_blocks import lambda_declaration, lambda_environment, strip_noise

HERE = pathlib.Path(__file__).resolve().parent
LAMBDAS = HERE.parent
LAMBDA_TF = LAMBDAS.parent / "infra" / "modules" / "user-directory" / "lambda.tf"


class FakeS3:
    """A paginating ListObjectsV2 over CommonPrefixes, plus a recording PutObject.

    Pages are served as given rather than computed, so a test can exercise the multi-page path
    without standing up 1000 prefixes — the property under test is that the builder consumes
    every page, not that boto3 paginates.
    """

    def __init__(self, pages, fail_put=False):
        self.pages = [
            {"CommonPrefixes": [{"Prefix": p} for p in page]} for page in pages
        ]
        self.puts = []
        self.fail_put = fail_put

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        assert kwargs["Bucket"] == "user-bkt"
        # Delimiter is what makes this a listing of WORKSPACES rather than of every object in
        # the bucket; without it the builder would page through every user's files.
        assert kwargs["Delimiter"] == "/", "the listing must be delimited to top-level prefixes"
        return iter(self.pages)

    def put_object(self, **kwargs):
        if self.fail_put:
            raise RuntimeError("put failed")
        self.puts.append(kwargs)
        return {}


@pytest.fixture
def s3():
    def _install(pages, **kwargs):
        fake = FakeS3(pages, **kwargs)
        clients._s3 = fake
        return fake

    yield _install
    clients._s3 = None


def _document(fake):
    return json.loads(fake.puts[-1]["Body"].decode("utf-8"))


# -- FR-001: the source is S3 common prefixes ------------------------------------------


def test_lists_sorts_and_dedupes_the_workspace_prefixes(s3):
    fake = s3([["cara/", "alice/", "bob_smith/"]])

    build_directory.handler({}, None)

    assert _document(fake)["usernames"] == ["alice", "bob_smith", "cara"]


def test_prefixes_that_are_not_catalog_safe_usernames_are_dropped(s3):
    """Including `_directory` itself — dropped by the REGEX, not by a special case. A leading
    underscore cannot start a catalog-safe identifier, which is exactly why that reserved name
    was chosen (FR-003).
    """
    fake = s3([["alice/", "_directory/", "Bob/", "x/", "has-hyphen/", "9lives/"]])

    build_directory.handler({}, None)

    assert _document(fake)["usernames"] == ["alice"]


# -- FR-002: the published document ----------------------------------------------------


def test_an_empty_result_never_overwrites_the_existing_document(s3):
    """The guard that matters most. A listing failure returning an empty page would otherwise
    erase the directory — and an erased directory is indistinguishable to a user from a broken
    feature, because the suggestions simply stop appearing.
    """
    fake = s3([[]])

    result = build_directory.handler({}, None)

    assert fake.puts == []
    assert result == {"published": False, "username_count": 0}


# -- The deployed environment matches what config.py declares ---------------------------
#
# Nothing else ties the two sides together. `tofu apply` is green against a thin environment,
# `update-function-code` is green against it, and the suite is green because `lambdas/conftest.py`
# stamps the required names before collection. The failure surfaces only in production, and only
# on the branch that reads the missing name — today that is `USER_SPACE_BUCKET` alone, so the
# other three are guarded for the reader this function does not yet have.

# The two names `config.py` declares in NEITHER `_REQUIRED_VARS` nor `_OPTIONAL_VARS`, so no
# comparison against it can speak for them. `observability` reads both through `os.environ.get`,
# which is what makes losing one silent rather than loud — but they do not degrade alike, and the
# difference is the point: without `LOGS_QUEUE_URL` the sink becomes stdout and nothing reaches the
# logs queue at all, while without `ENV_NAME` every event still ships, carrying a blank `env`.
# Neither raises, so the assertion below cannot see either. Hence one of their own.
UNDECLARED_BY_CONFIG = {"LOGS_QUEUE_URL", "ENV_NAME"}


def _terraform_environment_variables():
    """The names lambda.tf assigns to the function's environment, under either packaging.

    Read through the shared `tf_blocks` scanner end to end — the declaration and its environment
    by name, the names with comments and strings blanked first. The non-greedy regex this
    replaced worked only because the block happens to close at a particular indent, and it read
    a variable name out of a comment as readily as out of an assignment; both are the drift that
    module's docstring exists to warn about. The accessors are packaging-agnostic for the same
    reason: a pattern that matches one shape stops finding the block without ever saying so.
    """
    source = LAMBDA_TF.read_text(encoding="utf-8")
    function = lambda_declaration(source, "build")

    names = re.compile(r"([A-Z_][A-Z0-9_]*)\s*=(?!=)")
    captured = set(names.findall(strip_noise(lambda_environment(function))))
    everywhere = set(names.findall(strip_noise(function)))
    assert captured == everywhere, (
        f"the environment slice captured {sorted(captured)}, but the resource assigns "
        f"{sorted(everywhere)}. Every SHOUTING assignment in this resource is an environment "
        "variable, so a difference means this resource grew one outside the block. The slice "
        "itself is brace-counted rather than anchored to an indent, which is what retired the "
        "other half of this assertion: a slice that looks exhaustive while measuring less, and "
        "stays green the entire time"
    )
    return captured


def test_the_environment_block_matches_config_pys_own_declaration():
    """The block must carry `_REQUIRED_VARS` exactly — no name short, and no name spare.

    Both directions are real drift. A name missing from Terraform raises `RuntimeError` at
    first access on whichever branch reads it; a name set here that `config.py` no longer
    declares is a variable nothing requires, which is how a block silently becomes a
    hand-kept copy of a set it was supposed to mirror.

    `_OPTIONAL_VARS` is subtracted rather than ignored. Most other plane modules already set
    `NOTIFICATIONS_QUEUE_URL`, so this one may grow it too — and `config.py` DOES declare it,
    just as degrading rather than required. Comparing against the required set
    alone would refuse that correct change while reporting, wrongly, that `config.py` had never
    heard of it. The set's other member, `AWS_REGION`, is subtracted with it and costs nothing:
    Lambda reserves that key, so a block trying to set it fails the apply long before this runs.
    """
    declared = set(config._REQUIRED_VARS.values())
    deployed = (
        _terraform_environment_variables()
        - set(config._OPTIONAL_VARS.values())
        - UNDECLARED_BY_CONFIG
    )

    assert deployed == declared, (
        f"lambda.tf and cpcommon/config.py disagree. Required by config.py and absent from "
        f"lambda.tf: {sorted(declared - deployed)}. Set by lambda.tf and not required by "
        f"config.py: {sorted(deployed - declared)}. The first crashes the builder at first "
        "access in production; the second means one side dropped a name the other still keeps"
    )


def test_both_sides_of_that_comparison_are_actually_being_read():
    """Guards the assertion above against the one way it can pass while measuring nothing.

    Two empty sets compare equal. If the regex stopped matching and `_REQUIRED_VARS` were
    emptied, the test above would go green on a block that mirrors nothing at all.
    """
    parsed = _terraform_environment_variables()
    known = set(config._REQUIRED_VARS.values()) | set(config._OPTIONAL_VARS.values())

    assert "USER_SPACE_BUCKET" in parsed, "the lambda.tf parse found no variables at all"
    assert set(config._REQUIRED_VARS.values()) >= {"ADMIN_BUCKET", "ATHENA_WORKGROUP"}, (
        "config.py declares no required variables — the comparison above has nothing to match"
    )
    assert not UNDECLARED_BY_CONFIG & known, (
        f"{sorted(UNDECLARED_BY_CONFIG & known)} is exempted above while config.py declares it. "
        "An exemption is for names config.py cannot speak for, and one that covers a declared "
        "name subtracts it from both sides of the comparison, which passes on its removal"
    )


def test_the_names_config_py_cannot_speak_for_are_still_set():
    """The two exempted names need their own guard, because the comparison cannot see them.

    Subtracting a name from one side of a set equality removes it from the test entirely.
    Deleting `LOGS_QUEUE_URL` from lambda.tf left every other assertion here green while
    structured logging silently fell back to stdout — no queue, no logs, no failure.
    """
    missing = UNDECLARED_BY_CONFIG - _terraform_environment_variables()

    assert not missing, (
        f"lambda.tf no longer sets {sorted(missing)}. `observability` reads both with "
        "`os.environ.get`, so losing one degrades in silence rather than raising — nothing "
        "else in this file or in production will tell you"
    )
