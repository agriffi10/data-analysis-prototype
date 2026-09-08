"""The archive plane's user-facing wording.

SPEC-106: raw AWS text is never shown. The detail on a terminal error is for the logs and the
Step Functions record; the sentence a user reads is composed here.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import messages


def test_every_marker_in_every_body_can_be_filled_by_somebody():
    """A marker no caller supplies renders BLANK (`blank_unfilled=True`), which reads as a
    typo in the sentence rather than as a bug — so it must be caught here."""
    fillable = {
        "maxItems",
        "maxObjects",
        "itemName",
        "copied",
        "total",
        "failed",
        "residue",
        "requestId",
        "folderName",
        # SPEC-170's restore refusals. Every one is filled from its raise site — the id the user
        # pasted, the space they named, the two counts and the collision sample are all facts of
        # one request rather than properties this plane can know.
        "archiveId",
        "spaceName",
        "expected",
        "found",
        "sample",
        # SPEC-171's partial restore, filled by update-receipt from the collector's own
        # verdict — how many objects actually landed is a fact of one run, not of this plane.
        "restored",
    }
    for reason, body in messages._BODIES.items():
        for marker in re.findall(r"\{(\w+)\}", body):
            assert marker in fillable, f"{reason} names {{{marker}}}, which nothing supplies"


#: The ONE outcome on this plane that is genuinely partial, and it is SPEC-171's asymmetry
#: rather than a slipped standard. Every other code here refuses whole because it CAN: the
#: archive's commit gate means nothing was deleted, and a refused restore has written nothing.
#: A partial RESTORE cannot be made whole in either direction — the user's space already holds
#: some of their own data, and deleting it to make the operation atomic would destroy the very
#: thing the restore was for — so its body has to say so.
_DELIBERATELY_PARTIAL = {"restore_incomplete"}


def test_no_body_promises_a_partial_outcome_except_the_one_that_is():
    """Every refusal on this plane but one is a WHOLE-request refusal, which is what makes
    "nothing was archived" and "nothing was changed in your space" true in almost every sentence
    this table can produce. A body implying part of the request went through would be wrong for
    every code outside the exemption.

    The exemption is a SET rather than a skipped assertion so that a second body drifting into
    partial wording has to be argued for here, beside the reasoning, rather than merely passing.
    """
    for reason, body in messages._BODIES.items():
        if reason in _DELIBERATELY_PARTIAL:
            continue
        assert "some of" not in body.lower(), reason
        assert "were restored" not in body.lower(), reason

