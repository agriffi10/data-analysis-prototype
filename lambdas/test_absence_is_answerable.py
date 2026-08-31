"""Every read that treats absence as an answer must run under a role that can SEE absence.

S3 tells a caller an object is missing only when that caller can list the bucket. To a caller
that cannot, the same missing object is ``AccessDenied``. So a ``except NoSuchKey: return None``
branch is not reachable on its own merits — it is reachable only if the execution role behind it
holds ``s3:ListBucket`` on that bucket, and the absence path fails as a fault otherwise.

**Measured live, twice, in opposite directions.** ``dat-prod-file-send-execution-role`` had no
``s3:ListBucket`` statement on the admin bucket at all, and on 2026-08-17 a send to a space that
was not registered raised ``AccessDenied`` out of ``cpcommon.registry.load`` instead of taking
the ``unknown_space`` refusal the caller was written around. In the other direction,
``dat-prod-notifications-writer-role`` holds exactly one list grant, conditioned on
``*/user_settings/notifications.json``, and its structured logs carry thirteen writes at
``notifications=1`` across eleven recipients — an inbox size that is only reachable through
``load_inbox``'s ``NoSuchKey`` branch. So a **conditioned** grant whose pattern covers the key is
sufficient, and having **no** statement is what breaks.

That pair is why the rule this file enforces is about the statement and its prefix rather than
about the condition's presence: scope the condition to the keys the site actually reads, and
never leave a plane with no statement at all.

**The population is derived, never listed.** A hand-kept list of absence sites rots into a list
of the sites somebody remembered, which is the failure this test exists to prevent — a review
samples, and what is wanted here is a sweep. So the sites are found by walking the AST of every
production module under ``lambdas/``, and the planes that reach the registry are found by walking
their imports. A new plane, or a new absence branch, joins the population by existing; it cannot
be added without either holding the grant or being dispositioned here on purpose.

**What the sweep can and cannot see, stated honestly.** It finds a read whose handler names an
absence code — including one hidden behind a module constant, a predicate helper, or a reader one
call below the ``try`` — and any handler that returns a value rather than only propagating. It
would NOT see absence decided through ``contextlib.suppress``, which is an ``ast.With`` and not a
``try``, and no site on this fleet is written that way today. That is the gap to widen if one
appears, rather than a reason to trust the table less than it says.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda tree the sweep walks.
  ABSENT_STRINGS: The error codes that mean "not there".
  ABSENT_STATUSES: The HTTP status that means the same thing, as an int.
  READ_OPS: The S3 calls whose absence answer is at issue.
  REGISTRY_PREFIX: The admin-bucket prefix every plane's registry record sits under.
  MEMBERSHIP_INDEX_PREFIX: The admin-bucket prefix the per-user membership index sits under.
    Read by the API's identity layer and written by the plane that owns membership, so BOTH
    roles need a covering list grant and neither may hold an unconditioned one.
  ADMIN_BUCKET_TOKEN: The template variable naming the admin bucket, unexpanded.
  USER_SPACE_BUCKET_TOKEN: The template variable naming the user-space bucket, unexpanded.
  REGISTRY_LIST_SID: The statement each plane names its registry list grant with.
  POLICY_FOR_PREFIX: Lambda-tree directory prefix to the policy of the role that runs it.
  ORCHESTRATOR_POLICY: The policy of the plane that owns the registry.
  TOLERATED_OPTIMISATION: A read whose failure costs a convenience, never a wrong answer.
  DISPOSITIONS: Every absence site the sweep finds, and why each is sound. Keyed
    ``path::function``.
"""

import ast
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
ABSENT_STRINGS = {"NoSuchKey", "NotFound", "404"}
ABSENT_STATUSES = {404}
READ_OPS = {"get_object", "head_object", "download_file", "download_fileobj"}
REGISTRY_PREFIX = "shared-spaces/"
MEMBERSHIP_INDEX_PREFIX = "memberships/"
REGISTRY_LIST_SID = "RegistryList"
ADMIN_BUCKET_TOKEN = "@{admin_bucket_arn}"
USER_SPACE_BUCKET_TOKEN = "@{bucket_arn}"

