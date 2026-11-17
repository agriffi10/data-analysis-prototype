"""SPEC-146 — the username-directory builder.

The weight here is on the four properties that make an unattended daily rebuild safe: it reads
S3 and never Cognito (FR-001), it never publishes an empty document over a good one (FR-002),
its event count does not grow with the organisation (FR-008), and nothing else in the fleet
treats the document it writes as an authorization input (FR-007).

The last section guards a fifth, which is deployment rather than behaviour: the Terraform
environment must carry exactly the set `cpcommon.config` declares, because every other signal
this repo has — apply, deploy, and the suite itself — is green against a thin one.
"""

import ast
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
from tf_blocks import argument, lambda_declaration, strip_noise

HERE = pathlib.Path(__file__).resolve().parent
LAMBDAS = HERE.parent
LAMBDA_TF = LAMBDAS.parent / "infra" / "function-user-directory.tf"


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


# -- FR-007: the document is never an authorization input --------------------------------
#
# A name's presence in the directory grants nothing; every existence check stays against the User
# Pool. A control plane that started reading the document would be trusting a list that is up to a
# day stale and missing every user not yet provisioned.

DIRECTORY_MARKERS = ("usernames.json", "_directory/", "DIRECTORY_PREFIX", "DIRECTORY_KEY")

# The one production module allowed to open the document. It serves it to the browser, which is
# where the read always happened, and `ROUTE_SURFACE` holds it to deciding nothing from it.
DIRECTORY_ROUTE = pathlib.Path("api") / "routes" / "user_directory.py"

# The only module allowed to import that route: the dispatcher, which passes its answer through.
ROUTE_DISPATCHER = pathlib.Path("api") / "router.py"

# Everything the route imports and every attribute it reaches, pinned whole. Guessing the names of
# authorization helpers missed the real ones and any aliased import; an exact surface turns every
# new capability into a red test that someone has to read.
ROUTE_SURFACE = frozenset(
    {
        "apicommon.config.user_space_bucket",
        "apicommon.context.RequestContext",
        "apicommon.identity",
        "cpcommon.config.CATALOG_IDENTIFIER_RE",
        "cpcommon.observability",
        "json",
        "typing.Any",
        "acting_as",
        "aws_error_code",
        "fullmatch",
        "get",
        "get_object",
        "loads",
        "read",
        "stamp",
        "user_client",
        "warning",
    }
)


def _code_tokens(tree):
    """The strings and identifiers a module's code uses, leaving out its prose.

    A docstring or a bare string statement is prose; so is a comment, which the parser drops. A
    module explaining that it refuses `_directory/usernames.json` is the opposite of reading it,
    and a tripwire that fires on an explanation is one somebody deletes.

    Args:
      tree: A parsed module.

    Returns:
      Every string constant outside a bare expression statement, and every name, attribute and
      imported name.

    Raises:
      None.
    """
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    tokens = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
            tokens.add(node.value)
        elif isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            tokens.update(alias.name for alias in node.names)
    return tokens


def _imports_the_route(tree):
    """Whether a parsed module imports the directory route, in any import form.

    The module name comes from `DIRECTORY_ROUTE`, so moving the route and re-pointing that constant
    keeps this check aimed at it.

    Args:
      tree: A parsed module.

    Returns:
      True when an `import` or `from ... import` statement names the route module.

    Raises:
      None.
    """
    route = DIRECTORY_ROUTE.stem
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] == route for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[-1] == route:
                return True
            if any(alias.name == route for alias in node.names):
                return True
    return False


def _directory_readers(root):
    """Production modules under `root` that read the directory, other than its writer and server.

    A module reads it by using the key, the prefix or the key constants in its code, or by
    importing the route that serves it and so taking the list second-hand. `test_*.py` and
    `conftest.py` are skipped by shape rather than allowlisted by name: a suite that names the key
    is asserting which object a route opens or that a Deny covers it, which is the opposite of
    reading it, and a per-file allowlist grew a row every time a new suite did that. Other test
    helpers, such as `fakes.py`, are scanned like production code. The prefix is matched WITH its
    slash, because a bare `_directory` is a substring of innocent names. A key handed in through
    configuration is out of reach; no such variable exists.

    Args:
      root: The `lambdas/` tree to scan.

    Returns:
      Each offender as `path: what it used`, relative to `root`, sorted.

    Raises:
      SyntaxError: If a production module is not valid Python.
    """
    exempt = {pathlib.Path("user-directory-build") / "build_directory.py", DIRECTORY_ROUTE}
    offenders = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative in exempt or path.name.startswith("test_") or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tokens = _code_tokens(tree)
        used = sorted(m for m in DIRECTORY_MARKERS if any(m in token for token in tokens))
        if relative != ROUTE_DISPATCHER and _imports_the_route(tree):
            used.append(f"imports {DIRECTORY_ROUTE.stem}")
        if used:
            offenders.append(f"{relative}: {', '.join(used)}")
    return sorted(offenders)


def _route_surface(source):
    """What a module can reach: every import, fully dotted, and every attribute it names.

    Read from the syntax tree, never the text, so a docstring explaining why the route needs no
    check of its own does not count as reaching for one.

    Args:
      source: Python source text.

    Returns:
      The dotted import targets and attribute names.

    Raises:
      SyntaxError: If `source` is not valid Python.
    """
    surface = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            surface.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            surface.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Attribute):
            surface.add(node.attr)
    return surface


