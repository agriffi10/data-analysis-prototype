import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import type {ServiceResult} from '../../types/service.types';
import type {FileOpRequest, FileOpSpace} from './fileOps.types';

/**
 * The control plane's own caps, mirrored (`focommon/config.py`).
 *
 * The mirror is not belt-and-braces. `validate-authorize` enforces these in the machine's first
 * task, and a request too large for `StartExecution` never reaches it — the Pipe cannot start the
 * execution at all, so the message dead-letters and the user learns about it from the DLQ drain
 * minutes later rather than from a refusal now. Below the caps the verb is still the authority;
 * these exist so the common case fails fast and legibly.
 *
 * The byte cap is measured against a DIFFERENT quantity from the plane's, and it has to be: the
 * plane's is computed over the whole chain — the actor's token, the destination, and one outcome
 * record per item riding beside the request — none of which the browser can see. A test holds this
 * one at or below the plane's, so a local refusal can never be more permissive than the authority.
 */
const FILE_OPS_MAX_ITEMS = 200;
const FILE_OPS_MAX_SELECTION_BYTES = 64 * 1024;

/**
 * The bucket a space lives in, derived exactly as the control plane derives it
 * (`focommon.authz`): personal spaces are in the user-space bucket, shared spaces in the
 * shared-space bucket. Used only to build the FIFO group id — the enqueued body never carries a
 * bucket, because the verb resolves it server-side from the verified actor.
 */
function spaceBucket(space: FileOpSpace): string {
  const bucket =
    space.kind === 'personal' ? import.meta.env.VITE_S3_USER_SPACE_BUCKET : import.meta.env.VITE_S3_SHARED_SPACE_BUCKET;
  return (bucket as string | undefined) ?? '';
}

/**
 * FIFO group id: the SHA-256 hex digest of `{bucket}/{spaceRoot}`, so requests against one space
 * are delivered in order while different spaces run in parallel.
 *
 * **Ordered delivery is not serialized execution**, and on this plane that distinction is the
 * difference between working and losing data — the Pipe starts the machine and returns, so two
 * operations in one space can still run at once. The serialization is the per-space lock inside
 * the machine; this buys ordering and throughput isolation, and nothing else.
 *
 * A HASH, NEVER THE RAW PATH. SQS caps `MessageGroupId` at 128 characters where an S3 key reaches
 * 1024 — the raw form would be a length failure that appears only for the users with the deepest
 * prefixes.
 *
 * The trailing slash is inside the hashed string, and the plane hashes the identical string to
 * derive its lock key. A difference of one character means delivery is ordered per space while the
 * lock is keyed by something else, and nothing at runtime reports that: operations simply stop
 * being serialized. Both sides pin the same vector in their own tests.
 */
async function messageGroupId(space: FileOpSpace): Promise<string> {
  const canonical = `${spaceBucket(space)}/${space.name}/`;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Enqueue one file operation onto the file-ops FIFO queue — the browser's only file-ops AWS call,
 * and its only file-ops privilege. The async control plane performs the copy, move or delete, so
 * success means *enqueued*, never completed.
 *
 * The token rides as a top-level `actor`, matching every other plane's envelope: the shared DLQ
 * drain reads and redacts that field flatly, so a nested one would mean a dead-lettered request
 * notified nobody *and* wrote the raw JWT to CloudWatch.
 *
 * `MessageDeduplicationId` is the caller's `requestId` — the queue has content-based dedup OFF, so
 * that id is the only double-submit guard, and it must be minted per submit rather than per
 * dialog. Reusing one across a retry makes the retry a silent no-op.
 */
export async function submitFileOperation(request: FileOpRequest): Promise<ServiceResult<void>> {
  const selectionBytes = new TextEncoder().encode(JSON.stringify(request.source.items)).length;
  if (request.source.items.length > FILE_OPS_MAX_ITEMS || selectionBytes > FILE_OPS_MAX_SELECTION_BYTES) {
    return {
      success: false,
      error: {message: 'That selection is too large to do in one go', code: 'SelectionTooLarge'}
    };
  }

  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_FILE_OPS_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'File operations are not configured',
    build: async (idToken) => ({
      body: {
        requestId: request.requestId,
        actor: idToken,
        operation: request.operation,
        source: request.source,
        // Spread rather than set to undefined: the plane REJECTS these fields on a delete rather
        // than ignoring them, and `JSON.stringify` drops an undefined value but keeps an explicit
        // null — which would arrive as a field the contract forbids.
        ...(request.destination ? {destination: request.destination} : {}),
        ...(request.onConflict ? {onConflict: request.onConflict} : {}),
        ...(request.submittedAt ? {submittedAt: request.submittedAt} : {})
      },
      messageGroupId: await messageGroupId(request.source.space),
      deduplicationId: request.requestId,
      data: undefined
    })
  });
}
