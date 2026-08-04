"""Where the table-builder's Athena statements write their results (SPEC-070).

Extracted from ``execute_ddl._results_location`` by SPEC-144 so ``apply-refresh`` uses the
SAME construction rather than a second one derived from prose. The two verbs run DDL
against the same databases under the same role, and a results prefix that differs between
them is the kind of divergence that only shows up as a Lake Formation denial on whichever
path is exercised less.
"""


def results_location(space: dict, actor: str) -> str:
    """``s3://{bucket}/{database}/athenaresults/{actor}/`` for either space kind.

    Personal ⇒ the user's own prefix; shared ⇒ under the space's DB root, consistent with
    the SPEC-055 shared-results routing (``{database}/athenaresults/{username}/``).
    """
    return f"s3://{space['bucket']}/{space['database']}/athenaresults/{actor}/"