#: Lambda-tree directory prefix to the policy of the role that runs it. **Every deployed
#: directory that could reach the registry belongs here**, not only the six control planes: the
#: first version of this map held those six and nothing else, so adding
#: ``from cpcommon import registry`` to the DLQ drain — whose policy has no ``ListBucket`` at
#: all — left the suite green. An unmapped directory is now a hard failure rather than a silent
#: exemption, which is what makes the claim in this file's docstring true.
POLICY_FOR_PREFIX = {
    "archive": "archive/policies/execution.json.tftpl",
    "data-quality": "data-quality/policies/execution.json.tftpl",
    "file-ops": "file-ops/policies/execution.json.tftpl",
    "file-send": "file-send/policies/execution.json.tftpl",
    "table-builder": "table-builder/policies/execution.json.tftpl",
    "table-share": "table-share/policies/execution.json.tftpl",
    "shared-space": "shared-spaces/policies/orchestrator-permissions.json.tftpl",
    "control-plane-dlq-drain": "control-plane-dlq-drain/policies/drain-permissions.json.tftpl",
    "notifications-writer": "notifications/policies/writer-permissions.json.tftpl",
    "user-directory-build": "user-directory/policies/build-permissions.json.tftpl",
    "api": "api/policies/api-execution-policy.json.tftpl",
}

#: The orchestrator's own registry grant. The shared-spaces plane WRITES the registry and reads it
#: back through its own module rather than through ``cpcommon``, so it is invisible to the import
#: sweep — and deleting this statement left the whole suite green until it was named here.
ORCHESTRATOR_POLICY = "shared-spaces/policies/orchestrator-permissions.json.tftpl"

#: Reason codes. **Only the registry and portal-role grants below are checked against a policy
#: template**; every other entry is a reviewed claim about the code, recorded so a change that
#: falsifies one has to be argued with rather than passing silently. Do not read an entry here as
#: evidence a grant was verified — read it as evidence somebody decided.
LIST_GRANT = "list-grant"
FAIL_SAFE_CAS = "fail-safe-cas"
ABSENCE_IS_TERMINAL = "absence-is-terminal"
DENIAL_IS_ABSENT = "denial-is-absent"
TOLERATED_OPTIMISATION = "tolerated-optimisation"

