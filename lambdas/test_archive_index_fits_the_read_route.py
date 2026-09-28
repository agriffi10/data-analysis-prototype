"""The archive plane's two numbers that another service has to be able to carry.

The archive index is written by the archive plane and read by the browser through the API's
object content route, and the archive name is sized by the plane and bounded again by the API.
Neither side imports the other, so the numbers are held together here, where both may be loaded
into one process.

**The index is measured at more than one fill, because the two limits have different worst
cases.** The route's stored cap counts the document's own bytes, where a control character in a
key — stored escaped, six bytes — costs most. Lambda's response ceiling counts the bytes the
route serves, after two more rounds of escaping, where an astral character costs most: four
stored bytes served as fourteen. One fill proves only its own limit.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "api"))
sys.path.insert(0, os.path.join(_HERE, "archive-common"))

from apicommon import bounds, envelope, s3_config
from arcommon import config, index_store

#: What the index's string fields are filled with in turn: plain ASCII as the control, a quote
#: and a control character for the stored bytes, an astral character for the served ones. A name
#: can hold neither a control character nor anything the rule refuses, so a name takes the
#: astral character in the fill that would otherwise refuse it.
_FILLS = ("k", '"', "\x01", "\U0001f600")

_UUID = "9f2c1b8e-1111-4222-8333-444444444444"


def _worst_entry(fill):
    name_fill = "\U0001f600" if fill == "\x01" else fill
    path = (fill * index_store.ITEM_PATH_MAX_CHARS)[: index_store.ITEM_PATH_MAX_CHARS]
    return {
        "archiveId": _UUID,
        "name": name_fill * config.ARCHIVE_NAME_MAX_CHARS,
        "archivedAt": "2026-09-28T12:34:56.789Z",
        "archivedBy": "a" * 63,
        "items": [{"kind": "folder", "path": path}] * index_store.ITEMS_SHOWN,
        "itemCount": config.ARCHIVE_MAX_ITEMS,
        "fileCount": config.ARCHIVE_MAX_OBJECTS,
        "totalBytes": config.ARCHIVE_MAX_BYTES,
        "restore": {
            "status": "incomplete",
            "requestedAt": "2026-09-28T12:34:56.789Z",
            "updatedAt": "2026-09-28T12:34:56Z",
        },
    }


def _stored(fill):
    document = {
        "version": index_store.INDEX_VERSION,
        "archives": [_worst_entry(fill)] * config.ARCHIVE_INDEX_MAX_ENTRIES,
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@pytest.mark.parametrize("fill", _FILLS, ids=["ascii", "quote", "control", "astral"])
def test_a_full_index_of_worst_case_entries_is_readable_through_the_content_route(fill):
    """Both limits the route applies, at the entry cap, with headroom deliberately left.

    The headroom is kept on purpose rather than spent on a larger cap: an index the route refuses
    is an index the browser cannot read at all, and every archive in the space loses its label at
    once. Run this with the sizes printed before raising the cap.
    """
    stored = _stored(fill)
    served = envelope.served_bytes({"body": stored.decode("utf-8"), "etag": "0" * 32})

    assert len(stored) <= s3_config.MAX_DOCUMENT_BYTES, (
        f"at {fill!r} a full index stores {len(stored):,} bytes, over the route's "
        f"{s3_config.MAX_DOCUMENT_BYTES:,}-byte cap"
    )
    assert served <= envelope.LAMBDA_RESPONSE_BYTES, (
        f"at {fill!r} a full index serves {served:,} bytes, over Lambda's "
        f"{envelope.LAMBDA_RESPONSE_BYTES:,}-byte response ceiling"
    )


def test_the_measured_fills_really_are_each_limits_worst_case():
    """Guard the guard: if another fill were worse for either limit, the test above sampled the
    wrong ones and its green would say nothing about the limit it missed."""
    stored = {fill: len(_stored(fill)) for fill in _FILLS}
    served = {
        fill: envelope.served_bytes({"body": _stored(fill).decode("utf-8"), "etag": ""})
        for fill in _FILLS
    }

    assert max(stored, key=stored.get) == "\x01"
    assert max(served, key=served.get) == "\U0001f600"


def test_the_apis_name_bound_is_the_planes_cap_at_the_worst_escaping():
    """A hundred code points, each at most twelve bytes under ``ensure_ascii``, plus two quotes.

    The API does not import the plane, so it writes the hundred down; this is what holds the two
    copies together.
    """
    assert bounds.MAX_ARCHIVE_NAME_BYTES == config.ARCHIVE_NAME_MAX_CHARS * 12 + 2
    assert len(json.dumps("\U0001f600" * config.ARCHIVE_NAME_MAX_CHARS)) == bounds.MAX_ARCHIVE_NAME_BYTES
