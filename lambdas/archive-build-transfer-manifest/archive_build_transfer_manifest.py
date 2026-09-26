"""build-transfer-manifest — the Distributed Map's dataset.

Takes the copy plan inspect-source wrote and turns it into one JSON Lines item per object, in the
shape ``cpcommon.transfer`` copies: source and destination, the size the plan measured, and — new
on this plane — the destination STORAGE CLASS. The Map fans out over those items, so an archive's
ceiling is the manifest's length rather than one Lambda's timeout.

**Every destination comes from ``arcommon.paths.archived_key``**, called once per object. This
verb composes no key of its own: the archived key is what a restore reconstructs an origin from,
so a builder that disagreed with it would put objects where the restore looks for something else
— and the disagreement would surface as a restore writing to the wrong place, not as a failure.

**The storage class comes from ``config.ARCHIVE_STORAGE_CLASS`` and is never a literal here.** It
is the choice the whole arc is shaped by (a GLACIER object cannot be copied at all until a billed,
hours-long retrieval has finished), and a second home for it is how one verb archives to a class
the restore path was not built for.

**Every line says whether it is a folder placeholder, and the block says how many are files.**
The flag and the count come from ``arcommon.counts`` in the same pass over the same keys, so
they cannot disagree. The flag rides each copy failure back to the collector, which is how a
sentence about a shortfall can count files; the count rides the ``transfer`` block to every later
state, which is how the notifications and the receipt name files rather than objects. The Map
still iterates every line, placeholders included, because an archived empty folder has to come
back.

The service name is the control plane, not the function, so one archive's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import counts, notify, paths, plan
from arcommon.config import ARCHIVE_STORAGE_CLASS
from cpcommon import config, observability
from cpcommon.transfer import manifest as manifest_writer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


def _items(loaded: dict) -> list:
    """Expands the copy plan into the Map's transfer items.

    Args:
      loaded: The copy plan, carrying its source and archive locations and its objects.

    Every line is pinned to the ETag the plan recorded, so the vault holds exactly the version
    delete-source later checks the original against; a file changed before its copy fails that
    item and the commit gate rolls the archive back. A plan entry with no tag gives an unpinned
    line, and delete-source keeps that original.

    Returns:
      One transfer item per planned object, each flagged as a folder placeholder or not.

    Raises:
      TerminalError: ``forbidden`` from the destination builder for an object that does not sit
        inside the source root — unreachable from a plan the expansion wrote, and a refusal
        rather than a slice, because a mis-rooted key would archive an object whose restore put
        it back somewhere else.
    """
    source, archive = loaded["source"], loaded["archive"]
    src_root = source["root"]
    return [
        {
            "srcBucket": source["bucket"],
            "srcKey": f"{src_root}{entry['relKey']}",
            "destBucket": archive["bucket"],
            "destKey": paths.archived_key(
                archive["root"], src_root, f"{src_root}{entry['relKey']}"
            ),
            "size": entry.get("bytes") or 0,
            "storageClass": ARCHIVE_STORAGE_CLASS,
            counts.FOLDER_FIELD: counts.is_folder_placeholder(entry["relKey"]),
            **({"srcEtag": entry["etag"]} if entry.get("etag") else {}),
        }
        for entry in loaded["objects"]
    ]


@observability.traced("build-transfer-manifest")
@notify.notifies_on_failure("manifest")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the transfer manifest and reports its item count.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the copy plan's key and the stamped execution context.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transfer`` block naming the manifest, the results prefix, the item
      count the Choice gates the Map on and how many of those items are files.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the copy plan cannot be
        read or is not this run's, ``malformed_event`` when the execution name was not
        stamped, or ``forbidden`` from the destination builder.
        Whole-request either way — a manifest that cannot be built completely must not be built
        partially, because the commit gate compares the export against the plan and a short
        manifest would agree with itself.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    return _build_transfer_manifest(event)


def _build_transfer_manifest(event) -> dict:
    """Loads the plan, builds the items and writes them as JSON Lines.

    Args:
      event: The request with its copy plan key.

    Returns:
      The request with its ``transfer`` block.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded``, ``malformed_event`` or
        ``forbidden``.
      TransientError: On a retryable S3 fault.
    """
    loaded = plan.load(event.get("copyPlanKey"), event)
    items = _items(loaded)
    key = plan.transfer_manifest_key(event, (event.get("execution") or {}).get("name"))
    count = manifest_writer.write_manifest(config.ADMIN_BUCKET, key, items)

    logger.info("transfer manifest %s: %d items", key, count)
    observability.info(
        "transfer manifest built",
        items=count,
        bytes=loaded.get("totalBytes"),
        storage_class=ARCHIVE_STORAGE_CLASS,
    )
    return {
        **event,
        "transfer": {
            "manifestBucket": config.ADMIN_BUCKET,
            "manifestKey": key,
            "resultsBucket": config.ADMIN_BUCKET,
            "resultsPrefix": plan.transfer_results_prefix(event),
            "itemCount": count,
            counts.FILE_COUNT_FIELD: sum(1 for item in items if not item[counts.FOLDER_FIELD]),
        },
    }
