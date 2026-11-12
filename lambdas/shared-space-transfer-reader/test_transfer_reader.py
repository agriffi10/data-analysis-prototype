"""The operator's CSV reader: what it enqueues, what it refuses whole, and what it never touches."""

import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import transfer_reader as reader
from cpcommon import clients
from fakes import install
from tf_blocks import lambda_declaration, lambda_input, map_entries, module_calls, span

_BUCKET = "admin-bkt"

#: One valid file covering all three actions across DIFFERENT spaces, since one space takes one
#: action per file. The two `finance` rows are the coalescing case.
_THREE_ACTIONS = (
    "space,action,username\n"
    "finance,add,bcarter\n"
    "finance,add,rsingh\n"
    "project_atlas,transfer,dmehta\n"
    "sales_archive,remove,agriffith\n"
)


def _setup(files=None):
    """Installs the fakes, points the reader at a queue, and seeds the inbox.

    Args:
      files: Mapping of inbox file name to its text body.

    Returns:
      The S3 fake.

    Raises:
      None.
    """
    s3, *_ = install()
    os.environ["SHARED_SPACE_REQUESTS_QUEUE_URL"] = "https://sqs.test/shared-space-requests.fifo"
    for name, body in (files or {}).items():
        s3.store[(_BUCKET, f"{reader.INBOX}{name}")] = body.encode()
    return s3


def _sent():
    """The message bodies the reader put on the queue.

    Args:
      None.

    Returns:
      The parsed bodies, in send order.

    Raises:
      None.
    """
    return [json.loads(m["MessageBody"]) for m in clients._sqs.sent]


#: How many spaces a bulk fixture spreads its rows across. Under `MAX_SPACES_PER_FILE`, so a
#: fixture built to exercise the ROW cap is not rejected by the blast-radius ceiling first — which
#: is what the first draft of these fixtures did, reaching the right disposition for the wrong
#: reason and asserting nothing about the cap it was named for.
_FIXTURE_SPACES = 20


def _rows_for(tag, count):
    """Builds a CSV of `count` rows whose every space name starts with one tag.

    `remove` rather than `add`, and spread across `_FIXTURE_SPACES` spaces: the add ceiling and
    the spaces ceiling would otherwise fire before the cap under test. Every username is unique,
    so no row is a duplicate triple.

    Args:
      tag: The prefix every space name in this file carries.
      count: How many data rows to write.

    Returns:
      The file body.

    Raises:
      None.
    """
    return "space,action,username\n" + "\n".join(
        f"{tag}_{i % _FIXTURE_SPACES},remove,user_{tag}_{i}" for i in range(count)
    )


def _keys(s3, prefix):
    """Every key under one prefix in the fake.

    Args:
      s3: The S3 fake.
      prefix: The prefix to filter on.

    Returns:
      The sorted keys.

    Raises:
      None.
    """
    return sorted(key for bucket, key in s3.store if bucket == _BUCKET and key.startswith(prefix))


def _reason(s3):
    """The reason text written beside the one rejected file.

    Args:
      s3: The S3 fake.

    Returns:
      The reason.

    Raises:
      StopIteration: When nothing was rejected, which is itself the assertion failing.
    """
    key = next(k for k in _keys(s3, reader.REJECTED) if k.endswith(".reason.txt"))
    return s3.store[(_BUCKET, key)].decode()


def test_one_file_covering_all_three_actions_enqueues_what_each_verb_reads():
    """The payload key is asserted against the key the VERB actually reads, imported here, rather
    than against a literal repeated in this file — two literals written from each other agree with
    nothing else.
    """
    _setup({"a.csv": _THREE_ACTIONS})

    reader.handler({}, None)

    sent = _sent()
    assert [(m["space"], m["action"]) for m in sent] == [
        ("finance", "add_members"),
        ("project_atlas", "transfer_ownership"),
        ("sales_archive", "remove_members"),
    ]
    assert sent[0]["payload"]["members"] == ["bcarter", "rsingh"], "the two add rows coalesced"
    assert sent[1]["payload"]["newOwner"] == "dmehta"
    assert sent[2]["payload"]["members"] == ["agriffith"]
    assert all(m["origin"] == "operator" for m in sent)
    assert all("identity" not in m and "idToken" not in m for m in sent), (
        "an operator message carries no credential at all — the SenderId stands in for it"
    )
    assert all(m["schemaVersion"] == reader.SCHEMA_VERSION for m in sent)
    assert all(m["MessageGroupId"] == "shared-space" for m in clients._sqs.sent)


def test_the_payload_keys_are_the_ones_the_verbs_actually_read():
    """Read out of the verb modules, so a rename on either side reddens here rather than shipping
    a message the verb parses into an empty list and reports success on."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for folder, module, key in (
        ("shared-space-add-members", "add_members.py", '"members"'),
        ("shared-space-remove-members", "remove_members.py", '"members"'),
        ("shared-space-transfer-ownership", "transfer_ownership.py", '"newOwner"'),
    ):
        source = (root / folder / module).read_text()
        assert f'.get({key}' in source, f"{module} no longer reads {key}"


def test_the_operator_vocabulary_maps_onto_the_actions_the_plane_admits_in_BOTH_directions():
    """Set equality forces a word to exist for every admitted action and forces one to go when an
    action is withdrawn. It does NOT stop two words collapsing onto one action, which is why the
    injectivity is asserted separately: three keys, three distinct values.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))
    import config as domain_config

    assert set(reader.ACTIONS.values()) == set(domain_config.OPERATOR_ACTIONS)
    assert len(set(reader.ACTIONS.values())) == len(reader.ACTIONS) == 3


