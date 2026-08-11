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
import re
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


def test_every_page_of_common_prefixes_is_consumed(s3):
    """Pagination is the difference between a directory of everyone and a directory of the
    first 1000 people — and the truncated version looks perfectly healthy.
    """
    fake = s3([["alice/", "bob/"], ["cara/"], ["dan/"]])

    result = build_directory.handler({}, None)

    assert _document(fake)["usernames"] == ["alice", "bob", "cara", "dan"]
    assert result["username_count"] == 4


def test_prefixes_that_are_not_catalog_safe_usernames_are_dropped(s3):
    """Including `_directory` itself — dropped by the REGEX, not by a special case. A leading
    underscore cannot start a catalog-safe identifier, which is exactly why that reserved name
    was chosen (FR-003).
    """
    fake = s3([["alice/", "_directory/", "Bob/", "x/", "has-hyphen/", "9lives/"]])

    build_directory.handler({}, None)

    assert _document(fake)["usernames"] == ["alice"]


def test_the_dropped_count_is_reported(s3, captured_events):
    s3([["alice/", "_directory/", "Bob/"]])
    captured_events.events.clear()

    build_directory.handler({}, None)

    published = captured_events.messages("published")
    assert published and published[0]["fields"]["dropped_count"] == 2
    assert published[0]["fields"]["username_count"] == 1


def test_a_duplicate_prefix_appears_once(s3):
    fake = s3([["alice/", "alice/"], ["alice/"]])

    build_directory.handler({}, None)

    assert _document(fake)["usernames"] == ["alice"]


