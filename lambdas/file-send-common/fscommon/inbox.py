"""What a recipient's inbox already holds from one sender.

The conflict guard asks one question — *is any of the names this send would create
already taken?* — and this module answers it with a **delimited listing of the inbox prefix**
rather than a probe per selected item.

**The listing shape is the whole point, and the obvious alternative is wrong twice over.**
Probing ``{inbox}{item}`` per item costs two round trips each (the exact key for a file item,
the ``{key}/`` prefix for a folder one) — 200 items against a 50-recipient guard Map is 20,000
serial calls. And a single ``MaxKeys=1`` listing at ``Prefix={inbox}{item}`` cannot answer it at
all: S3 returns keys in lexicographic order and ``/`` (0x2F) is not the lowest byte a key may
carry, so ``notes.txt-old`` sorts BEFORE ``notes.txt/part-0`` and the one key returned says
"clear" over a destination that is occupied. A delimiter listing sidesteps both: one page per
1,000 things the sender has previously sent to that recipient, and every first-level name
exactly as the recipient sees it.

A name here is a name whatever it holds. A previous send of the FILE ``notes.txt`` conflicts
with a new send of the FOLDER ``notes.txt/`` and vice versa, because the destination key builder
gives both the same base — and "merge into what is there" is not a behaviour this plane has
(out of scope).
"""

from cpcommon import clients
from cpcommon.errors import TransientError

from .paths import inbox_prefix


def existing_item_names(bucket: str, target_root: str, sender: str) -> set:
    """Lists the item names one sender's inbox already holds in a recipient's space.

    Args:
      bucket: The recipient's bucket — user-space or shared-space.
      target_root: The recipient's space root prefix.
      sender: The verified sender's username, which namespaces the inbox.

    Returns:
      The first-level names under ``{targetRoot}shared_files/{sender}/``, folders and files
      alike, with no trailing slash on either. Empty when the sender has never sent to this
      recipient — which is the ordinary case and costs one listing.

    Raises:
      TransientError: On ANY listing fault, deliberately including the deterministic ones. A
        guard that cannot see the destination must retry and then refuse the recipient; it must
        never fall through to "nothing is there", which is the one answer that ends in an
        overwrite.
      TerminalError: ``forbidden`` from the prefix builder for an empty root or sender.
    """
    prefix = inbox_prefix(target_root, sender)
    names: set = set()
    try:
        for page in clients.s3().get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix, Delimiter="/"
        ):
            for entry in page.get("CommonPrefixes") or []:
                names.add(entry["Prefix"][len(prefix) :].rstrip("/"))
            for entry in page.get("Contents") or []:
                names.add(entry["Key"][len(prefix) :])
    except Exception as exc:
        raise TransientError(f"list {bucket}/{prefix} failed: {exc}") from exc
    names.discard("")
    return names
