"""The four Athena routes, and the assertions that moved here from the browser.

Three of this repo's most expensive lessons live in this surface, and each of them ships GREEN when
it is broken. Results read before an execution finished reached users as "Contact the
Administrator" on an ordinary first load. A SQL NULL collapsed to the empty string destroyed a
distinction no consumer can rebuild. The disclosed SQL is trusted because it is the same bytes
Athena received, and a statement mangled by a ``strip()`` still runs and still looks right.

So the assertions here are on the REASON — the mapped code, the raw body text, the byte
comparison — never on "something failed" or on a call count alone.
"""

import json

import pytest
import router
from apicommon import identity
from conftest import bearer


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    ``botocore`` is provided by the Lambda runtime and declared as a dependency nowhere, so it is
    absent in CI: importing it passes on a laptop that happens to have boto3 and fails on the
    runner. The classifier reads ``response["Error"]``, which is all the shape this needs.
    """

    def __init__(self, code, message=""):
        """Builds the error.

        Args:
          code: The service error code.
          message: The service's own message, which must reach no response body and no log field.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": message}}


class StubAthena:
    """An Athena client recording every call and answering from what a test programmed.

    Attributes:
      calls: Each call as ``(operation, kwargs)``, so a test can assert what was sent and HOW
        MANY times — the count is on this client rather than on botocore, because the assumed
        session is cached per container and an ``sts:AssumeRole`` fires on some invocations and
        not others.
    """

    def __init__(self, **answers):
        """Builds the stub.

        Args:
          **answers: Operation name to the response it returns, or to an exception it raises.

        Returns:
          None.

        Raises:
          None.
        """
        self._answers = answers
        self.calls = []

    def _answer(self, operation, kwargs):
        """Records one call and produces its answer.

        Args:
          operation: The botocore operation name.
          kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        self.calls.append((operation, kwargs))
        answer = self._answers.get(operation, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def start_query_execution(self, **kwargs):
        """Starts a query.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("start_query_execution", kwargs)

    def get_query_execution(self, **kwargs):
        """Reads an execution's status.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_query_execution", kwargs)

    def get_query_results(self, **kwargs):
        """Reads a page of results.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_query_results", kwargs)

    def stop_query_execution(self, **kwargs):
        """Stops an execution.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("stop_query_execution", kwargs)


@pytest.fixture(autouse=True)
def _athena_environment(monkeypatch):
    """The two values the start route derives from, both required.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("ATHENA_WORKGROUP", "dat-prod-portal-wg")
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")


@pytest.fixture
def athena(monkeypatch):
    """Installs a stub Athena client as the user plane.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      A function taking the stub to install and returning it.

    Raises:
      None.
    """

    def _install(stub):
        """Installs one stub.

        Args:
          stub: The client to serve.

        Returns:
          The stub.

        Raises:
          None.
        """
        monkeypatch.setattr(identity, "user_client", lambda service, acting_as: stub)
        return stub

    return _install


def _body(answer):
    """The parsed response body.

    Args:
      answer: The router's response.

    Returns:
      The decoded body.

    Raises:
      None.
    """
    return json.loads(answer["body"])


