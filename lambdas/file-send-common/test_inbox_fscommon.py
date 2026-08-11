"""What a recipient's inbox already holds, and why it is read with a delimiter (SPEC-166 FR-001).

Runnable under pytest or directly: python3 test_inbox_fscommon.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from fscommon import inbox


class _FakeS3:
    """An S3 that pages a delimited listing the way the real one does.

    The delimiter behaviour is REPRODUCED rather than stubbed — first-level names come back as
    ``CommonPrefixes`` and deeper ones do not appear at all — because that is the property the
    module depends on, and a fake that returned every key would let a wrong implementation pass.
    """

    def __init__(self, keys, page_size=1000, error=None):
        self._keys = sorted(keys)
        self._page_size = page_size
        self._error = error
        self.calls = []

    def get_paginator(self, name):
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix, Delimiter):
                fake.calls.append({"Bucket": Bucket, "Prefix": Prefix, "Delimiter": Delimiter})
                if fake._error:
                    raise fake._error
                prefixes, contents = [], []
                for key in fake._keys:
                    if not key.startswith(Prefix):
                        continue
                    rest = key[len(Prefix) :]
                    head, sep, _ = rest.partition(Delimiter)
                    if sep:
                        entry = {"Prefix": f"{Prefix}{head}{Delimiter}"}
                        if entry not in prefixes:
                            prefixes.append(entry)
                    else:
                        contents.append({"Key": key, "Size": 1})
                entries = [("CommonPrefixes", p) for p in prefixes] + [("Contents", c) for c in contents]
                for start in range(0, max(len(entries), 1), fake._page_size):
                    page = entries[start : start + fake._page_size]
                    yield {
                        "CommonPrefixes": [e for kind, e in page if kind == "CommonPrefixes"],
                        "Contents": [e for kind, e in page if kind == "Contents"],
                    }

        return _P()


def _install(keys, page_size=1000, error=None):
    fake = _FakeS3(keys, page_size, error)
    clients._s3 = fake
    return fake


def test_an_empty_inbox_is_the_ordinary_case_and_costs_one_listing():
    fake = _install(["bob/other.csv"])

    assert inbox.existing_item_names("user-bkt", "bob/", "alice") == set()
    assert len(fake.calls) == 1


def test_a_folder_and_a_file_both_read_as_taken_names():
    """A name is a name whatever it holds: the destination builder gives a file item and a
    folder item the same base, so "merge into what is there" is not on the table."""
    _install(
        [
            "bob/shared_files/alice/reports/2026/q1.csv",
            "bob/shared_files/alice/notes.txt",
        ]
    )

    assert inbox.existing_item_names("user-bkt", "bob/", "alice") == {"reports", "notes.txt"}


def test_only_this_senders_inbox_is_read():
    """The prefix is namespaced by sender, so two senders can use the same item name — which is
    the whole reason the layout carries the sender at all."""
    _install(
        [
            "bob/shared_files/alice/notes.txt",
            "bob/shared_files/carol/budget.csv",
            "bob/reports/notes.txt",
        ]
    )

    assert inbox.existing_item_names("user-bkt", "bob/", "alice") == {"notes.txt"}


def test_a_sibling_that_merely_starts_the_same_way_is_not_the_same_name():
    """The failure a per-item ``MaxKeys=1`` probe at ``Prefix={inbox}{item}`` would produce in
    reverse. S3 orders keys lexicographically and ``-`` (0x2D) sorts BELOW ``/`` (0x2F), so such
    a probe returns ``notes.txt-old`` and reads "clear" over an occupied destination. Listing the
    inbox with a delimiter gives whole names, where ``notes.txt-old`` is simply a different one."""
    _install(["bob/shared_files/alice/notes.txt-old"])

    names = inbox.existing_item_names("user-bkt", "bob/", "alice")

    assert names == {"notes.txt-old"}
    assert "notes.txt" not in names


def test_the_listing_pages_past_the_first_thousand_names():
    """Bounded by what this sender has previously sent to this recipient, not by the send — and
    a sender who has sent a thousand items before is exactly who must not get a wrong answer."""
    _install(
        [f"bob/shared_files/alice/item{n:04d}/data.csv" for n in range(1500)],
        page_size=1000,
    )

    assert len(inbox.existing_item_names("user-bkt", "bob/", "alice")) == 1500


def test_a_placeholder_object_at_the_inbox_root_is_not_a_name():
    """A zero-byte marker at the inbox prefix itself yields an empty relative key, which would
    otherwise become the empty item name and collide with nothing legitimately."""
    _install(["bob/shared_files/alice/"])

    assert inbox.existing_item_names("user-bkt", "bob/", "alice") == set()


def test_a_listing_fault_is_transient_rather_than_an_empty_inbox():
    """The one answer a broken guard must never give. Falling through to "nothing is there" ends
    in an overwrite; retrying and then failing the recipient does not."""
    _install([], error=RuntimeError("boom"))

    with pytest.raises(TransientError):
        inbox.existing_item_names("user-bkt", "bob/", "alice")


@pytest.mark.parametrize("root,sender", [("", "alice"), ("/", "alice"), ("bob/", "")])
def test_an_unusable_prefix_refuses_rather_than_listing_something_wider(root, sender):
    """An empty sender lists EVERY sender's inbox, and the guard would then refuse a name a
    different sender had used — a refusal the recipient could not act on."""
    _install([])

    with pytest.raises(TerminalError):
        inbox.existing_item_names("user-bkt", root, sender)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