DISPOSITIONS = {
    # Reads whose absence branch depends on the role holding a covering list grant.
    "lambdas/control-plane-common/cpcommon/registry.py::load": LIST_GRANT,
    "lambdas/shared-space-common/registry.py::_read": LIST_GRANT,
    "lambdas/file-ops-common/focommon/plan.py::_read": LIST_GRANT,
    "lambdas/notifications-writer/notifications_writer.py::load_inbox": LIST_GRANT,
    "lambdas/api/routes/feature_flags.py::feature_flags": LIST_GRANT,
    "lambdas/api/routes/user_directory.py::user_directory": LIST_GRANT,
    "lambdas/api/routes/objects_content.py::read_content": LIST_GRANT,
    "lambdas/api/routes/objects_content.py::_refuse_if_occupied": LIST_GRANT,
    "lambdas/api/routes/objects_head.py::metadata": LIST_GRANT,
    "lambdas/api/routes/objects_head.py::exists": LIST_GRANT,
    "lambdas/api/routes/objects_free_name.py::free_name": LIST_GRANT,
    "lambdas/api/routes/objects_presign.py::upload_url": LIST_GRANT,
    "lambdas/api/routes/objects_mutate.py::_perform_copy": LIST_GRANT,
    "lambdas/archive-common/arcommon/guard.py::_is_occupied": LIST_GRANT,
    "lambdas/data-quality-inspect-source/dq_inspect_source.py::_resolve_listing_prefix": LIST_GRANT,
    "lambdas/file-ops-check-destinations/file_ops_check_destinations.py::_occupied": LIST_GRANT,
    "lambdas/file-ops-common/focommon/delete.py::compare": LIST_GRANT,
    "lambdas/file-ops-inspect-source/file_ops_inspect_source.py::_head": LIST_GRANT,
    # A denial and an absence take the same branch, and the branch is safe either way: the write
    # that follows is create-only, so a present-but-unreadable object fails its precondition
    # rather than being overwritten.
    "lambdas/shared-space-common/cache.py::_read": DENIAL_IS_ABSENT,
    # Absence is proven by a 404 and by nothing else; a denial raises rather than taking the
    # branch. The archive role does hold the covering grant — its unconditioned SourceDataList on
    # the user-space and shared-space buckets — but that is not what makes this site safe: what
    # makes it safe is that an ambiguous answer cannot reach the caller's compose-a-fresh-receipt
    # fallback, which would lose the archive's own timestamp.
    "lambdas/archive-common/arcommon/receipt.py::read": ABSENCE_IS_TERMINAL,
    # A miss falls back to listing the same prefix, so the answer is the same either way. The
    # role can list that bucket — _find_result in the same function depends on it — and this is
    # Athena's own output location rather than a portal bucket.
    "lambdas/data-quality-assemble-report/dq_assemble_report.py::_result_rows": ABSENCE_IS_TERMINAL,
    # Swallow-and-default readers: a read failure becomes a benign value rather than an absence
    # claim, and the write that follows is a create-only or compare-and-swap one, so a
    # present-but-unreadable object fails its precondition instead of being overwritten. A denial
    # here costs a retry, never a wrong answer.
    "lambdas/data-quality-common/dqcommon/index_store.py::_read": FAIL_SAFE_CAS,
    "lambdas/data-quality-common/dqcommon/index_store.py::append": FAIL_SAFE_CAS,
    "lambdas/file-ops-common/focommon/lock.py::_read": FAIL_SAFE_CAS,
    "lambdas/log-sweep/log_sweep.py::_read_day": FAIL_SAFE_CAS,
    "lambdas/table-builder-common/tbcommon/table_lock.py::_read": FAIL_SAFE_CAS,
    # The record is an optimisation, not a fact, and both docstrings say so: losing it costs one
    # re-head or one skipped cross-check. A throttle is re-raised before the tolerance applies,
    # which is the only way it could cost anything.
    "lambdas/archive-common/arcommon/restore.py::read_recorded_count": TOLERATED_OPTIMISATION,
    "lambdas/archive-common/arcommon/retrieval.py::read_progress": TOLERATED_OPTIMISATION,
    # Not an absence branch at all: the only code it returns on is InvalidRange, which says the
    # object changed under a range read, not that it is gone. Swept because the handler returns;
    # kept here because a reader checking this table should not have to re-derive that.
    "lambdas/data-quality-byte-scan/dq_byte_scan.py::_scan_region": ABSENCE_IS_TERMINAL,
}


def _production_modules():
    """Every module the fleet actually deploys, excluding test scaffolding.

    Args:
      None.

    Returns:
      An iterator of paths.

    Raises:
      None.
    """
    for path in sorted(LAMBDAS.rglob("*.py")):
        if path.name.startswith("test_") or path.name in {"conftest.py", "fakes.py"}:
            continue
        yield path


def _constants(node):
    """Every literal appearing anywhere under a node.

    Args:
      node: The AST node to walk.

    Returns:
      The set of constant values.

    Raises:
      None.
    """
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant)}


def _means_absence(node):
    """Whether a node names an absence code, by literal or by the botocore exception.

    Args:
      node: The AST node to walk.

    Returns:
      True when it does.

    Raises:
      None.
    """
    values = _constants(node)
    if (values & ABSENT_STRINGS) or (values & ABSENT_STATUSES):
        return True
    return any(
        isinstance(n, ast.Attribute) and n.attr == "NoSuchKey" for n in ast.walk(node)
    )


def _s3_reads(node):
    """Every S3 read call under a node.

    Args:
      node: The AST node to walk.

    Returns:
      The matching Call nodes.

    Raises:
      None.
    """
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in READ_OPS
    ]


