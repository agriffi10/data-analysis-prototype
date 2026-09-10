"""The results-conversion plane's own invariants: what its layer, its role and its rule hold.

Each test here is a fence, not a behaviour: the domain layer holds no algorithm, the role
holds one write and no query start, the timeout door is the event one, the refused-destination
set contains the picker's by rule rather than equalling it by accident, and every cap is
computed rather than typed.
"""

import ast
import json
import os
import pathlib
import re
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "file-ops-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon import app_managed
from cpcommon import config as cp_config
from cpcommon import messages as cpmessages
from cpcommon.app_managed import app_managed_prefix
from rccommon import config, messages, reasons

_MODULE = _ROOT / "infra" / "modules" / "results-conversion"
_POLICY = _MODULE / "policies" / "execution.json.tftpl"
_ASL = _MODULE / "state-machine.asl.json.tftpl"
_LOCALS = _MODULE / "locals.tf"
_DOOR = _HERE.parent / "results-conversion-notify-failure" / "rc_notify_failure.py"

_ALGORITHM_NAMES = ("cas", "lock", "parse_sqs", "resolve")


def _render_policy() -> dict:
    """Renders the execution policy with every placeholder stubbed to a recognisable literal."""
    raw = _POLICY.read_text(encoding="utf-8")
    return json.loads(re.sub(r"\$\{([^}]+)\}", r"@\1@", raw))


def _actions(statement) -> set[str]:
    action = statement.get("Action")
    return set(action) if isinstance(action, list) else {action}


def _resources(statement) -> list[str]:
    resource = statement.get("Resource")
    return list(resource) if isinstance(resource, list) else [resource]