def test_the_module_never_reaches_for_cognito():
    """The source decision, pinned as a property rather than a comment.

    Cognito is the obvious source and is the WRONG one on the far side of the client
    transition (see the module docstring). A future reader "fixing" this back — or adding a
    union "to be safe" — trips this test rather than shipping a second source with different
    completeness properties.

    Checked over the AST rather than the raw text, deliberately: the module docstring ARGUES
    about Cognito at length, so a substring search over the source would either fail on the
    explanation or have to be weakened until it proved nothing. What is asserted here is that
    no NAME in the executable module — no import, no attribute, no call — is `cognito`.
    """
    tree = ast.parse((HERE / "build_directory.py").read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    offenders = {n for n in imported | attributes | used if "cognito" in n.lower()}
    assert offenders == set(), f"the builder must not reach for Cognito: {offenders}"


# -- FR-002: the published document ----------------------------------------------------


def test_the_document_shape(s3):
    fake = s3([["alice/", "bob/"]])

    build_directory.handler({}, None)

    put = fake.puts[-1]
    assert put["Bucket"] == "user-bkt"
    assert put["Key"] == "_directory/usernames.json"
    assert put["ContentType"] == "application/json"
    document = _document(fake)
    assert document["version"] == 1
    assert document["count"] == 2
    assert document["usernames"] == ["alice", "bob"]
    assert document["generatedAt"].endswith("Z")


def test_no_cache_control_and_no_conditional_write(s3):
    """Two absences that are decisions (FR-002).

    `Cache-Control` is omitted because the browser fetches this through the SDK with SigV4,
    not through CloudFront. The conditional-write headers are omitted because there is exactly
    one writer on a 24-hour schedule and last-wins is correct — this is not the append-under-CAS
    situation `log_sweep` and `dqcommon.index_store` are in.
    """
    fake = s3([["alice/"]])

    build_directory.handler({}, None)

    put = fake.puts[-1]
    assert "CacheControl" not in put
    assert "IfMatch" not in put and "IfNoneMatch" not in put


def test_an_empty_result_never_overwrites_the_existing_document(s3):
    """The guard that matters most. A listing failure returning an empty page would otherwise
    erase the directory — and an erased directory is indistinguishable to a user from a broken
    feature, because the suggestions simply stop appearing.
    """
    fake = s3([[]])

    result = build_directory.handler({}, None)

    assert fake.puts == []
    assert result == {"published": False, "username_count": 0}


def test_an_all_dropped_result_is_also_empty_and_writes_nothing(s3):
    fake = s3([["_directory/", "Bob/"]])

    assert build_directory.handler({}, None)["published"] is False
    assert fake.puts == []


def test_the_empty_guard_is_reported_as_an_error(s3, captured_events):
    s3([[]])
    captured_events.events.clear()

    build_directory.handler({}, None)

    assert captured_events.messages("no usernames found; not publishing")


# -- FR-006: idempotence ---------------------------------------------------------------


def test_two_runs_produce_the_same_document_apart_from_generated_at(s3):
    fake = s3([["bob/", "alice/"]])

    build_directory.handler({}, None)
    first = _document(fake)
    build_directory.handler({}, None)
    second = _document(fake)

    assert {k: v for k, v in first.items() if k != "generatedAt"} == {
        k: v for k, v in second.items() if k != "generatedAt"
    }


# -- FR-007: the directory is never an authorization input -----------------------------


def test_no_other_lambda_references_the_directory(s3):
    """The tripwire. The document is advisory: a name's presence in it grants nothing, and
    every existence check stays `admin_get_user` against the User Pool.

    A control plane that started reading this path would be trusting a list that is up to a
    day stale, that is missing every user not yet provisioned, and that any of them can make
    look wrong by not opening the file browser.

    Matches the PREFIX and this module's two constants as well as the object name (FR-007 says
    "the path or the object name"): a module that listed `_directory/` to read what is there,
    or that assembled the key from `DIRECTORY_PREFIX`, would slip past an object-name-only
    check while doing exactly what this forbids.

    The prefix is matched WITH its trailing slash rather than bare — a bare `_directory` is a
    substring of the perfectly innocent `test_every_lambda_directory_is_in_the_deploy_matrix`,
    and a tripwire that cries wolf gets weakened rather than heeded.

    `dqcommon.config` is the one legitimate mention — it lists `_directory` as a RESERVED
    prefix, which is the opposite of reading it — so it is allowlisted by name.

    `test_feature_flags_config.py` is the second, and is not Lambda code at all: it is a
    repo-as-data suite that names this document to explain why SPEC-162's publish addresses
    ONE EXACT KEY and never syncs — precisely so that a mis-scoped reconcile cannot delete
    what lives one prefix over. Forbidding the mention would delete the reasoning, not the
    coupling. What this tripwire is actually about — a control plane treating the directory
    as an authorization input — is untouched by it.
    """
    allowed = {"data-quality-common/dqcommon/config.py", "test_feature_flags_config.py"}
    markers = ("usernames.json", "_directory/", "DIRECTORY_PREFIX", "DIRECTORY_KEY")
    offenders = []
    for path in LAMBDAS.rglob("*.py"):
        if HERE in path.parents or path == HERE / "build_directory.py":
            continue
        if "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(LAMBDAS))
        if relative in allowed:
            continue
        text = path.read_text()
        if any(marker in text for marker in markers):
            offenders.append(relative)
    assert offenders == [], f"the directory document is not an authorization input: {offenders}"


# -- FR-008: observability -------------------------------------------------------------


def _event_count(s3, captured_events, user_count):
    s3([[f"user{n:04d}/" for n in range(user_count)]])
    captured_events.events.clear()
    build_directory.handler({}, None)
    return len(captured_events.events)


def test_the_event_count_does_not_grow_with_the_number_of_users(s3, captured_events):
    """The guard, not the comment (mirroring SPEC-131's for the sweep). `logs/` is retained
    forever, so a per-username emitter turns a growing organisation into a permanently growing
    log bill — and it is exactly the line someone adds while debugging one user's absence.
    """
    few = _event_count(s3, captured_events, 5)
    many = _event_count(s3, captured_events, 500)

    assert few == many, f"{few} events for 5 users but {many} for 500 — an emitter is per-user"


def test_the_username_list_itself_is_never_logged(s3, captured_events):
    """Usernames are metadata and individually permitted under the field rule. The LIST is a
    different thing: it is the whole document, already durable in S3, in a store that never
    expires.
    """
    s3([["alice/", "bob/"]])
    captured_events.events.clear()

    build_directory.handler({}, None)

    assert captured_events.events, "nothing was captured — this guard would pass vacuously"
    for event in captured_events.events:
        # Fields are nested under `fields`; asserting over event.values() alone would never
        # look at a single emitted field and would pass no matter what the builder logged.
        for value in event.get("fields", {}).values():
            assert "alice" not in (value if isinstance(value, (list, str)) else ())


def test_the_handler_is_traced(s3, captured_events):
    """Only the span is asserted here, and the name says so.

    The SERVICE deliberately is not: `conftest.captured_events` reconfigures log-foundry with
    `service="test"` to install its collector, so any assertion about `user-directory` reaching
    the sink would be testing the fixture. The `init` call is pinned by the source check below
    instead — an honest split, rather than a test whose name promises what it cannot check.
    """
    s3([["alice/"]])
    captured_events.events.clear()

    build_directory.handler({}, None)

    assert captured_events.spans("build-directory"), "the handler must carry @traced('build-directory')"


def test_observability_is_initialised_with_the_plane_name():
    source = (HERE / "build_directory.py").read_text()
    assert 'observability.init(service="user-directory")' in source


def test_echo_appears_nowhere():
    assert "echo=" not in (HERE / "build_directory.py").read_text()


def test_logs_queue_url_is_never_required(s3):
    """The PR #196 / PR #317 cold-start trap: a `_require` on an optional variable turns a
    missing env var into a function that cannot start, and on a scheduled function that is a
    silent stop rather than a visible failure.
    """
    source = (HERE / "build_directory.py").read_text()
    assert "_require" not in source


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


def test_the_function_environment_carries_everything_cpcommon_requires():
    """Every variable `cpcommon.config` requires must be ASSIGNED in this function's Terraform
    environment. SPEC-156 moved the fail-fast from import to first access, which narrows the
    blast radius but not this obligation: any of the six can be read on any code path, and a
    function that sets five is one branch away from the failure that broke signup for nine days
    (PR #317). Terraform still sets all six for every attaching function.
    """
    assigned = _terraform_environment_variables()
    required = {
        "COGNITO_USER_POOL_ID",
        "COGNITO_APP_CLIENT_ID",
        "ADMIN_BUCKET",
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        "ATHENA_WORKGROUP",
    }
    missing = required - assigned
    assert missing == set(), f"lambda.tf is missing {missing} — cold-start crash (PR #196)"


def test_the_environment_parser_actually_found_the_block():
    """Guards the guard: a parser that returned nothing would make the test above pass by
    finding no variables at all rather than by finding the right ones.
    """
    assigned = _terraform_environment_variables()
    assert "LOGS_QUEUE_URL" in assigned, f"parsed only {assigned} from lambda.tf"


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


def test_config_still_requires_exactly_what_this_test_pins():
    """Guards the guard above: a variable added to `cpcommon.config`'s required set must be
    added to this function's environment too, and the test that would catch that must not be a
    stale hard-coded list.
    """
    required = _cpcommon_required_variables()
    assert required == {
        "COGNITO_USER_POOL_ID",
        "COGNITO_APP_CLIENT_ID",
        "ADMIN_BUCKET",
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        "ATHENA_WORKGROUP",
    }


# -- FR-003: the reserved prefix is on every list that governs a user's own space -------


def test_directory_is_reserved_in_dqcommon_and_in_both_spa_lists():
    dq = (LAMBDAS / "data-quality-common" / "dqcommon" / "config.py").read_text()
    assert '"_directory"' in dq

    spa = (
        LAMBDAS.parent
        / "apps"
        / "portal"
        / "src"
        / "features"
        / "file-browser"
        / "protectedFolders.ts"
    ).read_text()
    def declared(name):
        """The array literal DECLARED for `name`, not the first place the name appears.

        Splitting on the bare name matched a prose mention of it in that file's header comment
        first, so both lists read as the comment text and the assertion below passed on the
        wrong string. Anchored on `export const <name> = [ ... ]` instead, and tolerant of a
        multi-line array.
        """
        match = re.search(rf"export const {name}\s*=\s*\[(.*?)\]", spa, re.DOTALL)
        assert match, f"could not find the {name} declaration"
        return match.group(1)

    hidden = declared("HIDDEN_BROWSER_FOLDERS")
    picker = declared("PICKER_LOCKED_FOLDERS")
    assert "_directory" in hidden and "_directory" in picker
    # Guards the parser: a match that swallowed the file would contain both names.
    assert "export const" not in hidden and "export const" not in picker


def test_the_handler_ignores_its_event_payload(s3):
    """A manual `aws lambda invoke` with any payload must produce a full rebuild (FR-006)."""
    fake = s3([["alice/"]])

    build_directory.handler({"anything": "at all"}, None)
    build_directory.handler(None, None)

    assert len(fake.puts) == 2