def _swallows_into_a_default(handlers):
    """Whether a read's handlers substitute a default instead of naming an absence code.

    ``except Exception: return None, None`` decides the object is absent without ever saying so,
    which is the same decision the code beside it makes with a ``NoSuchKey`` comparison — and it
    is the shape a matcher looking for absence codes cannot see. Four sites on this fleet are
    written that way, all of them locks or append-under-CAS readers, and it is the shape most
    likely to be written next, so it would otherwise be the gap this file leaves open.

    Any handler with a ``return`` in it counts, including one that also raises on another path.
    The narrower rule — return AND never raise — was the first version, and a review broke it in
    one line: a handler that re-raises a denial and returns a default otherwise names no absence
    code, so it was invisible while making exactly the decision this file exists to check.
    Widening costs one extra site to disposition, which is a good trade for closing the hole.

    Args:
      handlers: The ``except`` clauses of one try block.

    Returns:
      True when a failure is turned into a value.

    Raises:
      None.
    """
    for handler in handlers:
        if any(isinstance(n, ast.Return) for n in ast.walk(handler)):
            return True
    return False


def _parsed_tree(path):
    """Parses one module, or None when it does not parse.

    Args:
      path: The module path.

    Returns:
      The AST, or None.

    Raises:
      None.
    """
    try:
        return ast.parse(path.read_text())
    except SyntaxError:
        return None


def absence_sites():
    """Finds every S3 read whose failure handler decides the object is absent.

    Three kinds of indirection are resolved, and each one hid a real site while the sweep was
    being written: an absence code behind a module constant (``_ABSENT_CODES``), behind a
    predicate helper (``_is_absent``), and the read itself behind a local reader one call below
    the ``try`` that classifies its failure. Matching literals in the handler alone found eight
    of the twenty-one sites, which is why this walks names as well as constants.

    Args:
      None.

    Returns:
      A dict of ``"path::function"`` to the read operation's name.

    Raises:
      None.
    """
    trees = {p: t for p in _production_modules() if (t := _parsed_tree(p)) is not None}

    absence_names, reader_names = {}, {}
    for path, tree in trees.items():
        names, readers = set(), set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and _means_absence(node.value):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            if (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and _means_absence(node.value)
                and isinstance(node.target, ast.Name)
            ):
                names.add(node.target.id)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if _means_absence(node):
                    names.add(node.name)
                if _s3_reads(node):
                    readers.add(node.name)
        absence_names[path], reader_names[path] = names, readers

    everywhere = set().union(*absence_names.values()) if absence_names else set()

    found = {}
    for path, tree in trees.items():
        knows_absence = absence_names[path] | everywhere
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for block in [n for n in ast.walk(tree) if isinstance(n, ast.Try)]:
            direct = _s3_reads(block)
            called = {
                c.func.id if isinstance(c.func, ast.Name) else c.func.attr
                for c in ast.walk(block)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name | ast.Attribute)
            }
            if not direct and not (called & reader_names[path]):
                continue
            handlers = ast.Module(body=block.handlers, type_ignores=[])
            referenced = {n.id for n in ast.walk(handlers) if isinstance(n, ast.Name)}
            referenced |= {
                n.attr for n in ast.walk(handlers) if isinstance(n, ast.Attribute)
            }
            names_a_code = _means_absence(handlers) or bool(referenced & knows_absence)
            if not (names_a_code or _swallows_into_a_default(block.handlers)):
                continue
            owner = block
            while owner in parents and not isinstance(
                owner, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                owner = parents[owner]
            if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            key = f"{path.relative_to(ROOT)}::{owner.name}"
            found[key] = direct[0].func.attr if direct else "via-helper"
    return found


def registry_reading_planes():
    """Finds which planes reach ``cpcommon.registry``, counting attribute-style use.

    ``from cpcommon import registry as reg`` followed by ``reg.load(...)`` is invisible to a
    scan for the submodule path, so both spellings are counted. A plane that stops calling it
    drops out of the population on its own, and one that starts calling it joins.

    Args:
      None.

    Returns:
      The set of Lambda-tree directory names.

    Raises:
      None.
    """
    planes = set()
    for path in _production_modules():
        tree = _parsed_tree(path)
        if tree is None:
            continue
        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "cpcommon"
            ):
                aliases |= {
                    a.asname or a.name for a in node.names if a.name == "registry"
                }
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"cpcommon", "cpcommon.registry"}:
                        aliases.add(alias.asname or alias.name.split(".")[0])
        if not aliases:
            continue
        uses = any(
            isinstance(n, ast.Attribute)
            and (
                (isinstance(n.value, ast.Name) and n.value.id in aliases)
                or getattr(n.value, "attr", None) == "registry"
            )
            for n in ast.walk(tree)
        )
        if not uses:
            continue
        directory = path.relative_to(ROOT).parts[1]
        planes.add(directory)
    return planes