def test_the_domain_layer_defines_no_algorithm_of_its_own():
    """rccommon holds wording and rules; every algorithm is imported from cpcommon.

    A CAS loop, a lock, a queue parser or a message resolver written here would be a second
    copy of one the shared layer already owns, drifting from it silently.
    """
    offenders = []
    for path in sorted((_HERE / "rccommon").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if any(name in lowered for name in _ALGORITHM_NAMES):
                    offenders.append(f"{path.name}::{node.name}")
    assert offenders == [], f"rccommon defines an algorithm the shared layer owns: {offenders}"


def test_importing_any_module_in_the_layer_registers_the_reason_codes():
    """`TerminalError` validates its reason against the registered table at the RAISE site, and
    importing `messages` is what registers it — so a module that raises without it raises
    ValueError instead, and only when nothing else in the process imported `messages` first.

    Run in a SUBPROCESS, one module at a time, because this process has already imported the
    whole layer: an in-process check would pass on the very import order it exists to remove.
    `paths` is the module that had the bug — it raises ten times and imported nothing.
    """
    import subprocess

    for module in ("paths", "authz", "types", "config", "links"):
        probe = (
            f"import sys; sys.path[:0] = [{str(_HERE)!r}, {str(_HERE.parent / 'control-plane-common')!r}];"
            f" from rccommon import {module};"
            " from cpcommon.messages import is_known_reason;"
            " from rccommon.reasons import REASONS;"
            " assert all(is_known_reason(r) for r in REASONS), 'codes unregistered'"
        )
        finished = subprocess.run(  # noqa: S603
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env={**os.environ, "ADMIN_BUCKET": "a", "USER_SPACE_BUCKET": "u", "SHARED_SPACE_BUCKET": "s"},
            check=False,
        )
        assert finished.returncode == 0, f"importing rccommon.{module} alone: {finished.stderr}"


def test_the_layer_sweep_sees_the_functions_it_reads():
    """The positive control for the sweep above: it finds this plane's real functions."""
    found = {
        node.name
        for path in (_HERE / "rccommon").glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert {"authorize_destination", "destination_key", "failure_message"} <= found


def test_the_execution_role_writes_files_and_starts_no_query():
    """It writes exactly one kind of thing and reads the rest.

    The write grant arrived with the verb that writes, and it is the ONLY new power: an
    execution is still read from Athena's metadata and never started, and the timeout door
    still reads its own event rather than the Step Functions API.
    """
    allowed, writes = set(), []
    for statement in _render_policy()["Statement"]:
        if statement["Effect"] != "Allow":
            continue
        allowed |= _actions(statement)
        if "s3:PutObject" in _actions(statement):
            writes.append(statement)
    assert "athena:StartQueryExecution" not in allowed, "the input is a result object, never a query"
    assert "states:DescribeExecution" not in allowed, "the timeout door reads the event, not the API"
    assert {"athena:GetQueryExecution", "athena:GetQueryResults", "s3:GetObject"} <= allowed
    assert len(writes) == 1, "the write grant is one statement, so the Deny below has one thing to bound"
    assert _actions(writes[0]) == {"s3:PutObject", "s3:AbortMultipartUpload"}, (
        "the abort rides with the put: an incomplete multipart holds storage indefinitely and "
        "is invisible in a listing"
    )
    assert set(_resources(writes[0])) == {
        "@user_space_bucket_arn@/*",
        "@shared_space_bucket_arn@/*",
    }, "the write is scoped to the two space buckets and nothing else"


def test_the_deny_names_every_refused_destination_in_both_buckets():
    """The validator's refusal and the role's Deny are one rule stated twice, held equal here.

    The expected Resource is BUILT from ``app_managed_prefix`` rather than spelled ``{folder}/``,
    because two of these destinations moved under ``system_settings/`` and a literal here would
    have had to be edited to agree — which is the edit that makes a mirror test agree with a rule
    nobody re-read. Built, it follows the Deny wherever the folder goes.
    """
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    assert len(denies) == 1 and _actions(denies[0]) == {"s3:PutObject"}
    denied = set(_resources(denies[0]))
    for bucket in ("@user_space_bucket_arn@", "@shared_space_bucket_arn@"):
        for folder in config.PROTECTED_DESTINATIONS:
            expected = f"{bucket}/*/{app_managed_prefix('', folder)}*"
            assert expected in denied, f"{folder} is refused but not denied in {bucket}"


def test_the_deny_names_the_system_settings_prefix_itself_in_both_buckets():
    """The whole new prefix is denied, not only the three folders moving into it.

    ``system_settings`` has since joined ``PROTECTED_DESTINATIONS``, so the loop above now
    demands this shape through the list — which is exactly the condition this test was written
    to survive. It stays because it says the bare prefix OUTRIGHT, which is the fact the
    per-folder siblings do not carry: the loop would still pass if the entry were removed from
    the list and the resource removed with it.
    """
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    denied = set(_resources(denies[0]))
    for bucket in ("@user_space_bucket_arn@", "@shared_space_bucket_arn@"):
        assert f"{bucket}/*/system_settings/*" in denied, f"system_settings itself is writable in {bucket}"


def test_no_denied_resource_is_wide_enough_to_cover_a_whole_bucket():
    """Every Deny resource names at least one LITERAL segment, so none of them is bucket-wide.

    The two assertions above are both membership tests, so neither can see a resource that was
    ADDED — measured by planting ``${user_space_bucket_arn}/*`` into this statement, which left
    every template guard in the repository green. That blind spot costs more now the statement
    carries ``*/system_settings/*``, a strict superset of three siblings beside it: widening one
    of these is a one-character edit.

    The direction that bites is over-width, not under, and it now bites for real: the converter
    HAS its write grant, so a bucket-wide ``s3:PutObject`` Deny would refuse the plane's own
    output rather than sitting harmlessly over a role that writes nothing. This was written when
    the grant was still a spec away, which is when a guard against it is cheapest to add.

    A segment carrying ``*`` or ``?`` does not count, because both are S3 wildcards and the
    widening this guards against is a one-character edit — ``/*`` to ``/?*`` matches every key of
    length one or more while still reading as a path. The rule assumes an OBJECT-level Deny: the
    statement's actions are pinned to ``s3:PutObject`` above, and a bucket-level action added
    later would legitimately name the bucket ARN alone and redden this.
    """
    denies = [s for s in _render_policy()["Statement"] if s["Effect"] == "Deny"]
    for resource in _resources(denies[0]):
        segments = resource.split("/")[1:]
        literal = [seg for seg in segments if seg and not set(seg) & {"*", "?"}]
        assert literal, f"{resource} denies more than a folder"


def test_the_refused_set_is_a_superset_of_the_pickers_and_of_the_shared_enumerator():
    """This plane refuses everything the browser's picker never offers, every folder the shared
    owner enumerates, AND anything the execution role denies that neither of those two names.

    It used to be an equality with the picker, and the equality contradicted the rule
    `rccommon.paths` states in its own docstring: the validator mirrors the execution role's
    DENY, not the picker. The role denies `*/system_settings/*` in both buckets, and the
    converter now HOLDS a write grant, so a destination inside it would reach the user as a bare
    AccessDenied instead of a named refusal.

    The direction that matters is kept: nothing the picker locks may be accepted here. What is
    given up is the reverse, and deliberately, because the picker is a browser affordance and
    IAM is the thing that actually refuses.

    **The two sets coincide again, and that is a coincidence rather than the rule.** SPEC-219
    added `system_settings` to the picker as well, so the difference this used to carry is now
    empty — but the assertion stays an inclusion in one direction and an enumeration of the
    difference in the other, because the moment they diverge again is the moment somebody has to
    make the argument for the new member. Restoring an equality here would delete the question.
    """
    from focommon.config import PICKER_LOCKED_FOLDERS

    refused = set(config.PROTECTED_DESTINATIONS)
    assert set(PICKER_LOCKED_FOLDERS) <= refused, (
        "a folder the picker never offers is accepted here, so the plane can be driven into a "
        "destination the browser refuses to name"
    )
    assert "system_settings" in refused
    assert refused - set(PICKER_LOCKED_FOLDERS) == set(), (
        "the superset has grown a member the picker does not lock; every one of them is a "
        "refusal the browser never explains, so each needs the argument system_settings had "
        "before the picker took it on"
    )
    assert set(app_managed.SPACE_FOLDERS) <= set(config.PROTECTED_DESTINATIONS)
    assert set(app_managed.SPACE_FOLDERS) == {
        app_managed.ATHENA_RESULTS_FOLDER,
        app_managed.RECEIPT_FOLDER,
        app_managed.SHARED_TABLES_FOLDER,
    }


def test_a_protected_folder_is_refused_at_its_home_and_the_name_it_left_is_not():
    """This list mirrors the execution role's DENY, so it follows the folder and lets go of the name.

    **It was the last bare-name mirror in the fleet, and it was missed.** Its second arm tested
    ``name in folders``, which kept refusing ``alice/athenaresults/`` after the Deny stopped naming
    it — over-refusal, so it failed safe and nothing reported it. Worse than the usual case,
    because the same change released those folders from the browser's picker: *Save results* offered
    a destination this plane then refused. Both arms now resolve through the builders.

    ``user_settings`` did NOT move, so its row stays at depth one — which is what stops a repair
    from over-correcting and handing the whole list the new prefix.
    """
    from rccommon.paths import protected_refusal

    assert protected_refusal("alice", "alice/system_settings/athenaresults/x.csv") == "athenaresults"
    assert protected_refusal("alice", "alice/system_settings/notes.csv") == "system_settings"
    assert protected_refusal("alice", "alice/user_settings/x.json") == "user_settings"
    assert protected_refusal("alice", "alice/reports/mine.csv") is None

    # The names the two moving folders left — ordinary destinations now, at any depth.
    assert protected_refusal("alice", "alice/athenaresults/x.csv") is None
    assert protected_refusal("alice", "alice/archive/x.csv") is None
    assert protected_refusal("finance", "finance/reports/archive/out.xlsx") is None


def test_every_reason_is_worded_and_every_wording_is_a_reason():
    """The closed set and the wording table agree, base codes resolving through the base table."""
    for reason in reasons.REASONS:
        assert cpmessages.is_known_reason(reason), f"{reason} is raised but never registered"
        assert "something went wrong" not in messages.failure_message(reason) or reason == reasons.UNEXPECTED
    assert set(messages._BODIES) <= reasons.REASONS
    assert reasons.REASONS - set(messages._BODIES) == {reasons.MALFORMED_EVENT, reasons.FORBIDDEN}


def test_every_code_any_verb_on_this_plane_can_raise_is_registered_and_worded():
    """FR-006's criterion is about what the PLANE can return, so the population is derived from
    every verb rather than from a hand-written list beside the wording.

    The equality this replaces held `messages._BODIES` against `reasons.REASONS` — two
    hand-written tables in one package, which agree with each other and say nothing about
    whether the code a refusal actually carries was ever worded.

    It is derived from EVERY verb directory rather than from the converter alone, and that is
    the structural half. Scoped to one verb, a code that MOVES between verbs falls out of the
    population silently — which is exactly what happened when the column ceiling moved from the
    converter to describe-results: the enumeration stopped covering it, and its wording could
    then be broken without reddening anything. A directory glob cannot go quiet that way.
    """
    verbs = sorted(_HERE.parent.glob("results-conversion-*/rc_*.py"))
    assert len(verbs) >= 5, f"the verb sweep found only {[v.name for v in verbs]}"
    verb_tree = ast.parse(b"\n".join(v.read_bytes() for v in verbs).decode("utf-8"))
    # The verb's own vocabulary is not the whole of it: `unsupported_column_type` is raised by
    # `rccommon.types` and re-wrapped here, so a collector reading only this file under-counts
    # by one and would call the missing code a change in the verb. The modules it walks are
    # DERIVED from the verb's own `from rccommon import ...`, so a layer module that starts
    # refusing joins this population by being imported rather than by being remembered.
    imported = {
        alias.name
        for node in ast.walk(verb_tree)
        if isinstance(node, ast.ImportFrom) and node.module == "rccommon"
        for alias in node.names
    }
    assert "types" in imported, "the verb no longer imports the type table; re-derive this sweep"
    trees = [
        verb_tree,
        *(
            ast.parse((_HERE / "rccommon" / f"{name}.py").read_text(encoding="utf-8"))
            for name in sorted(imported)
            if (_HERE / "rccommon" / f"{name}.py").exists() and name != "reasons"
        ),
    ]
    # Collected from the FIRST ARGUMENT of a refusal's construction, not from every mention of
    # the module. `rccommon.notify` names `reasons.UNEXPECTED` while RENDERING the generic
    # sentence for a fault the decorator caught — a code the machine can carry but not one the
    # verb ever refuses with, and a collector counting mentions would put it in this list.
    referenced = {
        node.args[0].attr
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("_Refusal", "TerminalError")
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "reasons"
    }
    assert referenced, "the collector found no refusal construction, so the equality is vacuous"
    codes = {getattr(reasons, name) for name in referenced}
    assert codes == {
        reasons.RESULTS_UNREADABLE,
        reasons.UNSUPPORTED_COLUMN_TYPE,
        reasons.EXCEL_ROW_LIMIT,
        reasons.DESTINATION_OCCUPIED,
        reasons.TOO_MANY_COLUMNS,
        reasons.INVALID_COLUMN_NAME,
        reasons.DUPLICATE_COLUMN,
        reasons.RESULTS_TOO_LARGE,
        reasons.EXECUTION_NOT_FOUND,
        reasons.EXECUTION_NOT_FINISHED,
        reasons.EXECUTION_FAILED,
        reasons.NO_RESULT_SET,
        reasons.PROTECTED_LOCATION,
        reasons.INVALID_REQUEST,
        reasons.FORBIDDEN,
    }, f"the plane's refusal vocabulary has changed: {sorted(codes)}"
    for code in codes:
        assert cpmessages.is_known_reason(code), f"{code} is returned but never registered"
        rendered = messages.failure_message(
            code, {"format": "xlsx", "filename": "q1.xlsx", "count": 3, "column": "amount"}
        )
        assert "something went wrong" not in rendered, f"{code} reaches the user unworded"
        if code == reasons.FORBIDDEN:
            assert rendered == "You don't have access to save results there."
            continue
        assert "as Excel" in rendered, f"{code} does not name the format"
        assert "{" not in rendered, f"{code} left a marker unfilled"

    # Naming the FILE is FR-006's criterion and it is about the CONVERT verb's codes, so it is
    # asserted over those rather than over the whole plane — SPEC-221's own refusals predate it
    # and widening them is that spec's change, not this one's. The assertion used to end
    # `or "{" not in rendered`, a disjunct any sentence mentioning no file satisfies, which is
    # how three of the four held while the criterion did not.
    for code in NAMES_THE_FILE:
        assert code in codes, f"{code} is worded but no verb raises it any more"
        rendered = messages.failure_message(code, {"format": "xlsx", "filename": "q1.xlsx", "count": 3, "column": "a"})
        assert "q1.xlsx" in rendered, f"{code} does not name the file the user chose"


#: The golden vector the browser's half of this test reads too, in
#: `apps/portal/src/features/notifications/resultsConversionLink.test.ts`. A prefix carrying
#: every character that would truncate a query string, plus a space. Written out on both sides
#: rather than shared through a file: a Python test asserting its own model of URLSearchParams
#: proves nothing about the parser that actually resolves the link.
#: The refusals FR-006 requires to name the file the user chose — the convert verb's own, plus
#: the width refusal that moved out of it into describe-results and must not lose the property
#: by moving. SPEC-221's refusals are deliberately not here: they predate the criterion.
NAMES_THE_FILE = (
    "results_unreadable",
    "unsupported_column_type",
    "excel_row_limit",
    "destination_occupied",
    "too_many_columns",
    "protected_location",
)

GOLDEN_LINK_PREFIX = "finance/a b&c?d#e/"
GOLDEN_LINK = "/files?space=finance&prefix=finance/a%20b%26c%3Fd%23e/"

#: The row-limit refusal, written out in full and duplicated in the browser suite.
#:
#: The browser half is `apps/portal/src/features/notifications/resultsConversionNotification.test.tsx`.
#: The spec requires this one sentence checked END TO END — that the wording registered on the
#: plane is the wording a user reads — and this table is a Python literal no vitest run can
#: import. So it is written on both sides on the `GOLDEN_LINK` precedent above: deliberately
#: duplicated rather than shared through a fixture file, since a file both halves read would go
#: stale together. Change one and the other fails.
GOLDEN_ROW_LIMIT = (
    "Couldn't save the query results as Excel: the results have 1,400,000 rows, which is more "
    'than a spreadsheet can hold, so "q1.xlsx" was not written. Please save them as Parquet '
    "instead, or narrow the query."
)


#: Step Functions' ceiling on a task state's input or output, in bytes.
STATE_LIMIT_BYTES = cp_config.STATE_PAYLOAD_LIMIT_BYTES

#: The widest column entry describe-results can emit: a long name, plus the two fields only a
#: decimal carries. Serialised the way the Lambda runtime returns a payload.
WIDEST_COLUMN = {"name": "c" * 40, "type": "decimal", "precision": 38, "scale": 10}


def test_the_column_cap_is_bounded_by_the_state_it_was_derived_from():
    """The cap is a number, and a number needs a two-sided bound or it is a preference.

    A test that builds its fixture from `MAX_RESULT_COLUMNS` moves with the constant and cannot
    see it shrink — halving it to 750 passed a full suite. So both ends are derived here:

    ABOVE, by measuring. The columns ride on a Step Functions state capped at 256 KB, and the
    widest entry the describer can emit is a long name plus a decimal's precision and scale.
    The cap must leave real headroom against that, not merely fit, because the entry can grow
    without anyone thinking about this number.

    BELOW, by what the platform already accepts. A cap under a thousand columns would refuse
    result sets that are ordinary — the data-quality plane profiles up to 200 columns and a
    query can reasonably select several times that — and a cap that refuses legitimate work
    causes the damage it exists to prevent.
    """
    import json

    entry_bytes = len(json.dumps(WIDEST_COLUMN)) + 1
    worst_case = config.MAX_RESULT_COLUMNS * entry_bytes
    assert worst_case < STATE_LIMIT_BYTES * 0.6, (
        f"{config.MAX_RESULT_COLUMNS} of the widest column entry is {worst_case} bytes, over "
        f"60% of the {STATE_LIMIT_BYTES}-byte state limit — the headroom is gone"
    )
    assert config.MAX_RESULT_COLUMNS >= 1_000, (
        "a cap under a thousand columns refuses result sets users legitimately have"
    )
    assert config.MAX_RESULT_COLUMNS * entry_bytes * 2 > STATE_LIMIT_BYTES * 0.6, (
        "the cap is so far under its own bound that it is a preference rather than a derivation"
    )


def test_the_link_encodes_every_component_and_puts_the_space_first():
    """Two rules, both learned from links that resolved somewhere else.

    The prefix is the FULL key including the space root, because the file browser discards a
    `?prefix=` that does not start with the resolved space's root and lands the user at their
    space root with no idea why. And `space` comes FIRST, because the notification row's own
    feature gate tests for the literal `?space=`.

    Encoding the space NAME as well is a deliberate divergence from file-ops' notifier, which
    interpolates it raw behind a shape check. The shape check is kept too: a name the browser
    could not resolve should produce no link rather than an encoded broken one.
    """
    from rccommon import links

    assert links.destination_link("shared", "finance", f"{GOLDEN_LINK_PREFIX}q1.parquet") == GOLDEN_LINK
    assert links.destination_link("personal", "alice", "alice/out/q1.parquet") == "/files?prefix=alice/out/"
    assert links.destination_link("shared", "../etc", "x/q1.parquet") is None
    assert links.destination_link("personal", "alice", "bob/secret/q1.parquet") == "/files?prefix=alice/", (
        "a key outside the space root falls back to the root rather than linking into another"
    )


#: The browser file holding the other half of the row-limit golden.
BROWSER_GOLDEN_FILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "apps"
    / "portal"
    / "src"
    / "features"
    / "notifications"
    / "resultsConversionNotification.test.tsx"
)


def _browser_golden() -> str:
    """The VALUE of the browser half's GOLDEN_ROW_LIMIT, read out of its source.

    The value, not the file. Searching the whole file for the sentence passes when the sentence
    sits in a comment above a constant that says something else — a review planted exactly that
    and both suites stayed green, which is the drift this gate exists to catch wearing the shape
    of a passing gate. So the declaration is bounded and only its template literal is read.

    Returns:
      The sentence the browser file actually assigns.

    Raises:
      AssertionError: If the declaration is missing or is not a single template literal. Both are
        failures of this gate's own reading rather than of the sentence, and the messages say so.
    """
    source = BROWSER_GOLDEN_FILE.read_text(encoding="utf-8")
    marker = "const GOLDEN_ROW_LIMIT ="
    assert marker in source, f"{BROWSER_GOLDEN_FILE.name} no longer declares GOLDEN_ROW_LIMIT"
    declaration = source.split(marker, 1)[1].split(";", 1)[0]
    quoted = declaration.split("`")
    assert len(quoted) == 3, (
        "GOLDEN_ROW_LIMIT must be exactly ONE template literal, so this gate reads a value rather "
        "than re-implementing TypeScript string concatenation"
    )
    return quoted[1]


def test_the_row_limit_refusal_is_the_sentence_the_browser_renders():
    """The cross-language gate the two-language golden actually needs.

    The Python half alone only proves the producer agrees with itself, and the browser half
    alone proves that `NotificationRow` renders whatever `message` it is handed — it feeds the
    literal in and reads it back, which holds for any string. Neither can see the other drift.

    This closes it from the side that can: the sentence is produced for real here, and compared
    against the literal read out of the browser's own source. Change the wording, the Python
    golden, or the browser copy, and this fails.
    """
    produced = messages.failure_message(
        reasons.EXCEL_ROW_LIMIT,
        {"format": "xlsx", "filename": "q1.xlsx", "count": "1,400,000"},
    )
    assert produced == GOLDEN_ROW_LIMIT
    assert produced == _browser_golden(), (
        "the browser's copy of the row-limit sentence disagrees with the plane's wording — if the "
        "sentences read the same, check the browser copy is still ONE template literal, which is "
        "the layout this gate reads rather than a second string parser"
    )


def test_the_wording_names_the_format_and_the_file_where_they_are_known():
    sentence = messages.failure_message(
        reasons.PROTECTED_LOCATION, {"format": "xlsx", "filename": "q1.xlsx"}
    )
    assert sentence.startswith("Couldn't save the query results as Excel: ")
    assert '"q1.xlsx"' in sentence
    # Wired to the cap rather than re-typing its value: the VALUE is pinned by the budget test
    # above, which derives it, and repeating it here would be a second copy to update when the
    # account's memory quota is raised. What this asserts is the wiring — that the sentence a
    # user reads quotes the cap for the format they chose, and that the formats differ.
    for fmt in ("xlsx", "json"):
        rendered = messages.failure_message(reasons.RESULTS_TOO_LARGE, {"format": fmt})
        expected = messages._human_bytes(config.max_result_bytes(fmt))
        assert expected in rendered, f"{fmt}'s sentence does not quote its own cap"
    assert config.max_result_bytes("json") != config.max_result_bytes("xlsx"), (
        "the two caps have collapsed into one somewhere between the config and the wording"
    )
    assert messages.failure_message(reasons.FORBIDDEN) == "You don't have access to save results there."
    assert messages.failure_message(reasons.MALFORMED_EVENT, {"format": "json"}).startswith(
        "Couldn't save the query results as JSON: "
    )


#: The granularity the derived caps are floored to, so the sentence a user reads is a round
#: number rather than the raw quotient. 64 MiB is fine enough to keep the loss under 2% at
#: every cap below and coarse enough that no cap reads as an arbitrary quotient.
_CAP_GRANULARITY_MB = 64


def _derived_cap(fmt: str) -> int:
    """Recomputes one format's size cap from the measured budget, independently of the module.

    Written out here rather than imported so the assertion is between two derivations rather
    than between a value and itself: a cap that shrank because someone edited a constant has to
    be visible as a red test, and a test that asked ``config`` for the answer could not see it.

    Args:
      fmt: The output format.

    Returns:
      The cap in bytes.

    Raises:
      None.
    """
    disk_mb = config.CONVERTER_EPHEMERAL_MB * (1 - config.DISK_RESERVE)
    memory_mb = config.CONVERTER_MEMORY_MB * (1 - config.MEMORY_RESERVE)
    # The downloaded CSV and the written file sit on the scratch disk at the same time.
    bounds = [disk_mb / (1 + config.OUTPUT_EXPANSION[fmt])]
    if fmt == "xlsx":
        # And only Excel also has to fit in RAM, because only Excel cannot stream.
        bounds.append(memory_mb / config.EXCEL_MEMORY_EXPANSION)
    floored = int(min(bounds) // _CAP_GRANULARITY_MB) * _CAP_GRANULARITY_MB
    return floored * 1024**2


def test_each_formats_size_cap_is_computed_from_the_measured_converter_budget():
    """The caps are derived, and the derivation is the reason they differ by an order of magnitude.

    Both bounds are measured on the fleet image rather than assumed — `config.MEASURED_ON` says
    against what. The streamed formats are bounded by the SCRATCH DISK, which has to hold the
    downloaded CSV and the written file at once. Excel is bounded by MEMORY, because it is the
    one format that cannot stream: polars materialises the frame and xlsxwriter builds the whole
    workbook beside it, and the measured peak was 23x to 32x the CSV. Taking the worst of those
    rather than a fitted slope is deliberate — the failure it guards against is an OOM.

    A single cap could not be honest here: applied at Excel's bound it would refuse Parquet
    conversions that work comfortably, and applied at the disk bound it would promise an Excel
    conversion that runs out of memory two thirds of the way through.
    """
    assert set(config.RESULTS_MAX_BYTES) == set(config.OUTPUT_EXPANSION) == {"parquet", "json", "xlsx"}
    for fmt, cap in config.RESULTS_MAX_BYTES.items():
        assert cap == _derived_cap(fmt), f"{fmt}'s cap is not what the budget derives"
        assert cap % 1024**2 == 0, "the cap must render in whole units to a user"
    assert config.RESULTS_MAX_BYTES["xlsx"] < config.RESULTS_MAX_BYTES["json"], (
        "Excel is the memory-bound format; a budget that made it the largest has lost the "
        "constraint that produced it"
    )
    assert config.max_result_bytes("nonsense") == min(config.RESULTS_MAX_BYTES.values()), (
        "an unknown format falls to the smallest cap, never the largest"
    )


def test_the_converter_can_finish_its_largest_input_inside_its_own_timeout():
    """The time bound is a CHECK on the caps above, not an input to them — which is why it is
    stated separately and why it can be honest about what it does not know.

    Measured in the fleet image: Excel converts at about 4.2 MB/s (xlsxwriter is single-threaded
    Python and dominates), the streamed formats at 130 MB/s or better. Those figures come from
    an arm64 build on a developer machine and production runs amd64, so the check derates by 4
    rather than pretending the measurement transfers. If the live figure comes back below
    roughly 1 MB/s for Excel, the cap has to come down; that measurement is owed from the
    spec's live verification and is recorded on its PR.
    """
    measured_mb_per_second = {"parquet": 212.0, "json": 132.0, "xlsx": 4.2}
    derate, reserve_seconds = 4, 60
    usable = config.CONVERTER_TIMEOUT_SECONDS - reserve_seconds
    assert usable > 0
    for fmt, cap in config.RESULTS_MAX_BYTES.items():
        seconds = (cap / 1024**2) / (measured_mb_per_second[fmt] / derate)
        assert seconds <= usable, (
            f"{fmt} needs {seconds:.0f}s for its {cap // 1024**2} MB cap but has {usable}s"
        )
    assert config.CONVERTER_TIMEOUT_SECONDS <= 900, "Lambda refuses a timeout over 15 minutes"


def test_the_ceiling_clears_the_longest_path_the_machine_can_walk():
    """The machine's ceiling is a ceiling, not a guess: every Task's timeout times its attempts,
    plus the backoff between attempts, along the longest path through the machine."""
    locals_text = _LOCALS.read_text(encoding="utf-8")
    ceiling = int(re.search(r"state_machine_timeout_seconds\s*=\s*(\d+)", locals_text).group(1))
    assert ceiling == config.MACHINE_TIMEOUT_SECONDS, (
        "the Terraform ceiling and the constant the timeout notification words have diverged; "
        "the user would be told a duration the machine no longer runs for"
    )
    assert "an hour" in messages.failure_message(reasons.CONVERSION_TIMED_OUT)
    timeouts = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r'"([a-z-]+)"\s*=\s*\{[^}]*timeout\s*=\s*(\d+)', locals_text)
    }
    assert set(timeouts) == {
        "validate-authorize",
        "describe-results",
        "notify-failure",
        "convert",
        "notify",
    }
    assert timeouts["convert"] == config.CONVERTER_TIMEOUT_SECONDS, (
        "the converter's Terraform timeout and the constant the size budget derives from have "
        "diverged, so the caps are computed against a function that runs for a different time"
    )
    # The other two halves of the budget. `config` DOCUMENTS them as mirrored from locals.tf and
    # nothing held them there: dropping `memory = 10240, ephemeral = 10240` to 2048/512 left the
    # whole suite green, while all three size caps go on being derived from the larger numbers.
    # What that permits is an OOM on the Excel path or a full disk on the streamed ones, part of
    # the way through a conversion — the failure the per-format budget exists to prevent.
    convert_row = re.search(r'"convert"\s*=\s*\{(.*?)\}', locals_text, re.DOTALL).group(1)
    deployed = {
        key: int(value)
        for key, value in re.findall(r"(memory|ephemeral)\s*=\s*(\d+)", convert_row)
    }
    assert deployed == {
        "memory": config.CONVERTER_MEMORY_MB,
        "ephemeral": config.CONVERTER_EPHEMERAL_MB,
    }, (
        f"locals.tf deploys {deployed} while the size caps are derived from "
        f"memory={config.CONVERTER_MEMORY_MB} ephemeral={config.CONVERTER_EPHEMERAL_MB}"
    )
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", _ASL.read_text(encoding="utf-8"))
    states = json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))["States"]
    longest = 0
    for name, key in (
        ("ValidateAuthorize", "validate-authorize"),
        ("DescribeResults", "describe-results"),
        ("Convert", "convert"),
        ("Notify", "notify"),
        ("NotifyFailure", "notify-failure"),
    ):
        retry = states[name]["Retry"][0]
        attempts = retry["MaxAttempts"] + 1
        backoff = sum(retry["IntervalSeconds"] * retry["BackoffRate"] ** i for i in range(retry["MaxAttempts"]))
        longest += timeouts[key] * attempts + backoff
    assert ceiling > longest, f"the ceiling {ceiling}s cannot hold the longest path, {longest}s"