def test_a_processed_file_is_copied_aside_and_removed_from_the_inbox():
    """So a later tick cannot re-enqueue it."""
    s3 = _setup({"a.csv": "space,action,username\nfinance,add,bcarter\n"})

    reader.handler({}, None)

    assert _keys(s3, reader.INBOX) == []
    processed = _keys(s3, reader.PROCESSED)
    assert len(processed) == 1 and processed[0].endswith("/a.csv")


def test_the_copy_is_confirmed_before_the_delete():
    """A delete that ran first, followed by a failed copy, loses the operator's file — and loses it
    silently, because the next tick simply finds an empty inbox. The store looks identical either
    way, so the ORDER is what has to be asserted."""
    s3 = _setup({"a.csv": "space,action,username\nfinance,add,bcarter\n"})

    reader.handler({}, None)

    kinds = [op[0] for op in s3.operations]
    assert kinds == ["copy", "delete"], f"the file was moved in the wrong order: {s3.operations}"


def test_an_empty_inbox_is_a_successful_no_op():
    """The first firing of a newly created schedule must not fail."""
    _setup()

    result = reader.handler({}, None)

    assert result == {"status": "ok", "filesSeen": 0, "filesHandled": 0, "rowsEnqueued": 0}
    assert clients._sqs.sent == []