def policy_for(directory):
    """The policy template of the role that runs one Lambda directory, or None if unmapped.

    Args:
      directory: A directory name directly under ``lambdas/``.

    Returns:
      The path, or None when no prefix in ``POLICY_FOR_PREFIX`` matches.

    Raises:
      None.
    """
    for prefix in sorted(POLICY_FOR_PREFIX, key=len, reverse=True):
        if directory == prefix or directory.startswith(f"{prefix}-"):
            return ROOT / "infra" / "modules" / POLICY_FOR_PREFIX[prefix]
    return None


def _statements(policy_path):
    """Reads a policy template's statements, rewritten enough that JSON parsing survives.

    Two rewrites, and the second is not optional: the orchestrator's policy interpolates a
    pre-encoded list as a bare value (``"Resource": ${function_arns_json}``), which is not a JSON
    token at all. Quoting those first, then neutralising every remaining ``${``, leaves a
    document with the same statements and Sids.

    Args:
      policy_path: The ``.tftpl`` to read.

    Returns:
      The statement list.

    Raises:
      None.
    """
    raw = re.sub(r'(:\s+)\$\{([^}]+)\}', r'\1"@{\2}"', policy_path.read_text())
    return json.loads(raw.replace("${", "@{"))["Statement"]


def _as_list(value):
    """One value or many, always as a list.

    Args:
      value: A policy field IAM allows in either form.

    Returns:
      The value as a list.

    Raises:
      None.
    """
    return value if isinstance(value, list) else [value]


def _prefix_patterns(statement):
    """The ``s3:prefix`` patterns one statement is conditioned on, from any operator.

    Args:
      statement: One policy statement.

    Returns:
      The patterns, empty when the statement carries no ``s3:prefix`` condition at all.

    Raises:
      None.
    """
    return [
        pattern
        for operator in (statement.get("Condition") or {}).values()
        for key, value in operator.items()
        if key.lower() == "s3:prefix"
        for pattern in _as_list(value)
    ]


def _admin_bucket_list_grants(policy_path):
    """Every ``s3:ListBucket`` Allow naming the admin bucket, whatever its Sid.

    Args:
      policy_path: The policy template to read.

    Returns:
      The matching statements.

    Raises:
      None.
    """
    return [
        statement
        for statement in _statements(policy_path)
        if statement.get("Effect") == "Allow"
        and "s3:ListBucket" in _as_list(statement.get("Action"))
        and ADMIN_BUCKET_TOKEN in _as_list(statement.get("Resource"))
    ]