class TestStart:
    """FR-002 — the wire carries no identity, no bucket and no workgroup."""

    def test_the_wire_has_NOWHERE_to_name_a_user_a_bucket_or_a_workgroup(self, athena) -> None:
        """The strongest form of "the request cannot move the identity": it is refused, not ignored.

        The spec asks for a fixture whose body and query disagree with the claim. The contract
        makes that unexpressible — the body's declared shape is ``{sql, database?}`` and the route
        declares no query at all, so both are 400 before a handler runs. Asserted rather than
        left implicit, because "the field is ignored" and "the field cannot be sent" are different
        guarantees and only one of them survives someone adding a key later.
        """
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        with_body = router.route(
            "POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1", "username": "mallory"}
        )
        with_query = router.route(
            "POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1"}, {"username": "mallory"}
        )

        assert with_body["statusCode"] == 400
        assert _body(with_body)["error"]["code"] == "InvalidRequest"
        assert with_query["statusCode"] == 400

    def test_the_results_location_FOLLOWS_the_verified_claim(self, athena) -> None:
        """Two callers, two prefixes, one route.

        A single-token fixture cannot tell a route reading the claim from one that hard-codes a
        prefix or reads a constant — both pass. Driving two different tokens through the same
        route is what makes the source of the username observable.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1"})
        router.route("POST", "/v1/queries", bearer("bob_smith"), "rq", {"sql": "SELECT 1"})

        assert [call[1]["ResultConfiguration"]["OutputLocation"] for call in stub.calls] == [
            "s3://dat-prod-user-space/alice/system_settings/athenaresults/",
            "s3://dat-prod-user-space/bob_smith/system_settings/athenaresults/",
        ]

    def test_the_workgroup_comes_from_the_environment(self, athena) -> None:
        """A defaulted workgroup would send queries to Athena's own ``primary``.

        Its results location is the account default, which is a write outside the isolation model
        by a query that otherwise succeeds.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert stub.calls[0][1]["WorkGroup"] == "dat-prod-portal-wg"

    def test_an_unset_workgroup_is_a_server_fault_rather_than_a_default(
        self, athena, monkeypatch
    ) -> None:
        """Failing loudly here beats succeeding quietly against the wrong workgroup."""
        monkeypatch.delenv("ATHENA_WORKGROUP")
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 503
        assert _body(answer)["error"]["code"] == "ApiUnavailable"

    def test_no_database_means_the_context_is_ABSENT_not_empty(self, athena) -> None:
        """Queries carry no active database, so every base table is fully qualified.

        A present-but-empty context changes what resolves, which is why the key has to be gone
        rather than blank.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert "QueryExecutionContext" not in stub.calls[0][1]

    def test_a_database_is_sent_when_one_is_given(self, athena) -> None:
        """The two callers that send one are View DDL and a user's own DDL run."""
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route(
            "POST", "/v1/queries", bearer(), "rq", {"sql": "SHOW CREATE TABLE a.b", "database": "a"}
        )

        assert stub.calls[0][1]["QueryExecutionContext"] == {"Database": "a"}

    @pytest.mark.parametrize(
        "statement",
        [
            "SELECT 1\n",
            "\nSELECT 1",
            "SELECT * FROM t WHERE name = 'O''Brien'",
            "SELECT 1 -- a comment",
            "SELECT ';' AS semi",
            "SELECT\t1",
            "SELECT 'café' AS accented",
        ],
        ids=["trailing newline", "leading blank", "doubled quote", "comment", "embedded semicolon", "tab", "non-ascii"],
    )
    def test_the_statement_reaches_athena_BYTE_IDENTICAL(self, athena, statement) -> None:
        """FR-009. The disclosure is trusted because it is the same bytes.

        A statement mangled by a ``strip()`` still runs, still returns rows and still looks right
        in the Generated SQL panel — only the byte comparison catches it.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": statement})

        assert stub.calls[0][1]["QueryString"] == statement

    def test_a_body_naming_a_field_the_contract_does_not_declare_is_REFUSED(self, athena) -> None:
        """Ignoring an unknown key is how a field comes back."""
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        answer = router.route(
            "POST",
            "/v1/queries",
            bearer(),
            "rq",
            {"sql": "SELECT 1", "outputLocation": "s3://elsewhere/"},
        )

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_athena_returning_no_execution_id_is_an_INTERNAL_error(self, athena) -> None:
        """It replaces a client-minted code that reached the generic sentence by fallthrough."""
        athena(StubAthena(start_query_execution={}))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 500
        assert _body(answer)["error"]["code"] == "InternalError"

    @pytest.mark.parametrize(
        "message",
        [
            "line 1:8: mismatched input 'FROM'",
            "SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved",
            "parse error at line 2",
        ],
        ids=["mismatched input", "syntax_error", "parse error"],
    )
    def test_a_statement_the_USER_can_fix_gets_its_own_code(self, athena, message) -> None:
        """The generic sentence is for what a user cannot act on, and this is the opposite.

        Athena rejects some statements at submit and accepts others that then fail; the user
        typed the same mistake either way. Under a single ``InvalidRequest`` the first group read
        "Something went wrong. Contact the Administrator." while the second read "There is a
        syntax error in your query" — the same mistake, two sentences, and the unhelpful one for
        the case where the app knows exactly what is wrong.
        """
        athena(StubAthena(start_query_execution=_ServiceError("InvalidRequestException", message)))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELEC 1"})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "QuerySyntaxError"
        assert message not in answer["body"]

    @pytest.mark.parametrize(
        "message",
        ["WorkGroup dat-prod-portal-wg is not found", "The request was not valid"],
        ids=["unusable workgroup", "malformed request"],
    )
    def test_a_refusal_the_user_can_do_NOTHING_about_stays_generic(self, athena, message) -> None:
        """The counter-case, and the reason the classifier reads the message rather than the name.

        An unusable workgroup and a malformed request parameter arrive under the same exception
        name as a bad statement and are an operator's to fix, not a user's. Telling someone to
        check their SQL for a workgroup misconfiguration sends them hunting for a mistake that is
        not there — the failure mode of a rule that maps the whole family to the friendlier
        sentence.
        """
        athena(StubAthena(start_query_execution=_ServiceError("InvalidRequestException", message)))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_a_denial_at_submit_is_still_a_denial(self, athena) -> None:
        """The 400 arm is one exception name wide, not "any failure is a bad request"."""
        athena(StubAthena(start_query_execution=_ServiceError("AccessDeniedException", "no")))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    def test_the_route_makes_exactly_one_call_on_the_athena_client(self, athena) -> None:
        """Counted on THIS client, never on botocore as a whole.

        The assumed session is cached per container, so an ``sts:AssumeRole`` fires on a cold
        invocation and not on a warm one — "one botocore call per request" is unsatisfiable on
        the first request and satisfiable on the second.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert len(stub.calls) == 1


