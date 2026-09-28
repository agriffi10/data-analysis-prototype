import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiFailure, documentBody, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {enqueueArchive, enqueueRestore, listArchives} from './archive.service';
import type {ArchiveRequest, RestoreRequest} from '../../types/archive.types';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The archive and restore enqueues, now over the API.
 *
 * **Every FIFO key is deliberately absent from this file.** The archive group id
 * (`{spaceBucket}/{spaceRoot}`, which also kept the two bucket namespaces apart), the restore
 * group id (the archive root, which deliberately never named the vault bucket) and both dedup ids
 * are computed server-side now, and they are replayed against vectors captured from this very
 * service in `lambdas/api/test_fifo_derivations.py` — personal and shared, archive and restore.
 * Asserting them here would be asserting a fake.
 *
 * The flat top-level token, which the shared DLQ drain reads and redacts, went the same way: the
 * API stamps it, and `lambdas/test_plane_envelope_agreement.py` holds it against the drain's own
 * table rather than against a copy of it.
 *
 * What stays here is the browser's half: the two selection caps, which are still refused in this
 * process before anything is sent, the caller's own fields reaching the body, and a failure that
 * comes back as a result rather than a throw.
 */
const archiveReq: ArchiveRequest = {
  requestId: '11111111-1111-4111-8111-111111111111',
  space: {kind: 'personal', name: 'alice'},
  items: [
    {kind: 'file', key: 'alice/reports/q1.csv'},
    {kind: 'folder', key: 'alice/reports/2026/'}
  ]
};

const restoreReq: RestoreRequest = {
  requestId: '22222222-2222-4222-8222-222222222222',
  space: {kind: 'personal', name: 'alice'},
  // Deliberately mixed case, and deliberately not the request id: the service forwards the id it
  // is handed, and the normalising to lower case is `useRestoreArchive`'s job and asserted there.
  archiveId: '3F8A1C2E-9b4d-4A17-8c65-2E0D7B1F4A93'
};

describe('enqueueArchive', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the archive once, carrying the request id and the whole selection', async () => {
    api.on('archive.archive', {success: true, data: {requestId: archiveReq.requestId}});

    const result = await enqueueArchive(archiveReq);

    // The route answers `{requestId}` and the caller's signature is `ServiceResult<void>`.
    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['archive.archive']);
    // `toEqual`, not `toMatchObject`: the absence of a claimed identity is the assertion. The API
    // refuses a body carrying `actor`, `identity` or `idToken` outright.
    expect(api.bodyFor('archive.archive')).toEqual({
      requestId: archiveReq.requestId,
      source: {space: {kind: 'personal', name: 'alice'}, items: archiveReq.items}
    });
  });

  it('sends the name normalised as archiveName, and no name at all when only spaces were typed', async () => {
    api.on('archive.archive', {success: true, data: {requestId: archiveReq.requestId}});

    await enqueueArchive({...archiveReq, name: '  Q1   reports  '});
    await enqueueArchive({...archiveReq, name: '   '});

    expect(api.calls.map((call) => call.body)).toEqual([
      {
        requestId: archiveReq.requestId,
        source: {space: archiveReq.space, items: archiveReq.items},
        archiveName: 'Q1 reports'
      },
      {requestId: archiveReq.requestId, source: {space: archiveReq.space, items: archiveReq.items}}
    ]);
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('archive.archive', apiFailure('ApiUnavailable'));

    const result = await enqueueArchive(archiveReq);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
  });

  it('refuses a selection over the item cap without calling the API', async () => {
    const result = await enqueueArchive({
      ...archiveReq,
      items: Array.from({length: 201}, (_, i) => ({kind: 'file' as const, key: `alice/f${i}.csv`}))
    });

    expect(result).toEqual({success: false, error: {message: expect.any(String), code: 'SelectionTooLarge'}});
    expect(api.calls).toEqual([]);
  });

  it('refuses a selection over the byte cap even when the count is legal', async () => {
    // The two caps bound different quantities: the count bounds per-item work, the bytes bound
    // what rides on the state and reaches the Pipe. A handful of very long keys passes one and
    // not the other.
    const result = await enqueueArchive({
      ...archiveReq,
      items: Array.from({length: 50}, (_, i) => ({kind: 'file' as const, key: `alice/${'k'.repeat(2000)}${i}.csv`}))
    });

    expect(result.success === false && result.error.code).toBe('SelectionTooLarge');
    expect(api.calls).toEqual([]);
  });
});

describe('enqueueRestore', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the restore once, with the run id, the space and the archive id it was handed', async () => {
    api.on('archive.restore', {success: true, data: {requestId: restoreReq.requestId}});

    const result = await enqueueRestore(restoreReq);

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['archive.restore']);
    expect(api.bodyFor('archive.restore')).toEqual({
      requestId: restoreReq.requestId,
      space: {kind: 'personal', name: 'alice'},
      archiveId: '3F8A1C2E-9b4d-4A17-8c65-2E0D7B1F4A93'
    });
    // Conflating the run id with the archive id is the obvious shortcut and is wrong in both
    // directions: a refused restore must be re-submittable under a new run id, and a second
    // attempt at one archive is a new request.
    const body = api.bodyFor('archive.restore') as {requestId: string; archiveId: string};
    expect(body.requestId).not.toBe(body.archiveId);
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('archive.restore', apiFailure('ApiUnavailable'));

    const result = await enqueueRestore(restoreReq);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
  });
});