def list_grants_covering(policy_path, bucket_token, prefix):
    """Every ``s3:ListBucket`` Allow on ``bucket_token`` admitting a key under ``prefix``.

    **The bucket half is not decoration.** Every one of these roles holds an unconditioned list
    on its source buckets, so a check that only looked at the action and the condition would
    accept those and report a plane sound with no admin-bucket grant at all — which is exactly
    the production defect, passing. Found by planting it: removing a plane's registry grant left
    this green until the resource was compared too.

    An unconditioned grant admits every prefix. A conditioned one admits the prefix when one of
    its patterns matches it up to a trailing wildcard, which is the only shape this fleet writes.

    Args:
      policy_path: The policy template to read.
      bucket_token: The unexpanded template variable naming the bucket, as it appears after
        ``${`` is rewritten — for example ``@{admin_bucket_arn}``.
      prefix: The key prefix the site reads under.

    Returns:
      The matching statements.

    Raises:
      None.
    """
    matched = []
    for statement in _statements(policy_path):
        if statement.get("Effect") != "Allow":
            continue
        if "s3:ListBucket" not in _as_list(statement.get("Action")):
            continue
        if bucket_token not in _as_list(statement.get("Resource")):
            continue
        condition = statement.get("Condition")
        if not condition:
            matched.append(statement)
            continue
        patterns = []
        for operator in condition.values():
            for key, value in operator.items():
                if key.lower() == "s3:prefix":
                    patterns += _as_list(value)
        if any(prefix.startswith(p.rstrip("*")) for p in patterns):
            matched.append(statement)
    return matched


def test_every_absence_site_in_the_tree_is_dispositioned():
    """The swept population and the disposition table agree exactly, in both directions.

    An undispositioned site is a new absence branch nobody has decided about, and a
    dispositioned site the sweep no longer finds is a stale entry that would otherwise keep
    vouching for code that has moved.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: On a site in one set and not the other.
    """
    found = set(absence_sites())
    declared = set(DISPOSITIONS)

    assert found - declared == set(), (
        "absence branches with no disposition — decide whether the role behind each can see "
        f"absence, then record it: {sorted(found - declared)}"
    )
    assert declared - found == set(), (
        f"dispositions naming sites the sweep no longer finds: {sorted(declared - found)}"
    )


def test_the_sweep_finds_the_sites_it_was_written_against():
    """The sweep is not vacuous: it still finds the two sites that motivated it.

    A sweep that silently stops matching would let the agreement test above pass with an empty
    population on both sides, which is the one way this file could go green while checking
    nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either site is missing, or the population collapses.
    """
    found = absence_sites()

    assert "lambdas/control-plane-common/cpcommon/registry.py::load" in found
    assert "lambdas/shared-space-common/registry.py::_read" in found
    assert len(found) >= 20


def test_every_plane_reading_the_registry_can_see_a_space_absent():
    """Each plane that calls ``cpcommon.registry`` holds a list grant covering the registry.

    This is the defect that reached production. ``registry.load`` returns None for "no such
    space" and every plane's authorize step is written around that, but the read is a
    ``GetObject`` on a key that is absent precisely when the answer matters — so without a list
    grant on the admin bucket the refusal arrives as an unhandled ``AccessDenied``. Measured on
    2026-08-17: a send naming an unregistered space raised out of ``registry.load`` under
    ``dat-prod-file-send-execution-role``, which had no such statement.

    The plane list is derived from the imports, so a new plane that reads the registry is held
    to this without anybody remembering to add it here.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane reads the registry without a covering grant.
    """
    directories = registry_reading_planes()
    assert directories, (
        "nothing appears to read the registry — the import sweep has stopped working"
    )

    unmapped = sorted(d for d in directories if policy_for(d) is None)
    assert unmapped == [], (
        f"these deployed directories read the registry and this file cannot say which role runs "
        f"them: {unmapped}. Add each to POLICY_FOR_PREFIX — an unmapped directory would "
        "otherwise be exempted from the grant check silently, which is the whole failure this "
        "test exists to prevent."
    )

    for directory in sorted(directories):
        policy = policy_for(directory)
        grants = list_grants_covering(policy, ADMIN_BUCKET_TOKEN, REGISTRY_PREFIX)
        assert grants, (
            f"{directory} reads the shared-space registry but the role running it holds no "
            f"s3:ListBucket grant covering {REGISTRY_PREFIX} in {policy.name} — a space that is "
            "not registered will raise AccessDenied instead of taking the unknown-space refusal"
        )