def _route_drift(source):
    """How a module's reach differs from the route's pinned surface, in either direction.

    Args:
      source: Python source text.

    Returns:
      The sorted names reached but not pinned, or pinned but no longer reached.

    Raises:
      SyntaxError: If `source` is not valid Python.
    """
    return sorted(_route_surface(source) ^ ROUTE_SURFACE)


def test_no_production_lambda_but_the_builder_and_its_route_reads_the_directory():
    offenders = _directory_readers(LAMBDAS)
    assert offenders == [], (
        f"these modules read the username directory: {offenders}. It is advisory and never an "
        "authorization input; ask the User Pool instead"
    )


def test_the_route_that_serves_the_directory_reaches_only_what_is_pinned():
    drift = _route_drift((LAMBDAS / DIRECTORY_ROUTE).read_text(encoding="utf-8"))
    assert drift == [], (
        f"the directory route's reach changed by {drift}. It serves the document and decides "
        "nothing from it; if the change decides nothing either, re-pin ROUTE_SURFACE"
    )


@pytest.mark.parametrize(
    ("reader", "used"),
    [(f"KEY = '{marker}'\n", marker) for marker in DIRECTORY_MARKERS[:2]]
    + [
        ("key = config.DIRECTORY_PREFIX\n", "DIRECTORY_PREFIX"),
        ("key = DIRECTORY_KEY\n", "DIRECTORY_KEY"),
        ("from build_directory import DIRECTORY_KEY as key\n", "DIRECTORY_KEY"),
        ("from routes.user_directory import _parse as parse\n", "imports user_directory"),
        ("from routes import (\n    user_directory,\n)\n", "imports user_directory"),
        ("import routes.user_directory as served\n", "imports user_directory"),
    ],
)
def test_the_tripwire_names_a_planted_reader_and_only_it(tmp_path, reader, used):
    """One planted reader per way of reading, beside every shape the guard must stay silent on.

    The silent shapes are a suite naming the key, the exempt route, the dispatcher importing it, a
    docstring and a comment explaining the directory, and a bare `_directory`.
    """
    planted = {
        pathlib.Path("some-plane") / "handler.py": reader,
        pathlib.Path("some-plane") / "test_handler.py": "KEY = '_directory/usernames.json'\n",
        pathlib.Path("some-plane") / "conftest.py": "from routes.user_directory import x\n",
        pathlib.Path("some-plane") / "explains.py": (
            '"""Refuses `_directory/usernames.json` as a user."""\n'
            "# never reads DIRECTORY_KEY\n"
            "RESERVED = ('_directory', '_config')\n"
        ),
        DIRECTORY_ROUTE: "KEY = '_directory/usernames.json'\n",
        ROUTE_DISPATCHER: "from routes.user_directory import user_directory\n",
        pathlib.Path("deploy") / "matrix.py": "CHECK = 'every_lambda_directory_is_listed'\n",
    }
    for relative, text in planted.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")

    assert _directory_readers(tmp_path) == [f"{pathlib.Path('some-plane') / 'handler.py'}: {used}"]


def test_the_route_surface_counts_aliased_imports_and_calls_but_not_prose():
    reaching = (
        "import json\n"
        "from cpcommon.cognito import user_exists as known\n"
        "def handler(client, name):\n"
        "    return known(name) and client.admin_get_user(Username=name)\n"
    )
    explaining = '"""Needs no admin_get_user or user_exists: the grant already authorizes."""\n'

    assert _route_surface(reaching) == {"json", "cpcommon.cognito.user_exists", "admin_get_user"}
    assert _route_surface(explaining) == set()


def test_the_route_pin_reddens_on_a_new_reach():
    route = (LAMBDAS / DIRECTORY_ROUTE).read_text(encoding="utf-8")
    widened = route + "from cpcommon.cognito import user_exists as known\n"

    assert "cpcommon.cognito.user_exists" in _route_drift(widened)


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
    """The names the root call to `scheduled-function` assigns to the function's environment.

    Read through the shared `tf_blocks` scanner end to end — the call and its
    `environment_variables` by name, the names with comments and strings blanked first. The
    non-greedy regex this replaced worked only because the block happens to close at a particular
    indent, and it read a variable name out of a comment as readily as out of an assignment; both
    are the drift that module's docstring exists to warn about.
    """
    source = LAMBDA_TF.read_text(encoding="utf-8")
    function = lambda_declaration(source, "user_directory")

    names = re.compile(r"([A-Z_][A-Z0-9_]*)\s*=(?!=)")
    captured = set(names.findall(strip_noise(argument(function, "environment_variables"))))
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
        f"function-user-directory.tf and cpcommon/config.py disagree. Required by config.py and absent from "
        f"function-user-directory.tf: {sorted(declared - deployed)}. Set by function-user-directory.tf and not required by "
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

    assert "USER_SPACE_BUCKET" in parsed, "the function-user-directory.tf parse found no variables at all"
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
    Deleting `LOGS_QUEUE_URL` from function-user-directory.tf left every other assertion here green while
    structured logging silently fell back to stdout — no queue, no logs, no failure.
    """
    missing = UNDECLARED_BY_CONFIG - _terraform_environment_variables()

    assert not missing, (
        f"function-user-directory.tf no longer sets {sorted(missing)}. `observability` reads both with "
        "`os.environ.get`, so losing one degrades in silence rather than raising — nothing "
        "else in this file or in production will tell you"
    )