class TestStatus:
    """FR-003 — the engine's own text travels verbatim, on a 200."""

    def test_a_FAILED_execution_is_a_200_carrying_the_reason(self, athena) -> None:
        """Mapping it to an error envelope is the change that looks most correct.

        It would retire six authored sentences at once: the browser chooses each of them by
        reading this field, and an envelope has nowhere to put it.
        """
        reason = "Insufficient Lake Formation permission(s): Required SELECT on table x"
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {
                        "Status": {"State": "FAILED", "StateChangeReason": reason},
                        "Statistics": {"DataScannedInBytes": 10, "EngineExecutionTimeInMillis": 5},
                    }
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["stateChangeReason"] == reason

    def test_the_reason_is_not_truncated_or_rewritten(self, athena) -> None:
        """A reason truncated at 100 characters is present and still breaks the wording rules."""
        reason = "SYNTAX_ERROR: line 1:8: Column 'foo' cannot be resolved" + " " + "x" * 200
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": reason}}
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert _body(answer)["stateChangeReason"] == reason

    def test_a_non_terminal_execution_reports_NULL_statistics_never_zero(self, athena) -> None:
        """A confident zero freezes the tab's cost figure at zero for the whole run."""
        athena(StubAthena(get_query_execution={"QueryExecution": {"Status": {"State": "QUEUED"}}}))

        body = _body(router.route("GET", "/v1/queries/e-1", bearer(), "rq"))

        assert body["dataScannedBytes"] is None
        assert body["engineExecutionTimeMillis"] is None

    def test_a_missing_state_defaults_to_QUEUED(self, athena) -> None:
        """As the browser has always done."""
        athena(StubAthena(get_query_execution={"QueryExecution": {}}))

        assert _body(router.route("GET", "/v1/queries/e-1", bearer(), "rq"))["state"] == "QUEUED"

    def test_the_output_location_survives_for_a_succeeded_execution(self, athena) -> None:
        """Export copies that object and Save results parses it."""
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {
                        "Status": {"State": "SUCCEEDED"},
                        "ResultConfiguration": {"OutputLocation": "s3://b/alice/athenaresults/e.csv"},
                    }
                }
            )
        )

        body = _body(router.route("GET", "/v1/queries/e-1", bearer(), "rq"))

        assert body["outputLocation"] == "s3://b/alice/athenaresults/e.csv"

    def test_the_execution_id_comes_from_the_path_and_costs_ONE_call(self, athena) -> None:
        """Reaches botocore unchanged, and exactly once.

        The count is list equality rather than an index, because ``calls[0]`` is silent about a
        second call — and a second call here is a doubled bill on a route the browser polls
        every 1.5 seconds.
        """
        stub = athena(StubAthena(get_query_execution={"QueryExecution": {}}))

        router.route("GET", "/v1/queries/e-99", bearer(), "rq")

        assert stub.calls == [("get_query_execution", {"QueryExecutionId": "e-99"})]