def test_the_RETIRED_header_is_told_what_changed_rather_than_that_its_columns_are_wrong():
    """An operator who wrote yesterday's file gets the generic wrong-header sentence otherwise,
    which is true and tells them nothing they can act on."""
    s3 = _setup({"old.csv": "space,new_owner\nfinance,bcarter\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == []
    reason = _reason(s3)
    assert "retired" in reason
    assert "'action'" in reason or "action" in reason
    for word in sorted(reader.ACTIONS):
        assert word in reason, f"the reason does not name {word!r}"


def test_a_wrong_header_rejects_the_WHOLE_file_and_enqueues_none_of_its_rows():
    """Including the transposed set, which parses perfectly and would act on every row against the
    wrong argument."""
    s3 = _setup({"bad.csv": "username,action,space\nbcarter,add,finance\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == [], "not one row was enqueued"
    assert _keys(s3, reader.INBOX) == []
    assert "header" in _reason(s3)


def test_every_per_row_refusal_names_its_LINE_and_rejects_the_whole_file():
    """Enumerated rather than sampled, and each case carries a good row ABOVE the bad one so a
    reader that enqueued as it parsed would be caught by the empty queue rather than by the
    disposition."""
    # **The fixture names are deliberately opaque.** Every refusal message opens with the object
    # key, so a file called `blank.csv` supplies the fragment "blank" whatever actually fired —
    # and the blank-field guard could then be deleted with this test still green, because the
    # identifier check below it refuses the same row for a different reason. Each case now
    # asserts the sentence its OWN guard writes.
    cases = {
        "case_a.csv": ("space,action,username\nfinance,add,bcarter\nproject\n", "has 1 fields, not 3"),
        "case_b.csv": ("space,action,username\nfinance,add,bcarter\npa,add,b,extra\n", "has 4 fields, not 3"),
        "case_c.csv": ("space,action,username\nfinance,add,bcarter\nproject,add,\n", "leaves a field blank"),
        # A row of EMPTY FIELDS is not a blank line. Skipping it would drop a row the operator
        # wrote with no line named and no refusal, and report the file as processed.
        "case_d.csv": ("space,action,username\nfinance,add,bcarter\n,,\n", "leaves a field blank"),
        "case_e.csv": ("space,action,username\nfinance,add,bcarter\nproject,grant,dmehta\n", "asks for 'grant'"),
        "case_f.csv": ("space,action,username\nfinance,add,bcarter\nProject,add,dmehta\n", "has space 'Project'"),
        "case_g.csv": ("space,action,username\nfinance,add,bcarter\nproject,add,D.Mehta\n", "has username 'D.Mehta'"),
    }
    for name, (body, fragment) in cases.items():
        s3 = _setup({name: body})
        reader.handler({}, None)
        reason = _reason(s3)
        assert clients._sqs.sent == [], f"{name}: the good row above the bad one was enqueued"
        assert "line 3" in reason, f"{name}: the reason names no line — {reason}"
        assert fragment in reason, f"{name}: {fragment!r} not in {reason!r}"


def test_a_refusal_names_the_line_the_OPERATORS_EDITOR_shows():
    """A quoted field carrying a newline is one record over two physical lines, so a reader that
    enumerated records would name line 3 for something on line 4 — and every refusal after it
    drifts further. These messages exist only to be acted on, and a line number the operator
    cannot find is worse than none.

    The `finance` row is deliberately VALID and multi-line, so the drift is introduced above the
    bad row rather than by it.
    """
    body = (
        "space,action,username\n"
        'finance,"add\n",bcarter\n'
        "project,add,D.Mehta\n"
    )
    s3 = _setup({"wrapped.csv": body})

    reader.handler({}, None)

    reason = _reason(s3)
    assert "line 4" in reason, f"the reason names the wrong physical line: {reason}"
    assert "line 3" not in reason


def test_a_file_that_is_not_utf8_is_refused_whole_and_says_so():
    """Reachable from any editor with a regional default encoding, and the operator sees a file
    that looks fine. Enumerated here because a refusal nobody tests is the half of the system no
    user exercises."""
    s3 = _setup()
    s3.store[("admin-bkt", f"{reader.INBOX}latin.csv")] = (
        b"space,action,username\nfinance,add,bcarter\n" + b"\xff\xfe"
    )

    reader.handler({}, None)

    assert clients._sqs.sent == []
    assert "UTF-8" in _reason(s3)


def test_a_file_with_no_header_at_all_is_refused_rather_than_read_as_empty():
    """An empty INBOX is a successful no-op; an empty FILE is not the same thing, and treating it
    as one would move a file the operator meant to fill to `processed/` reporting success."""
    s3 = _setup({"nothing.csv": ""})

    reader.handler({}, None)

    assert clients._sqs.sent == []
    assert _keys(s3, reader.PROCESSED) == []
    assert "not even a header" in _reason(s3)


def test_a_file_saved_by_excel_parses_rather_than_being_rejected_whole():
    """Excel writes a UTF-8 BOM by default, and an operator's CSV is exactly the file Excel makes.

    Left in, the first column reads `﻿space`, the header comparison fails and the whole file
    is refused — for a reason invisible in the operator's own editor. `str.strip()` does not remove
    it either: U+FEFF is not whitespace.
    """
    s3 = _setup({"excel.csv": "\ufeffspace,action,username\nfinance,add,bcarter\n"})

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["finance"]
    assert _keys(s3, reader.REJECTED) == []


def test_a_repeated_row_rejects_the_file_naming_BOTH_lines():
    s3 = _setup({"dup.csv": "space,action,username\nfinance,add,bcarter\nfinance,add,bcarter\n"})

    reader.handler({}, None)

    reason = _reason(s3)
    assert clients._sqs.sent == []
    assert "2" in reason and "3" in reason, reason


def test_one_space_under_TWO_actions_rejects_the_file_naming_the_space_and_both_lines():
    """Two actions on one space read as a sequence and are not one: the executions overlap, so
    `transfer` then `remove` can be validated in either order and the losing order refuses with
    advice the previous line already took. The reader is the only place that can see the pair.
    """
    s3 = _setup(
        {"seq.csv": "space,action,username\nfinance,transfer,dmehta\nfinance,remove,bcarter\n"}
    )

    reader.handler({}, None)

    reason = _reason(s3)
    assert clients._sqs.sent == []
    assert "finance" in reason and "2" in reason and "3" in reason, reason


def test_two_transfers_of_one_space_naming_DIFFERENT_targets_are_refused():
    """A repeated target is already a duplicate row; two different ones are a race whichever way
    they are read."""
    s3 = _setup(
        {"two.csv": "space,action,username\nfinance,transfer,dmehta\nfinance,transfer,bcarter\n"}
    )

    reader.handler({}, None)

    assert clients._sqs.sent == []
    assert "twice" in _reason(s3)


def test_the_members_per_message_cap_is_computed_from_the_verbs_own_budget():
    """Named to its inputs rather than written down, and the inputs are read from Terraform.

    The timeout is add-members' own row in the plane's verb map, and the shared module deploys
    each row's timeout as written; both halves are read, so a module that stopped honouring the
    row reddens here rather than sizing against a number that is not deployed.
    """
    expected = int(
        (
            reader.ADD_MEMBERS_TIMEOUT_SECONDS * reader.ADD_MEMBERS_BUDGET_FRACTION * 1000
            - reader.REGISTRY_MILLISECONDS
            - reader.REFERENCE_ROSTER * reader.PER_ROSTER_MEMBER_MILLISECONDS
        )
        / (reader.PER_MEMBER_MILLISECONDS + reader.PER_ROSTER_MEMBER_MILLISECONDS)
    )
    assert expected == reader.MAX_MEMBERS_PER_MESSAGE
    assert reader.MAX_MEMBERS_PER_MESSAGE > 0, (
        "the reference roster has eaten the whole budget, so no add could ever be enqueued"
    )

    # Recomputing from the same constants can only agree with itself, so the ROSTER TERM is
    # asserted to bind. FR-002 is explicit that an R-independent model is too permissive for
    # exactly the large space this cap protects — and with either roster constant at zero the
    # expression above still evaluates, still agrees with itself, and the cap silently rises.
    assert reader.REFERENCE_ROSTER > 0 and reader.PER_ROSTER_MEMBER_MILLISECONDS > 0
    without_roster = int(
        (
            reader.ADD_MEMBERS_TIMEOUT_SECONDS * reader.ADD_MEMBERS_BUDGET_FRACTION * 1000
            - reader.REGISTRY_MILLISECONDS
        )
        / reader.PER_MEMBER_MILLISECONDS
    )
    # `>` alone rules out exactly zero, which the line above already rules out: at a
    # per-roster-member cost of 1ms the cap is 84 against 85 and a bare `>` still holds, on a
    # fan-out model that models nothing. So the term is asserted to bind MATERIALLY — the ratio
    # is 1.93 as shipped, 1.29 with the reference roster reduced to nothing, and 1.01 with the
    # per-member cost reduced to nothing. Half again is the line: it clears today's value
    # comfortably and fails every degenerate one.
    assert 2 * without_roster >= 3 * reader.MAX_MEMBERS_PER_MESSAGE, (
        f"dropping the fan-out term leaves the cap at {without_roster} against "
        f"{reader.MAX_MEMBERS_PER_MESSAGE} — the roster term is present but barely binds, so the "
        "model is roster-dependent in form only"
    )

    infra = pathlib.Path(__file__).resolve().parents[2] / "infra"
    machine = lambda_declaration(
        (infra / "modules" / "control-plane" / "lambda.tf").read_text(), "functions"
    )
    assert lambda_input(machine, "timeout") == "each.value.timeout", (
        "the shared module no longer deploys each verb's own timeout row"
    )

    plane = (infra / "plane-shared-spaces.tf").read_text()
    start = re.search(r"(?m)^\s*shared_space_functions\s*=\s*\{", plane)
    assert start, "the verb map was not found, so this assertion is vacuous"
    verbs = map_entries(span(plane, start.end() - 1))
    assert "add-members" in verbs, f"the verb map has no add-members row: {sorted(verbs)}"
    timeouts = re.findall(r"\btimeout\s*=\s*(\d+)", verbs["add-members"])
    assert len(timeouts) == 1, f"add-members' row is reshaped: {verbs['add-members']}"
    assert int(timeouts[0]) == reader.ADD_MEMBERS_TIMEOUT_SECONDS, (
        f"the cap is sized for {reader.ADD_MEMBERS_TIMEOUT_SECONDS}s and Terraform deploys "
        f"add-members with {timeouts[0]}s"
    )


def test_a_group_larger_than_the_members_cap_rejects_the_file_naming_the_cap():
    """Only the operator can split it, which is the same reasoning the row cap already carries."""
    # The fixture must reach the MEMBERS cap, not a ceiling above it: raise the members cap past
    # the add ceiling and this file trips the ceiling instead, reddening for the wrong guard.
    assert reader.MAX_MEMBERS_PER_MESSAGE + 1 <= reader.MAX_ADD_ROWS_PER_FILE
    rows = "\n".join(f"finance,add,user_{i}" for i in range(reader.MAX_MEMBERS_PER_MESSAGE + 1))
    s3 = _setup({"big.csv": f"space,action,username\n{rows}\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == []
    reason = _reason(s3)
    assert str(reader.MAX_MEMBERS_PER_MESSAGE) in reason and "Split it" in reason, reason


def test_the_two_blast_radius_ceilings_reject_a_file_naming_the_one_it_broke():
    """Neither is a resource budget: without them one file is up to the row cap's worth of grants
    across as many spaces, with no dual control, no approval and no outcome ledger."""
    spaces = "\n".join(
        f"space_{i},transfer,owner_{i}" for i in range(reader.MAX_SPACES_PER_FILE + 1)
    )
    s3 = _setup({"wide.csv": f"space,action,username\n{spaces}\n"})
    reader.handler({}, None)
    assert clients._sqs.sent == []
    assert str(reader.MAX_SPACES_PER_FILE) in _reason(s3)

    per_space = reader.MAX_MEMBERS_PER_MESSAGE
    needed = reader.MAX_ADD_ROWS_PER_FILE + 1
    # Same trap in the other direction: widen the add ceiling and this file spreads over more
    # spaces than the spaces ceiling allows, so it reddens on that instead.
    assert -(-needed // per_space) <= reader.MAX_SPACES_PER_FILE
    adds = "\n".join(
        f"space_{i // per_space},add,user_{i}" for i in range(needed)
    )
    s3 = _setup({"deep.csv": f"space,action,username\n{adds}\n"})
    reader.handler({}, None)
    assert clients._sqs.sent == []
    assert str(reader.MAX_ADD_ROWS_PER_FILE) in _reason(s3)


def test_every_number_that_was_CHOSEN_rather_than_computed_is_pinned_where_it_was_argued():
    """ACCEPTED_-style: these two are CHOSEN rather than computed, so nothing else can catch them
    moving. Every fixture that exercises them is built as `cap + 1` and follows the cap wherever
    it goes, so the mechanism is well covered and the NUMBER is covered by nothing.

    Revisit the decision rather than deleting the test. What they buy: one file is one operator
    action, and without a ceiling it is up to the row cap's worth of grants across as many spaces,
    with no dual control, no approval and no outcome ledger. What they do NOT buy is a bound on a
    hostile writer, who can upload ten files in one tick — that residual is recorded in the
    register, and these numbers are sized against a careless operator, not against them.
    """
    assert reader.MAX_SPACES_PER_FILE == 25
    assert reader.MAX_ADD_ROWS_PER_FILE == 100

    # `REFERENCE_ROSTER` belongs here for the same reason, and it took a mutation to see it. The
    # roster-term assertion beside the cap catches that term going to ZERO, but not the reference
    # shrinking to a token value — at 1 the model stays formally roster-dependent, every
    # assertion still holds, and the cap quietly rises. The number carries the whole argument:
    # there is no per-space roster cap in the product, so this is the largest space the cap is
    # sized to protect, and a space above it can exhaust the verb's budget for any number of
    # added members. Revisit the decision rather than deleting the test.
    assert reader.REFERENCE_ROSTER == 100

    # `MAX_FILE_BYTES` belongs here too, and it took a mutation to see it: the oversize fixture is
    # `cap + 1` bytes, so it follows the cap anywhere — widening this to a gigabyte leaves the
    # suite green while the guard can no longer fire, and a test cannot honestly seed a gigabyte
    # to prove otherwise. What the number carries: the row cap is 600, a generous row is 200
    # bytes, so a legitimate file is around 120 KB and this leaves roughly eight times that —
    # while staying two orders of magnitude below the 128 MB the function actually has, because
    # the parse peaks at many times the file's own size. Revisit the decision rather than
    # deleting the test; re-derive it if either the row cap or the function's memory moves.
    assert reader.MAX_FILE_BYTES == 1_048_576


def test_the_row_cap_keeps_its_existing_inputs_and_its_existing_value():
    """Coalescing made it conservative and it is deliberately not re-derived: this function was
    never the expensive half, and a cap re-derived from a per-row PARSE cost would run to five
    figures, leave the over-cap rejection unreachable and bound nothing anyone cares about.
    """
    expected = int(
        reader.TIMEOUT_SECONDS * reader.SEND_BUDGET_FRACTION * 1000 / reader.SEND_MILLISECONDS
    )
    assert expected == reader.MAX_ROWS_PER_INVOCATION

    infra = pathlib.Path(__file__).resolve().parents[2] / "infra"
    function = lambda_declaration(
        (infra / "modules" / "scheduled-function" / "main.tf").read_text(), "function"
    )
    assert lambda_input(function, "timeout") == "var.timeout_seconds", (
        "the scheduled-function module no longer deploys the timeout its caller passes"
    )
    call = module_calls((infra / "plane-shared-spaces.tf").read_text())["shared_space_transfer_reader"]
    declared = int(lambda_input(call, "timeout"))
    assert declared == reader.TIMEOUT_SECONDS, (
        f"the reader budgets for {reader.TIMEOUT_SECONDS}s and Terraform gives it {declared}s"
    )


def test_a_file_bigger_than_the_WHOLE_row_cap_is_refused_rather_than_deferred_forever():
    """A file of more rows than one invocation can ever read cannot be processed by ANY tick.
    Leaving it in the inbox is not "waiting for the next tick", it is waiting forever — in a prefix
    that deliberately has no expiry rule, behind a log line nobody is alerted on.

    The wording no longer claims those rows "could never be handled in one run" because there are
    too many SENDS: coalescing separated the two, and the cap now bounds rows READ.
    """
    s3 = _setup({"big.csv": _rows_for("bulk", reader.MAX_ROWS_PER_INVOCATION + 1)})

    # The fixture must reach the ROW cap, not a ceiling above it — otherwise this asserts the
    # right disposition for the wrong reason.
    rows = reader.MAX_ROWS_PER_INVOCATION + 1
    assert _FIXTURE_SPACES <= reader.MAX_SPACES_PER_FILE
    assert -(-rows // _FIXTURE_SPACES) <= reader.MAX_MEMBERS_PER_MESSAGE

    result = reader.handler({}, None)

    assert clients._sqs.sent == [], "an over-cap file is not partly enqueued"
    assert _keys(s3, reader.INBOX) == [], "and it does not sit in the inbox forever"
    assert _keys(s3, reader.PROCESSED) == []
    assert result["rowsEnqueued"] == 0

    reason = _reason(s3)
    assert str(reader.MAX_ROWS_PER_INVOCATION) in reason, "the operator is told the cap"
    assert "read in one run" in reason, "the rejection no longer conflates a row with a send"
    assert "Split it" in reason, "and what to do about it"


def test_files_are_processed_in_listing_order():
    """Lexicographic, which is what makes a sequence of operator files replayable."""
    _setup(
        {
            "a.csv": "space,action,username\nalpha,add,one\n",
            "b.csv": "space,action,username\nbeta,add,two\n",
            "c.csv": "space,action,username\ngamma,add,three\n",
        }
    )

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["alpha", "beta", "gamma"]


def test_a_spent_budget_STOPS_the_sweep_so_a_later_file_cannot_overtake_an_earlier_one():
    """Skipping the file that does not fit and carrying on would let a small later file jump ahead
    of a large earlier one, and listing order is the whole of what makes a sequence replayable.
    """
    # c.csv is DELIBERATELY small enough to fit what is left after a.csv. With three equal files
    # the budget excludes b and c alike, so `break` and `continue` behave identically and the test
    # asserts nothing — which is exactly what the first version of it did.
    half = reader.MAX_ROWS_PER_INVOCATION // 2 + 10
    s3 = _setup(
        {
            "a.csv": _rows_for("a", half),
            "b.csv": _rows_for("b", half),
            "c.csv": _rows_for("c", 5),
        }
    )

    result = reader.handler({}, None)

    assert result["filesHandled"] == 1, "the count must not include a file it did not handle"
    assert _keys(s3, reader.INBOX) == [f"{reader.INBOX}b.csv", f"{reader.INBOX}c.csv"]
    spaces = [json.loads(m["MessageBody"])["space"] for m in clients._sqs.sent]
    assert all(s.startswith("a_") for s in spaces), (
        f"c.csv fits the remaining budget and overtook b.csv: {sorted(set(spaces))}"
    )


def test_the_shortfall_is_logged_rather_than_dropped_silently(captured_events):
    """CLAUDE.md's "no silent caps": if a check bounds coverage, it says what was dropped.

    Asserted on the emitted event rather than on the absence of work, because "nothing was
    enqueued and the file is still there" is equally true of a reader that says nothing at all.
    """
    half = reader.MAX_ROWS_PER_INVOCATION // 2 + 10
    _setup({name: _rows_for(name[0], half) for name in ("a.csv", "b.csv")})

    reader.handler({}, None)

    deferred = [
        event
        for event in captured_events.events
        if (event.get("fields") or {}).get("rows_not_processed")
    ]
    assert deferred, f"the rows it did not process were never reported: {captured_events.events}"
    assert deferred[0]["fields"]["rows_not_processed"] == half
    assert deferred[0]["fields"]["cap"] == reader.MAX_ROWS_PER_INVOCATION


def test_the_log_distinguishes_an_add_from_a_removal_and_says_which_lines_fed_it(captured_events):
    """The reader's structured log is the operator's ONLY feedback channel — the notifications go
    to the space's owner and the added or removed members, and none of them names the operator.
    A line that said "ownership-transfer" for a removal would be worse than none.
    """
    _setup({"a.csv": _THREE_ACTIONS})

    reader.handler({}, None)

    enqueued = [
        event["fields"]
        for event in captured_events.events
        if event.get("message") == "enqueued an operator request"
    ]
    assert [(f["space"], f["action"]) for f in enqueued] == [
        ("finance", "add_members"),
        ("project_atlas", "transfer_ownership"),
        ("sales_archive", "remove_members"),
    ]
    assert enqueued[0]["lines"] == [2, 3], enqueued[0]
    assert enqueued[1]["lines"] == [4]
    assert not any(
        "ownership-transfer" in str(event.get("message", "")) for event in captured_events.events
    ), "an event still describes every operator request as an ownership transfer"


def test_the_reader_touches_only_the_operator_requests_prefix():
    """It never reads or writes the registry, and holds no grant that would let it.

    Whether a space exists, whether the named member belongs to it and whether the caller may make
    the change are the validator's questions; a reader that answered them is a second authority
    that will eventually disagree with the first.
    """
    s3 = _setup({"a.csv": _THREE_ACTIONS})
    touched = []
    for name in ("get_object", "put_object", "delete_object", "list_objects_v2"):
        real = getattr(s3, name)

        def watch(_real=real, **kw):
            touched.append(kw.get("Key") or kw.get("Prefix"))
            return _real(**kw)

        setattr(s3, name, watch)
    real_copy = s3.copy_object

    def watch_copy(Bucket, Key, CopySource, **kw):
        touched.extend([Key, CopySource["Key"]])
        return real_copy(Bucket=Bucket, Key=Key, CopySource=CopySource, **kw)

    s3.copy_object = watch_copy

    reader.handler({}, None)

    assert touched, "the sweep recorded nothing, so this asserts nothing"
    stray = [key for key in touched if not key.startswith("operator-requests/")]
    assert stray == [], f"the reader reached outside its prefix: {stray}"


def test_the_GRANT_is_scoped_to_the_prefix_the_code_actually_reads():
    """The prefix now lives in four independent places — three constants here, two statements in
    the reader's IAM template, two lifecycle rules, and this file. Nothing tied them together, and
    a drift in any one is green in every gate: the reader would simply take `AccessDenied` on its
    listing once an hour, outside any handler try, on a function in no probe list, with the
    operator's only channel being the log it can no longer write to.

    The expected value is derived from `reader.INBOX` — the code — and the Terraform is asserted
    to match it. Deriving it from the template instead would only prove the template agrees with
    itself.

    It also asserts the grant reaches NOTHING ELSE on the admin bucket. The prefix was admitted
    additively across the cutover, deliberately, and this is what makes the narrowing visible: a
    second prefix reappearing here is a widening somebody has to have meant.
    """
    prefix = reader.INBOX.split("/")[0]
    assert prefix and "/" not in prefix

    policy = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra" / "planes" / "shared-spaces" / "transfer-reader.json.tftpl"
    ).read_text()
    rendered = json.loads(
        re.sub(r"\$\{[a-z_]+\}", "arn:aws:test", policy)
    )

    bucket_statements = [
        s for s in rendered["Statement"] if "s3" in json.dumps(s["Action"])
    ]
    assert bucket_statements, "no S3 statement found, so this test asserts nothing"

    scopes = []
    for statement in bucket_statements:
        resource = statement["Resource"]
        scopes.extend([resource] if isinstance(resource, str) else resource)
        condition = statement.get("Condition", {}).get("StringLike", {})
        for value in condition.values():
            scopes.extend([value] if isinstance(value, str) else value)

    keyed = [s for s in scopes if s.endswith("/*")]
    assert keyed, "the grant names no prefix at all"
    for scope in keyed:
        assert scope.endswith(f"{prefix}/*"), (
            f"the reader lists {reader.INBOX!r} but its grant covers {scope!r} — a drift here is "
            "an hourly AccessDenied on a function nothing probes"
        )

    lifecycle = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra" / "modules" / "analytics" / "s3.tf"
    ).read_text()
    for sub in ("processed", "rejected"):
        assert f'prefix = "{prefix}/{sub}/"' in lifecycle, (
            f"no lifecycle rule expires {prefix}/{sub}/, so files pile up there forever"
        )
    assert f'prefix = "{prefix}/inbox/"' not in lifecycle, (
        "the inbox gained an expiring rule, which deletes an operator's file out from under the "
        "tick that was going to retry it"
    )


def test_a_request_id_is_STABLE_across_a_replay_and_KEYED_on_the_file_it_came_from():
    """The request id is derived so one enqueued request is traceable to the lines that asked for
    it — and it is not only this function's concern. The validator passes it to `_record_intent`,
    which builds a notification dedup token out of it, so two files in one sweep naming the same
    `(space, action)` would collide and one operator's notification would be discarded inside the
    five-minute window. Silently, on the one feedback channel they have. So both inputs are
    pinned: dropping the object key, or the action, must not leave this green.
    """
    _setup({"a.csv": _THREE_ACTIONS})
    reader.handler({}, None)
    first = [m["requestId"] for m in _sent()]

    _setup({"a.csv": _THREE_ACTIONS})
    reader.handler({}, None)
    assert [m["requestId"] for m in _sent()] == first and first
    assert len(set(first)) == len(first), "two requests in one file share an id"

    same_rows = "space,action,username\nfinance,add,bcarter\n"
    assert reader._request_id("inbox/one.csv", "finance", "add_members") != reader._request_id(
        "inbox/two.csv", "finance", "add_members"
    ), "two files naming the same change produce one id, so one of them loses its notifications"
    assert reader._request_id("inbox/one.csv", "finance", "add_members") != reader._request_id(
        "inbox/one.csv", "finance", "remove_members"
    ), "an add and a removal on one space in one file share an id"
    assert same_rows  # the fixture above is the shape those keys stand for


def test_the_dedup_key_survives_an_ASYNC_RETRY_but_cannot_be_claimed_by_a_stranger():
    """Two properties, and each closes what the other opens.

    It must NOT be the derived request id: the API's dedup id on this same queue and group is the
    caller's own `requestId`, so a value computable from constants in this repository can be
    claimed first by any signed-in user on a harmless action, after which SQS discards the
    operator's real row and the log reports it enqueued. The object's `ETag` is the salt, because
    it is the content of a file in a bucket that caller cannot read.

    It must NOT be random either. EventBridge invokes this sweep ASYNCHRONOUSLY and no
    `maximum_retry_attempts` is set, so Lambda's own retries fire about a minute and three minutes
    later — INSIDE the five-minute window, unlike the hourly schedule. Under a random id a crash
    between a send and the file move delivers the whole set twice, and a duplicate transfer
    refuses as `TransferTargetIsOwner` and tells the new owner it failed a minute after telling
    them it worked.
    """
    _setup({"a.csv": _THREE_ACTIONS})
    reader.handler({}, None)
    dedup = [m["MessageDeduplicationId"] for m in clients._sqs.sent]
    request_ids = [m["requestId"] for m in _sent()]

    assert not set(dedup) & set(request_ids), (
        "the dedup key IS the request id, which a signed-in user can compute and claim first"
    )

    # Same bytes, same key -> the same token, so an async retry is collapsed.
    assert reader._dedup_id("r1", "etag-aaa") == reader._dedup_id("r1", "etag-aaa")
    # Corrected re-upload under the same key -> a new ETag, so it is sent rather than swallowed.
    assert reader._dedup_id("r1", "etag-aaa") != reader._dedup_id("r1", "etag-bbb")
    # And the salt is what a stranger cannot supply: the request id alone is not enough.
    assert reader._dedup_id("r1", "") != reader._dedup_id("r1", "etag-aaa")

    # **Everything above supplies the salt on BOTH sides**, so it agrees with itself and with
    # nothing else — `_process` could stop reading the object's ETag entirely and every assertion
    # so far would still hold. This is the one that asserts the WIRE. The ETag is read BEFORE the
    # sweep on purpose: the fake drops it when the object is deleted, so reading it afterwards
    # raises rather than failing.
    clients._sqs.sent.clear()
    s3 = _setup({"a.csv": _THREE_ACTIONS})
    etag = s3.get_object(Bucket=_BUCKET, Key=f"{reader.INBOX}a.csv")["ETag"]

    reader.handler({}, None)

    assert [m["MessageDeduplicationId"] for m in clients._sqs.sent] == [
        reader._dedup_id(m["requestId"], etag) for m in _sent()
    ], "the token is not salted with the object's own ETag, so it is guessable again"


def test_a_file_python_cannot_PARSE_is_refused_rather_than_crashing_the_sweep():
    """The worst failure this function has, and it is silent.

    `csv` raises on a field over its own size limit — one unmatched quote in a file over 128 KB —
    and on lone-CR line endings. Uncaught, that escapes `handler` and fails the invocation: the
    file never reaches `rejected/`, no reason is written, and it stays in an inbox that
    deliberately has no expiry. Files are swept in listing order, so the lowest-named bad file
    then blocks every later one on every subsequent tick, for good. The revocation this door
    exists for would never be enqueued and nobody would be told.
    """
    poison = "space,action,username\nfinance,add,\"" + ("x" * 200_000) + "\n"
    s3 = _setup({"00-poison.csv": poison, "99-urgent.csv": "space,action,username\nsales,remove,bcarter\n"})

    result = reader.handler({}, None)

    assert "not readable as CSV" in _reason(s3)
    assert _keys(s3, reader.INBOX) == [], "the bad file stayed in an inbox that never expires"
    assert [m["space"] for m in _sent()] == ["sales"], (
        "the urgent file behind the bad one was never processed"
    )
    assert result["filesHandled"] == 2


def test_a_file_too_big_to_READ_is_refused_from_the_LISTING_before_it_is_fetched():
    """The row cap cannot catch this: rows have to be parsed before they can be counted, and the
    parse materialises the whole file. At 128 MB a CSV of a few megabytes exhausts the function —
    and that is not a refusal, it kills the invocation, so the file never reaches `rejected/` and
    blocks every later-named file on every tick from then on. Same permanent wedge an unparseable
    file used to cause, reached through size rather than syntax.

    Asserted on `get_object` NOT being called, because a refusal that first downloads the file has
    not avoided the thing it exists to avoid.
    """
    # A real body over the ceiling, not a patched size: the point is that the bytes are never
    # fetched, and that only means something if the bytes are really there.
    s3 = _setup({"big.csv": "x" * (reader.MAX_FILE_BYTES + 1)})
    fetched = []
    real = s3.get_object

    def watch(Bucket, Key):
        fetched.append(Key)
        return real(Bucket=Bucket, Key=Key)

    s3.get_object = watch

    reader.handler({}, None)

    assert fetched == [], "the oversized file was downloaded before being refused"
    assert clients._sqs.sent == []
    reason = _reason(s3)
    assert str(reader.MAX_FILE_BYTES) in reason and "Split it" in reason, reason


def test_a_row_of_EMPTY_FIELDS_is_refused_rather_than_skipped():
    """A decision, not an accident, and the two reviewers of this change disagreed about it.

    `,,` carries no information, so skipping it loses nothing — that is the case for skipping. But
    the shapes next to it do carry information: `project,add,` is a row the operator started and
    did not finish, and dropping it silently is the failure this file's whole refusal vocabulary
    exists to prevent. The spec's own words settle it: "any blank field rejects the whole file
    naming the line", unqualified, and "wholly blank lines" means a blank LINE. So an empty record
    is refused, and the refusal names the line so the fix is obvious.

    Pinned because the cost is real: a spreadsheet writes `,,` for a cleared row inside its used
    range, so an operator can meet this without meaning to. Revisit the decision rather than
    deleting the test — and if it is revisited, skip only TRAILING empty records, never interior
    ones.
    """
    s3 = _setup({"cleared.csv": "space,action,username\nfinance,add,bcarter\n,,\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == []
    assert "line 3" in _reason(s3)


def test_a_file_saved_with_lone_CR_endings_parses_rather_than_raising():
    """`io.StringIO` defaults to universal-newline translation off for `\r`, and the csv module
    requires `newline=""`. Without it an old-Mac-style export raises instead of parsing."""
    _setup({"cr.csv": "space,action,username\rfinance,add,bcarter\r"})

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["finance"]


def test_a_rejected_file_does_not_stop_the_sweep():
    """`DONE` and `DEFERRED` are constants precisely so a typo cannot fall through to the skip.
    The opposite direction matters too: a rejected file returning `DEFERRED` would break the sweep
    at the first bad upload and emit a spurious "the rest of the inbox waits" warning."""
    s3 = _setup(
        {
            "a-bad.csv": "space,new_owner\nfinance,bcarter\n",
            "b-good.csv": "space,action,username\nsales,add,bcarter\n",
        }
    )

    result = reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["sales"]
    assert result["filesHandled"] == 2
    assert _keys(s3, reader.INBOX) == []


def test_ordinary_operator_formatting_is_accepted():
    """A blank line between rows and a header typed with spaces around the commas are both what a
    hand-written CSV looks like. Each is handled by one line in the parser, and neither line had a
    test — so either could be deleted and the suite would stay green while an ordinary file was
    refused."""
    _setup({"human.csv": " space , action , username \nfinance,add,bcarter\n\nsales,add,rsingh\n"})

    reader.handler({}, None)

    assert [(m["space"], m["payload"]["members"]) for m in _sent()] == [
        ("finance", ["bcarter"]),
        ("sales", ["rsingh"]),
    ]


def test_a_console_created_folder_marker_is_not_read_as_a_file():
    """The S3 console's "create folder" writes a zero-byte object AT the prefix. Read as a file it
    is refused as carrying not even a header, and `_move` would then build a destination key
    ending in `/` from an empty name."""
    s3 = _setup({"": ""})
    s3.store[("admin-bkt", f"{reader.INBOX}a.csv")] = b"space,action,username\nfinance,add,bcarter\n"

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["finance"]
    assert _keys(s3, reader.REJECTED) == [], "the folder marker was read as a file"


def test_the_readers_envelope_constants_agree_with_the_plane_they_are_for():
    """The reader ships without the domain layer, so both constants are local copies. Copies drift;
    this is what stops these two doing it silently.

    ``SCHEMA_VERSION`` disagreeing means every operator message is refused as an unsupported
    version. The group id disagreeing is worse — the messages are accepted and simply stop being
    ordered against the API's, which nothing else would report.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
    from apicommon import fifo

    import config as domain_config

    assert reader.SCHEMA_VERSION == domain_config.SCHEMA_VERSION
    assert fifo._group_shared_space(None, {}) == reader.MESSAGE_GROUP_ID