def test_the_registry_list_grant_stays_scoped_to_the_registry():
    """The grant is conditioned, and its condition names the registry prefix.

    An unconditioned list on the admin bucket would let a plane enumerate every shared space's
    name and then every roster — the disclosure this project declines by publishing no
    shared-space directory at all. The space name is the only thing gating that read, so the
    grant that makes absence visible must not also make the names visible.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane's registry grant is unconditioned or names a wider prefix.
    """
    for directory in sorted(registry_reading_planes()):
        policy = policy_for(directory)

        # EVERY admin-bucket list grant, not just the one named below. A second, unconditioned
        # statement under any other Sid would satisfy a Sid-filtered check while handing the role
        # exactly what this test exists to withhold.
        for statement in _admin_bucket_list_grants(policy):
            assert statement.get("Condition"), (
                f"{statement.get('Sid')!r} in {policy.name} lists the whole admin bucket. That "
                "hands the role every shared space's name and then every roster, which is the "
                "disclosure the project declines by publishing no shared-space directory."
            )

        named = [s for s in _statements(policy) if s.get("Sid") == REGISTRY_LIST_SID]
        assert len(named) == 1, f"{directory} should carry exactly one {REGISTRY_LIST_SID}"

        patterns = [
            p
            for operator in (named[0].get("Condition") or {}).values()
            for key, value in operator.items()
            if key.lower() == "s3:prefix"
            for p in _as_list(value)
        ]
        assert patterns == [f"{REGISTRY_PREFIX}*"], (
            f"{directory}'s registry list grant should admit {REGISTRY_PREFIX}* and nothing wider, "
            f"got {patterns}"
        )


@pytest.mark.parametrize("prefix", ["_directory/", "_config/"])
def test_the_portal_role_can_see_its_shared_documents_absent(prefix):
    """The two documents that belong to no user are listable by the role that reads them.

    Both routes run on the user plane, so they read through the caller's own assumed portal
    role, whose other list grant is conditioned on the caller's own prefix — which neither of
    these keys is under. Without this the absent-document branches are unreachable: the username
    directory would raise instead of answering an empty list, and the flag document would raise
    instead of answering NotFound.

    Args:
      prefix: The document prefix under test.

    Returns:
      None.

    Raises:
      AssertionError: If the portal role cannot list that prefix.
    """
    policy = (
        ROOT
        / "infra"
        / "modules"
        / "data"
        / "policies"
        / "portal-role-permissions.json.tftpl"
    )
    assert list_grants_covering(policy, USER_SPACE_BUCKET_TOKEN, prefix), (
        f"the portal role reads {prefix} but cannot list it, so a missing document answers "
        "AccessDenied rather than being reported absent"
    )


def test_the_plane_that_owns_the_registry_can_read_it_back_absent():
    """The orchestrator's own registry grant, which no other test in this file reaches.

    The shared-spaces plane writes the registry and reads it back through
    ``shared-space-common/registry.py`` rather than through ``cpcommon``, so the import sweep
    above cannot see it — and its policy is the orchestrator's, not an ``execution.json.tftpl``.
    Deleting ``AdminRegistryList`` therefore left the entire suite green while reintroducing this
    file's own defect on the one plane that owns the data.

    ``_read`` returns ``(None, None)`` for a space that is not there, and ``reserve``'s collision
    resolution branches on that None to tell a vanished reservation from a taken name.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the orchestrator cannot list the registry prefix, or can list wider.
    """
    policy = ROOT / "infra" / "modules" / ORCHESTRATOR_POLICY
    assert policy.exists(), f"{ORCHESTRATOR_POLICY} has moved — this test has no subject"

    grants = list_grants_covering(policy, ADMIN_BUCKET_TOKEN, REGISTRY_PREFIX)
    assert grants, (
        "the shared-space orchestrator holds no s3:ListBucket grant covering "
        f"{REGISTRY_PREFIX}, so registry._read cannot tell a missing record from a denial — and "
        "reserve's collision resolution branches on exactly that answer"
    )

    for statement in _admin_bucket_list_grants(policy):
        assert statement.get("Condition"), (
            f"{statement.get('Sid')!r} lists the whole admin bucket. The orchestrator holds the "
            "registry's object grants, so a bucket-wide list adds nothing it needs and widens "
            "what a compromised verb could enumerate."
        )