describe('listArchives', () => {
  const PREFIX = 'alice/system_settings/archive/';
  const NEW = '11111111-1111-4111-8111-111111111111';
  const OLDER = '22222222-2222-4222-8222-222222222222';
  const UNLABELLED = '44444444-4444-4444-8444-444444444444';
  const INDEX_ONLY = '55555555-5555-4555-8555-555555555555';
  let api: ApiMock;

  const entry = (archiveId: string, archivedAt: string) => ({
    archiveId,
    name: null,
    archivedAt,
    archivedBy: 'alice',
    items: [{kind: 'file', path: 'q1.csv'}],
    itemCount: 1,
    fileCount: 1,
    totalBytes: 5,
    restore: null
  });

  const page = (ids: string[], nextToken: string | null, files: string[] = [], prefix = PREFIX) => ({
    success: true as const,
    data: {
      items: [
        ...ids.map((id) => ({kind: 'folder' as const, key: `${prefix}${id}/`, size: null, lastModified: null})),
        ...files.map((key) => ({kind: 'file' as const, key: `${prefix}${key}`, size: 1, lastModified: null}))
      ],
      nextToken
    }
  });

  beforeEach(async () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bkt');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bkt');
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('lists every archive with a receipt folder across pages, labelled where the index knows it, newest first', async () => {
    // The token has the characters a re-encoding would corrupt, so a changed one would show.
    api.onEach('objects.list', [page([OLDER, UNLABELLED], 'a+b/c='), page([NEW], null, ['index.json'])]);
    api.on(
      'objects.readContent',
      documentBody({
        version: 1,
        archives: [
          entry(OLDER, '2026-08-01T00:00:00Z'),
          entry(NEW, '2026-09-01T00:00:00Z'),
          entry(INDEX_ONLY, '2026-09-02T00:00:00Z')
        ]
      })
    );

    const result = await listArchives({kind: 'personal', name: 'alice'});

    expect(result.success && result.data.map((row) => [row.archiveId, row.details?.archivedAt ?? null])).toEqual([
      [NEW, '2026-09-01T00:00:00Z'],
      [OLDER, '2026-08-01T00:00:00Z'],
      [UNLABELLED, null]
    ]);
    expect(api.calls.filter((call) => call.route === 'objects.list').map((call) => call.query?.nextToken)).toEqual([
      undefined,
      'a+b/c='
    ]);
    expect(api.queryFor('objects.readContent')).toEqual({
      spaceKind: 'personal',
      spaceName: 'alice',
      key: `${PREFIX}index.json`
    });
  });

  it.each([
    ['a failed read', apiFailure('InternalError')],
    ['a body that is not JSON', documentBody('{not json')],
    ['a newer version', documentBody({version: 2, archives: [entry(NEW, '2026-09-01T00:00:00Z')]})],
    ['a document too large to read', apiFailure('PayloadTooLarge')]
  ])('lists every archive unlabelled after %s of the index, and does not fail', async (_label, read) => {
    api.on('objects.list', page([NEW], null, [], 'team/system_settings/archive/'));
    api.on('objects.readContent', read);

    const result = await listArchives({kind: 'shared', name: 'team'});

    expect(result).toEqual({success: true, data: [{archiveId: NEW, details: null}]});
  });

  it('reads a shared space’s index from that space, and labels its rows from it', async () => {
    const shared = 'team/system_settings/archive/';
    api.on('objects.list', page([NEW], null, [], shared));
    api.on('objects.readContent', documentBody({version: 1, archives: [entry(NEW, '2026-09-01T00:00:00Z')]}));

    const result = await listArchives({kind: 'shared', name: 'team'});

    expect(api.queryFor('objects.readContent')).toEqual({
      spaceKind: 'shared',
      spaceName: 'team',
      key: `${shared}index.json`
    });
    expect(result.success && result.data[0].details?.archivedAt).toBe('2026-09-01T00:00:00Z');
  });

  it.each([
    ['no items', {items: undefined}],
    ['a restore status it does not know', {restore: {status: 'lost', requestedAt: 't', updatedAt: 't'}}]
  ])('drops only the label of an entry with %s, and keeps its neighbours', async (_label, broken) => {
    api.on('objects.list', page([NEW, OLDER], null));
    api.on(
      'objects.readContent',
      documentBody({
        version: 1,
        archives: [{...entry(NEW, '2026-09-01T00:00:00Z'), ...broken}, entry(OLDER, '2026-08-01T00:00:00Z')]
      })
    );

    const result = await listArchives({kind: 'personal', name: 'alice'});

    expect(result.success && result.data.map((row) => [row.archiveId, row.details !== null])).toEqual([
      [OLDER, true],
      [NEW, false]
    ]);
  });

  it('fails when the receipt folder itself cannot be listed', async () => {
    api.on('objects.list', apiFailure('InternalError'));

    const result = await listArchives({kind: 'personal', name: 'alice'});

    expect(result.success).toBe(false);
    expect(api.countOf('objects.readContent')).toBe(0);
  });
});
