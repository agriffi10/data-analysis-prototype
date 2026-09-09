import {wireBytes} from '../../lib/wireBytes';
import {apiRequest} from '../../lib/apiClient';
import {discardPayload} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {ArchiveRequest, RestoreRequest} from '../../types/archive.types';

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
const ARCHIVE_MAX_ITEM_BYTES = 89 * 1024;

/** Both modes' shared shape guard: the selection cap the control plane enforces again. */
function selectionTooLarge(items: ArchiveRequest['items']): boolean {
  const bytes = wireBytes(items);
  return items.length > ARCHIVE_MAX_ITEMS || bytes > ARCHIVE_MAX_ITEM_BYTES;
}

/**
 * Enqueue an archive request onto the archive FIFO queue — the browser's only archive write,
 * and its only archive privilege. The async control plane copies the selection into the vault at
 * `GLACIER`, confirms every object, and only then deletes the source, so success here means
 * *enqueued*, not archived.
 *
 *
 * The `requestId` stays minted PER SUBMIT in the browser: it is still the double-submit guard,
 * the API echoes it rather than minting one, and reusing it across a retry would make the retry a
 * silent no-op. The FIFO keys themselves are derived server-side now.
 */
export async function enqueueArchive(req: ArchiveRequest): Promise<ServiceResult<void>> {
  if (selectionTooLarge(req.items)) {
    return {
      success: false,
      error: {message: 'That selection is too large to archive in one go', code: 'SelectionTooLarge'}
    };
  }

  return discardPayload(
    await apiRequest('archive.archive', {
      body: {requestId: req.requestId, source: {space: req.space, items: req.items}}
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