def test_the_converter_retries_only_what_cannot_have_written_anything():
    """Convert's Retry is deliberately unlike every other Task's, and the reason is correctness.

    The four Lambda service errors cover a response lost AFTER the function completed. A
    re-invocation in that window meets its own conditional PutObject, gets a precondition
    failure, and reports `destination_occupied` to a user whose save in fact succeeded — so the
    retry would manufacture the one refusal this plane's whole conditional-write design exists
    to make truthful. Only TransientError is retried, which the verb raises solely before the
    upload begins.
    """
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", _ASL.read_text(encoding="utf-8"))
    states = json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))["States"]
    retry = states["Convert"]["Retry"][0]
    assert retry["ErrorEquals"] == ["TransientError"], (
        "a Lambda.* retry here can re-run an invocation that already wrote the object"
    )
    assert retry["MaxAttempts"] == 1
    for other in ("ValidateAuthorize", "DescribeResults", "NotifyFailure"):
        assert "Lambda.ServiceException" in states[other]["Retry"][0]["ErrorEquals"], (
            f"{other} still retries the service errors, so the narrowing above is Convert's "
            "alone rather than a fleet-wide change made by accident"
        )


def test_the_timed_out_door_reads_the_event_and_never_describes_the_execution():
    """One claim in two places: the policy grants no DescribeExecution, so the door must not
    reach for the shared helper that falls back to it."""
    source = _DOOR.read_text(encoding="utf-8")
    assert "timed_out_execution_input" not in source
    assert "describe_execution" not in source
    assert 'detail.get("input")' in source


def test_the_timeout_rule_matches_timed_out_and_never_failed():
    text = (_MODULE / "stepfunction.tf").read_text(encoding="utf-8")
    assert 'status          = ["TIMED_OUT"]' in text
    assert "FAILED" not in text.split("event_pattern")[1].split("})")[0]
    assert '"TimeoutSeconds": ${state_machine_timeout_seconds}' in _ASL.read_text(encoding="utf-8")


def test_no_queue_resource_policy_is_added_anywhere_in_the_fleet():
    """The notifications writer's boundary is a runtime denylist of one; a queue policy would
    silence notifying roles invisibly."""
    offenders = [
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "infra" / "modules").rglob("*.tf")
        if "aws_sqs_queue_policy" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_module_ships_no_moved_block():
    """A cutover-era guard counts moved blocks against the frozen fixture; a new module has
    nothing to move."""
    assert not (_MODULE / "moved.tf").exists()


@pytest.mark.parametrize("fixture", ["module_dir", "policy", "asl"])
def test_the_files_this_suite_reads_exist(fixture):
    path = {"module_dir": _MODULE, "policy": _POLICY, "asl": _ASL}[fixture]
    assert path.exists(), f"{path} is missing, so the assertions over it are vacuous"
