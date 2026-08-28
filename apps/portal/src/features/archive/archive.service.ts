import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import type {ServiceResult} from '../../types/service.types';
import type {ArchiveRequest, ArchiveSpace, RestoreRequest} from '../../types/archive.types';
import {configValue} from '../../lib/runtimeConfig';
import {spaceBuckets} from '../../lib/userSpace';

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
const ARCHIVE_MAX_ITEM_BYTES = 96 * 1024;

/** The archive folder segment, matching `arcommon.config.ARCHIVE_FOLDER`. */
const ARCHIVE_FOLDER = 'archive';

/**
 * The bucket a space lives in, derived exactly as the control plane derives it
 * (`arcommon.authz.authorize_source`): personal spaces are in the user-space bucket, shared
 * spaces in the shared-space bucket. Used only to build the archive FIFO group id — the enqueued
 * body never carries a bucket, because the verb resolves it server-side from the verified actor.
 */
function spaceBucket(space: ArchiveSpace): string {
  const {user, shared} = spaceBuckets();
  return (space.kind === 'personal' ? user : shared) ?? '';
}

/**
 * SHA-256 hex digest of a canonical string.
 *
 * A HASH, NEVER THE RAW PATH, in both derivations below. SQS caps `MessageGroupId` at 128
 * characters where an S3 key reaches 1024 — the raw form would be a length failure that appears
 * only for the users with the deepest prefixes, which is the reasoning the data-quality plane
 * recorded first.
 */
async function digest(canonical: string): Promise<string> {
  const hashed = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(hashed))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * The ARCHIVE group id: the digest of `{spaceBucket}/{spaceRoot}`, so two
 * archives out of one space serialize — they may select overlapping folders — while archives
 * from different spaces run in parallel.
 */
function archiveGroupId(space: ArchiveSpace): Promise<string> {
  return digest(`${spaceBucket(space)}/${space.name}/`);
}

/**
 * The RESTORE group id: the digest of the ARCHIVE ROOT, `{kind}/{name}/archive/{archiveId}/`,
 * mirroring `arcommon.paths.archive_root`. Keyed on the archive rather than the space, so two
 * restores of ONE archive serialize — that is the field's whole job here, since without it a
 * double-submitted restore could pass the destination guard twice before either copy lands —
 * while restores of different archives in one space proceed in parallel.
 *
 * **The archive BUCKET is deliberately not part of it**, which is where this differs from
 * The plane's literal wording. The browser has no relationship with that bucket by
 * decision: its name is absent from the CSP, from every portal-role statement and
 * from this app's build env, and `test_archive_bucket_isolation.py` enforces that absence. It
 * would also add no discrimination — it is one constant across every restore this app can make
 * — and the `personal/`/`shared/` segment already makes the archive root globally unique, which
 * is the property the group id actually needs.
 */
function restoreGroupId(space: ArchiveSpace, archiveId: string): Promise<string> {
  return digest(`${space.kind}/${space.name}/${ARCHIVE_FOLDER}/${archiveId}/`);
}

/** Both modes' shared shape guard: the selection cap the control plane enforces again. */
function selectionTooLarge(items: ArchiveRequest['items']): boolean {
  const bytes = new TextEncoder().encode(JSON.stringify(items)).length;
  return items.length > ARCHIVE_MAX_ITEMS || bytes > ARCHIVE_MAX_ITEM_BYTES;
}

/**
 * Enqueue an archive request onto the archive FIFO queue — the browser's only archive AWS call,
 * and its only archive privilege. The async control plane copies the selection into the vault at
 * `GLACIER`, confirms every object, and only then deletes the source, so success here means
 * *enqueued*, not archived.
 *
 * The token rides as a top-level `actor`, matching every other plane's envelope: the
 * shared DLQ drain reads and redacts that field flatly, so a nested one would mean a
 * dead-lettered archive notified nobody *and* wrote the raw JWT to CloudWatch.
 *
 * `MessageDeduplicationId` is the caller's `requestId` — the queue has content-based dedup OFF,
 * so that id is the only double-submit guard, and it is also the archive's permanent identity.
 */
export async function enqueueArchive(req: ArchiveRequest): Promise<ServiceResult<void>> {
  if (selectionTooLarge(req.items)) {
    return {
      success: false,
      error: {message: 'That selection is too large to archive in one go', code: 'SelectionTooLarge'}
    };
  }

  return enqueueFifoRequest<void>({
    queueUrl: configValue('archiveQueueUrl'),
    notConfiguredMessage: 'Archiving is not configured',
    build: async (idToken) => ({
      body: {
        requestId: req.requestId,
        mode: 'archive',
        actor: idToken,
        source: {space: req.space, items: req.items}
      },
      messageGroupId: await archiveGroupId(req.space),
      deduplicationId: req.requestId,
      data: undefined
    })
  });
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
  return enqueueFifoRequest<void>({
    queueUrl: configValue('archiveQueueUrl'),
    notConfiguredMessage: 'Restoring is not configured',
    build: async (idToken) => ({
      body: {
        requestId: req.requestId,
        mode: 'restore',
        actor: idToken,
        space: req.space,
        archiveId: req.archiveId
      },
      messageGroupId: await restoreGroupId(req.space, req.archiveId),
      deduplicationId: req.requestId,
      data: undefined
    })
  });
}