def test_both_roles_that_touch_the_membership_index_can_see_it_absent():
    """The index read and the index write each need a list grant, on different roles.

    **An absent index is the correct answer, not a fault**, and it is the answer for every user
    who has never been added to a shared space. S3 says ``NoSuchKey`` only to a caller holding
    ``s3:ListBucket``; to a caller without it the same missing object is ``AccessDenied``. So a
    read-only grant would turn the commonest state of this object into a server fault on the
    credential-minting path — every such user refused, for a reason no user can act on.

    Both roles need it, and each fails differently without it. On the API's execution role the
    absence IS the answer: the identity layer refuses a caller who is correctly a member of
    nothing. On the orchestrator the absence is the first step of a create-if-absent write, and
    ``cas_mutate`` runs its read outside the retry guard — so the fault propagates on the first
    attempt rather than being retried, and the plane's contract is that an index-write failure
    fails the run.

    The condition is asserted by its PATTERN rather than by its presence. ``s3:prefix: "*"`` is a
    bucket-wide list wearing a condition, and a presence check passes it — which is how the role
    every request runs through would come to hold every shared space's name and then every
    roster. Every admin-bucket list statement is checked, not only the named one: a second
    statement under any other Sid satisfies a Sid-filtered check while handing over exactly what
    this withholds.

    The object statement is pinned too, and for the same reason one level down: widened to the
    whole bucket it reaches every other plane's registry record and lock, under a Sid that still
    says memberships.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either role cannot list the membership prefix, or can reach wider.
    """
    roles = {
        "the API's execution role": ROOT / "infra" / "modules" / POLICY_FOR_PREFIX["api"],
        "the shared-space orchestrator": ROOT / "infra" / "modules" / ORCHESTRATOR_POLICY,
    }
    for who, policy in roles.items():
        assert policy.exists(), f"{policy} has moved — this test has no subject for {who}"
        assert list_grants_covering(policy, ADMIN_BUCKET_TOKEN, MEMBERSHIP_INDEX_PREFIX), (
            f"{who} touches {MEMBERSHIP_INDEX_PREFIX} but holds no s3:ListBucket grant covering "
            "it, so an absent index answers AccessDenied instead of being reported absent"
        )
        for statement in _admin_bucket_list_grants(policy):
            patterns = _prefix_patterns(statement)
            assert patterns, (
                f"{statement.get('Sid')!r} in {policy.name} lists the whole admin bucket for "
                f"{who}. That hands it every shared space's name and then every roster."
            )
            assert all(pattern.rstrip("*") for pattern in patterns), (
                f"{statement.get('Sid')!r} in {policy.name} is conditioned on {patterns}, which "
                "admits every prefix — a bucket-wide list wearing a condition"
            )

        objects = [
            statement
            for statement in _statements(policy)
            if any(
                MEMBERSHIP_INDEX_PREFIX in resource
                for resource in _as_list(statement.get("Resource"))
            )
        ]
        assert len(objects) == 1, (
            f"{who} should reach {MEMBERSHIP_INDEX_PREFIX} through exactly one object statement"
        )
        assert _as_list(objects[0]["Resource"]) == [
            f"{ADMIN_BUCKET_TOKEN}/{MEMBERSHIP_INDEX_PREFIX}*"
        ], (
            f"{who}'s membership-index objects statement names {objects[0]['Resource']} — "
            "widening it past the prefix reaches every other plane's registry record and lock "
            "through a statement whose Sid still says memberships"
        )
        assert "s3:DeleteObject" not in _as_list(objects[0]["Action"]), (
            f"{who} may not delete a membership index — an emptied index is written empty, and a "
            "deleted one is indistinguishable from a user who was never a member"
        )
