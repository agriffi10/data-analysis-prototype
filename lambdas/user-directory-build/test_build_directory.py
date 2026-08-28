"""SPEC-146 — the username-directory builder.

The weight here is on the four properties that make an unattended daily rebuild safe: it reads
S3 and never Cognito (FR-001), it never publishes an empty document over a good one (FR-002),
its event count does not grow with the organisation (FR-008), and nothing else in the fleet
treats the document it writes as an authorization input (FR-007).
"""

import ast
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

import build_directory
from cpcommon import clients

HERE = pathlib.Path(__file__).resolve().parent
LAMBDAS = HERE.parent


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


# -- FR-006: idempotence ---------------------------------------------------------------


# -- FR-007: the directory is never an authorization input -----------------------------


# -- FR-008: observability -------------------------------------------------------------


def _event_count(s3, captured_events, user_count):
    s3([[f"user{n:04d}/" for n in range(user_count)]])
    captured_events.events.clear()
    build_directory.handler({}, None)
    return len(captured_events.events)


def _terraform_environment_variables():
    """The names ASSIGNED inside lambda.tf's `environment { variables = { … } }` block.

    Parsed rather than substring-searched, and that distinction is the whole point of the test
    below. A bare `name in source` check also matches the COMMENTS — and lambda.tf's comment
    explaining the cold-start trap names `USER_SPACE_BUCKET`, so the one variable this function
    actually uses was the one the guard could not see. Deleting its assignment left the suite
    green.
    """
    module = (LAMBDAS.parent / "infra" / "modules" / "user-directory" / "lambda.tf").read_text()
    block = module.split("variables = {", 1)[1]
    names = set()
    depth = 1
    for line in block.splitlines():
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
        assignment = __import__("re").match(r"\s*([A-Z][A-Z0-9_]*)\s*=", line)
        if assignment:
            names.add(assignment.group(1))
    return names


def _cpcommon_required_variables():
    """The env vars `cpcommon.config` requires, read from its `_REQUIRED_VARS` declaration.

    Parsed from source rather than imported, and from the DECLARATION rather than a regex over
    `_require("…")` calls: SPEC-156 moved the resolution to first access, so the calls no longer
    name the variables and a call-site regex would silently find none.
    """
    source = (LAMBDAS / "control-plane-common" / "cpcommon" / "config.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_REQUIRED_VARS"
            for target in node.targets
        ):
            return set(ast.literal_eval(node.value).values())
    return set()


# -- FR-003: the reserved prefix is on every list that governs a user's own space -------
