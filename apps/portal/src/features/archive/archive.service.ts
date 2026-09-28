import {wireBytes} from '../../lib/wireBytes';
import {apiRequest} from '../../lib/apiClient';
import {appManagedPrefix, ARCHIVE_FOLDER} from '../../lib/appManagedPaths';
import {readJsonDocument} from '../../lib/s3Json';
import {discardPayload, fromApiFailure, ok} from '../../lib/serviceResult';
import {sharedSpaceBucket, userSpaceBucket} from '../../lib/userSpace';
import type {ListObjectsResponse} from '../../types/apiContract.generated';
import type {ServiceResult} from '../../types/service.types';
import type {
  ArchiveIndexEntry,
  ArchiveListing,
  ArchiveRequest,
  ArchiveSpace,
  RestoreRequest
} from '../../types/archive.types';
import {normalizeArchiveName} from './archiveName';
import {isArchiveId} from './archiveId';

/**
 * The control plane's own request-shape caps, mirrored (`arcommon/config.py`), so the common
 * case fails fast and legibly instead of dead-lettering.
 *
 * The mirror is not belt-and-braces. `validate-authorize` enforces these in the machine's first
 * task, but a request too large for `StartExecution` never reaches it: the Pipe cannot start the
 * execution at all, the message dead-letters, and the user learns about it from the drain
 * minutes later rather than from a refusal now. Below the caps the verb is still the authority.
 *
 * The Lambda side reads these two names back out of this file, because a restatement
 * nobody checks is worse than no guard at all — the wrong number reads as deliberate.
 */
const ARCHIVE_MAX_ITEMS = 200;
const ARCHIVE_MAX_ITEM_BYTES = 87 * 1024;

/** Both modes' shared shape guard: the selection cap the control plane enforces again. */
function selectionTooLarge(items: ArchiveRequest['items']): boolean {
  const bytes = wireBytes(items);
  return items.length > ARCHIVE_MAX_ITEMS || bytes > ARCHIVE_MAX_ITEM_BYTES;
}

/**
 * Enqueue an archive request through the API's `archive.archive` route — the browser's only
 * archive write. A name, when the request carries one, travels normalised as `archiveName`, and
 * is left off entirely when nothing is left of it. The browser holds no privilege on the plane: the API's execution role puts the
 * request on the archive FIFO queue, and the async control plane copies the selection into the
 * vault at `GLACIER`, confirms every object, and only then deletes the source, so success here
 * means *enqueued*, not archived.
 *
 * The `requestId` stays minted PER SUBMIT in the browser: it is still the double-submit guard,
 * the API echoes it rather than minting one, and reusing it across a retry would make the retry a
 * silent no-op. The FIFO keys themselves are derived server-side now.
 */
export async function enqueueArchive(req: ArchiveRequest): Promise<ServiceResult<void>> {
  if (selectionTooLarge(req.items)) {
    return {
      success: false,
      error: {
        message: 'That selection is too large to archive in one go. Select fewer items and try again.',
        code: 'SelectionTooLarge'
      }
    };
  }

  // Normalised HERE as well as in the dialog, because this is the wire boundary: a caller that
  // skipped the dialog must not send a name the plane refuses as un-normalised.
  const archiveName = normalizeArchiveName(req.name ?? '');
  return discardPayload(
    await apiRequest('archive.archive', {
      body: {
        requestId: req.requestId,
        source: {space: req.space, items: req.items},
        ...(archiveName ? {archiveName} : {})
      }
    })
  );
}

/**
 * Enqueue a restore request onto the same FIFO queue — one plane serves both modes, branching on
 * `mode`.
 *
 * The body's field set is the RESTORE contract and not a superset of the archive one: unknown
 * top-level fields are rejected rather than ignored by `validate-authorize`, per mode, so a
 * restore carrying a selection is a refusal rather than a request that quietly ignores half of
 * itself.
 *
 * The space comes from the caller — the route the user is standing in — never from the archive.
 * An archive belonging to a different space is then simply not found, which
 * is what keeps this from becoming an existence oracle over other people's archives.
 */
export async function enqueueRestore(req: RestoreRequest): Promise<ServiceResult<void>> {
  return discardPayload(
    await apiRequest('archive.restore', {
      body: {requestId: req.requestId, space: req.space, archiveId: req.archiveId}
    })
  );
}

/**
 * A runaway bound on the receipt folder's pages, 25 archives each. A space past it shows the
 * archives it loaded, and the restore dialog's id field still reaches the rest.
 */
const ARCHIVE_LIST_MAX_PAGES = 100;

/**
 * Is this an index entry the list can label a row with? Checked field by field, and an entry that
 * fails is dropped rather than failing the list: the index is a label, and one malformed row
 * should cost that row's label and nothing else.
 */