class TestResults:
    """FR-004 and FR-005 — the page, the NULL, and the read that came too early."""

    def test_a_null_cell_and_an_empty_one_are_distinct_in_the_RAW_body(self, athena) -> None:
        """Asserted on the response TEXT, not on a parsed structure.

        ``d.get("VarCharValue", "")`` is indistinguishable from the right implementation for
        every non-null cell and for every fixture that has no NULLs — and it destroys what the
        Value panel, the null styling and the copy path all read.
        """
        athena(
            StubAthena(
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {
                            "ColumnInfo": [{"Name": "a", "Type": "varchar"}, {"Name": "b", "Type": "varchar"}]
                        },
                        "Rows": [{"Data": [{}, {"VarCharValue": ""}]}],
                    }
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert '"rows": [[null, ""]]' in answer["body"]

    def test_the_first_page_overfetches_by_one_and_nets_999_at_the_maximum(self, athena) -> None:
        """The existing arithmetic, moved.

        At 1000 the ``+1`` is clamped away, so page one nets 999 data rows after the header goes.
        Callers number rows from actual page lengths and must keep being allowed to see pages
        that are not uniform.
        """
        stub = athena(StubAthena(get_query_results={"ResultSet": {}}))

        router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": "1000"})

        assert stub.calls[0][1]["MaxResults"] == 1000

    def test_a_continuation_page_asks_for_exactly_the_page_size(self, athena) -> None:
        """Only the first page carries Athena's repeated header row."""
        stub = athena(StubAthena(get_query_results={"ResultSet": {}}))

        router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": "20", "nextToken": "t"}
        )

        assert stub.calls[0][1]["MaxResults"] == 20

    def test_the_header_row_is_dropped_on_the_first_page_only(self, athena) -> None:
        """Athena repeats the column names as row one of page one of a SELECT."""
        result_set = {
            "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar"}]},
            "Rows": [{"Data": [{"VarCharValue": "a"}]}, {"Data": [{"VarCharValue": "1"}]}],
        }
        athena(StubAthena(get_query_results={"ResultSet": result_set}))

        first = _body(router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {}))
        later = _body(
            router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"nextToken": "t"})
        )

        assert first["rows"] == [["1"]]
        assert later["rows"] == [["a"], ["1"]]

    def test_a_first_data_row_equal_to_the_header_is_ALSO_dropped(self, athena) -> None:
        """Today's accepted foot-gun, preserved rather than quietly fixed.

        Fixing it is a behaviour change and belongs to whichever spec wants the behaviour.
        """
        athena(
            StubAthena(
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar"}]},
                        "Rows": [{"Data": [{"VarCharValue": "a"}]}],
                    }
                }
            )
        )

        body = _body(router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {}))

        assert body["rows"] == []

    def test_a_statement_with_no_result_set_is_an_empty_200(self, athena) -> None:
        """A DDL or CTAS statement produced no rows; that is not an error."""
        athena(StubAthena(get_query_results={}))

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert _body(answer) == {"columns": [], "rows": [], "nextToken": None}

    def test_the_column_type_is_athenas_raw_string(self, athena) -> None:
        """Normalising it is the browser's job and stays there."""
        athena(
            StubAthena(
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar(255)"}]}
                    }
                }
            )
        )

        body = _body(router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {}))

        assert body["columns"] == [{"name": "a", "type": "varchar(255)"}]

    def test_the_continuation_token_round_trips_unmodified(self, athena) -> None:
        """Over the three characters that break a re-encoder."""
        awkward = "a+b/c=="
        stub = athena(
            StubAthena(get_query_results={"ResultSet": {}, "NextToken": awkward})
        )

        body = _body(
            router.route(
                "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"nextToken": awkward}
            )
        )

        assert stub.calls[0][1]["NextToken"] == awkward
        assert body["nextToken"] == awkward

    def test_the_route_makes_exactly_ONE_call_and_a_denial_is_still_a_denial(self, athena) -> None:
        """Two properties the other tests here are silent about.

        ``calls[0]`` indexing cannot see a second call, and this is the route the row-count walk
        drives a thousand times over a large result. The denial arm matters because the
        classifier this route adds sits in front of it: a Lake Formation refusal must fall
        through to the 403, not be swallowed by the not-finished branch.
        """
        stub = athena(StubAthena(get_query_results={"ResultSet": {}}))
        router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})
        assert len(stub.calls) == 1

        denied = athena(
            StubAthena(get_query_results=_ServiceError("AccessDeniedException", "no"))
        )
        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert len(denied.calls) == 1
        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    @pytest.mark.parametrize("value", ["0", "1001", "-1", "abc", "1.5"], ids=list("abcde"))
    def test_a_page_size_outside_its_range_is_refused(self, athena, value) -> None:
        """The browser never sends one, which is exactly why the check must exist here."""
        athena(StubAthena(get_query_results={"ResultSet": {}}))

        answer = router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": value}
        )

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_a_read_before_the_execution_finished_is_409_QueryNotFinished(self, athena) -> None:
        """The condition that reached users as "Contact the Administrator" on a first load."""
        athena(
            StubAthena(
                get_query_results=_ServiceError(
                    "InvalidRequestException",
                    "Query has not yet finished. Current state: QUEUED",
                )
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 409
        assert _body(answer)["error"]["code"] == "QueryNotFinished"

    def test_a_malformed_query_is_400_InvalidRequest(self, athena) -> None:
        """The counter-case, in the same file as the one above.

        ``InvalidRequestException`` is BOTH conditions' exception name. A mapper keyed on the name
        passes whichever of the two it is shown — which is precisely how the original defect
        survived — so the pair has to be asserted together.
        """
        athena(
            StubAthena(
                get_query_results=_ServiceError(
                    "InvalidRequestException", "line 1:8: mismatched input 'FROM'"
                )
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_no_athena_message_reaches_the_response_body(self, athena) -> None:
        """The route reads the engine's message to classify and hands on none of it."""
        athena(
            StubAthena(
                get_query_results=_ServiceError(
                    "InvalidRequestException",
                    "Query has not yet finished. Current state: QUEUED for alice_secret_table",
                )
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert "alice_secret_table" not in answer["body"]


class TestStop:
    """FR-006 — one call, no body, and what it does not authorize."""

    def test_it_passes_only_the_path_id_and_consults_nothing_else(self, athena) -> None:
        """The API adds no ownership check and removes none.

        Athena authorizes this by WORKGROUP and this deployment has one, so a caller holding
        another user's execution id can already stop it. That is a preserved exposure recorded
        against the spec — a real fix needs an execution-to-owner record that does not exist —
        and what ships instead is attribution on the span.
        """
        stub = athena(StubAthena(stop_query_execution={}))

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {}
        assert stub.calls == [("stop_query_execution", {"QueryExecutionId": "e-7"})]

    def test_stopping_an_already_terminal_execution_is_a_success(self, athena) -> None:
        """The poller observes the terminal state either way, and today's caller swallows this."""
        athena(
            StubAthena(
                stop_query_execution=_ServiceError(
                    "InvalidRequestException", "Query has already completed"
                )
            )
        )

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 200

    def test_a_denial_is_still_a_denial(self, athena) -> None:
        """The forgiving arm is one exception name wide, not "any failure is fine"."""
        athena(StubAthena(stop_query_execution=_ServiceError("AccessDeniedException", "no")))

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"