function isIndexEntry(value: unknown): value is ArchiveIndexEntry {
  const entry = value as Partial<ArchiveIndexEntry> | null;
  const restore = entry?.restore;
  return (
    !!entry &&
    typeof entry === 'object' &&
    typeof entry.archiveId === 'string' &&
    (entry.name === null || typeof entry.name === 'string') &&
    typeof entry.archivedAt === 'string' &&
    typeof entry.archivedBy === 'string' &&
    Array.isArray(entry.items) &&
    entry.items.every((item) => typeof item?.path === 'string' && (item.kind === 'file' || item.kind === 'folder')) &&
    typeof entry.itemCount === 'number' &&
    typeof entry.fileCount === 'number' &&
    typeof entry.totalBytes === 'number' &&
    (restore === null ||
      (typeof restore === 'object' &&
        (restore.status === 'requested' || restore.status === 'restored' || restore.status === 'incomplete') &&
        typeof restore.requestedAt === 'string' &&
        typeof restore.updatedAt === 'string'))
  );
}

/**
 * The index's labels by archive id. TOTAL: a body that is absent, not JSON, of another version or
 * the wrong shape gives no labels, which puts every archive in the list unlabelled — never an
 * error, since the receipt folders still say what exists.
 */
function parseLabels(body: string | undefined): Map<string, ArchiveIndexEntry> {
  let parsed: unknown;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    return new Map();
  }
  const document = parsed as {version?: unknown; archives?: unknown} | null;
  if (document?.version !== 1 || !Array.isArray(document.archives)) return new Map();
  return new Map(document.archives.filter(isIndexEntry).map((entry) => [entry.archiveId.toLowerCase(), entry]));
}

/**
 * List a space's archives for the restore dialog: every archive that has a receipt, labelled
 * where the space's index knows it.
 *
 * **The receipt folder says which archives exist, and the index only labels them.** Each completed
 * archive leaves a folder named after its id under `system_settings/archive/`, which users can
 * read and cannot write, so listing it cannot miss an archive the plane finished. The index is
 * written after the receipt and every fault writing it is swallowed, so it can lack an entry —
 * which costs that row its name and never its route to a restore. An index entry with no folder
 * is dropped, and a folder with no entry is an unlabelled row.
 *
 * Rows sort by archive date, newest first, with the unlabelled ones after them by id. Only the
 * folder listing failing is a failure; the index failing in any way is no labels.
 *
 * @param space - The space being restored into, from the route.
 * @returns The rows, or a failure when the receipt folder could not be listed.
 */
export async function listArchives(space: ArchiveSpace): Promise<ServiceResult<ArchiveListing[]>> {
  const root = `${space.name}/`;
  const prefix = appManagedPrefix(root, ARCHIVE_FOLDER);
  const ids = new Set<string>();

  let nextToken: string | null = null;
  for (let page = 0; page < ARCHIVE_LIST_MAX_PAGES; page++) {
    const listed: ServiceResult<ListObjectsResponse> = await apiRequest('objects.list', {
      query: {spaceKind: space.kind, spaceName: space.name, prefix, ...(nextToken ? {nextToken} : {})}
    });
    if (!listed.success) return fromApiFailure(listed.error, 'Couldn’t load this space’s archives.');
    for (const row of listed.data.items) {
      const id = row.key.slice(prefix.length).replace(/\/$/, '');
      if (row.kind === 'folder' && row.key.startsWith(prefix) && isArchiveId(id)) ids.add(id.toLowerCase());
    }
    nextToken = listed.data.nextToken;
    if (!nextToken) break;
  }

  const read = await readJsonDocument({
    bucket: space.kind === 'shared' ? sharedSpaceBucket() : userSpaceBucket(),
    key: `${prefix}index.json`,
    parse: (body) => ok(parseLabels(body)),
    onMissing: () => ok(new Map<string, ArchiveIndexEntry>()),
    onTooLarge: () => ok(new Map<string, ArchiveIndexEntry>()),
    fallbackMessage: 'Couldn’t read the archive labels.'
  });
  const labels = read.success ? read.data : new Map<string, ArchiveIndexEntry>();

  const listings: ArchiveListing[] = [...ids].map((archiveId) => {
    const entry = labels.get(archiveId);
    if (!entry) return {archiveId, details: null};
    const {name, archivedAt, archivedBy, items, itemCount, fileCount, totalBytes, restore} = entry;
    return {archiveId, details: {name, archivedAt, archivedBy, items, itemCount, fileCount, totalBytes, restore}};
  });
  return ok(listings.sort(byArchiveDate));
}

/** Newest archive first; unlabelled rows after every labelled one, by id. */
function byArchiveDate(a: ArchiveListing, b: ArchiveListing): number {
  if (a.details && b.details) return b.details.archivedAt.localeCompare(a.details.archivedAt);
  if (a.details) return -1;
  if (b.details) return 1;
  return a.archiveId.localeCompare(b.archiveId);
}
