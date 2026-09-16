import {describe, it, expect, vi, beforeEach} from 'vitest';
import {
  listFiles,
  ensurePrefixMarker,
  deleteObject,
  copyObject,
  moveObject,
  getDownloadUrl,
  folderExists,
  firstFreeName,
  uploadFile,
  createFolder,
  validateFolderName,
  validateLeafName,
  uploadPercent,
  getObjectMetadata,
  __resetPrefixMarkerCache
} from './fileBrowser.service';
import {maxUploadBytes, S3_SINGLE_PUT_MAX_BYTES} from './uploadLimits';
import {
  appManagedPrefix,
  MOVING_FOLDERS,
  SHARED_TABLES_FOLDER,
  SYSTEM_SETTINGS_FOLDER
} from '../../lib/appManagedPaths';
import {PICKER_LOCKED_FOLDERS} from './protectedFolders';
import {mockApi, apiFailure} from '../../test/apiMock';
import {toUserText} from '../../lib/errorMessages';

const {mockRequest} = vi.hoisted(() => ({mockRequest: vi.fn()}));
vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: mockRequest
}));

vi.mock('../../lib/userSpace', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/userSpace')>()),
  userSpaceBucket: () => 'user-space',
  sharedSpaceBucket: () => 'shared-space'
}));

let api: ReturnType<typeof mockApi>;

beforeEach(() => {
  vi.clearAllMocks();
  api = mockApi(mockRequest);
  __resetPrefixMarkerCache();
});

/** One listing page, in the shape the route returns: folders and files in ONE array. */
function page(
  items: {kind: 'folder' | 'file'; key: string; size?: number | null; lastModified?: string | null}[],
  nextToken: string | null = null
) {
  return {
    success: true as const,
    data: {
      items: items.map((item) => ({
        kind: item.kind,
        key: item.key,
        size: item.size ?? (item.kind === 'folder' ? null : 0),
        lastModified: item.lastModified ?? (item.kind === 'folder' ? null : '2024-01-01T00:00:00.000Z')
      })),
      nextToken
    }
  };
}

describe('listFiles', () => {
  it('maps one array of rows back onto files and folders', async () => {
    api.on(
      'objects.list',
      page([
        {kind: 'folder', key: 'alice/documents/archive/'},
        {kind: 'file', key: 'alice/documents/report.pdf', size: 1024, lastModified: '2024-01-15T10:00:00.000Z'}
      ])
    );

    const result = await listFiles('user-space', 'alice/documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.folders).toEqual([{type: 'folder', prefix: 'alice/documents/archive/', name: 'archive'}]);
    expect(result.data.files).toEqual([
      {
        type: 'file',
        key: 'alice/documents/report.pdf',
        name: 'report.pdf',
        size: 1024,
        lastModified: new Date('2024-01-15T10:00:00.000Z')
      }
    ]);
  });

  it('sorts folders and files alphabetically within their own group', async () => {
    api.on(
      'objects.list',
      page([
        {kind: 'file', key: 'alice/zebra.txt'},
        {kind: 'folder', key: 'alice/zoo/'},
        {kind: 'file', key: 'alice/apple.txt'},
        {kind: 'folder', key: 'alice/apps/'}
      ])
    );

    const result = await listFiles('user-space', 'alice/');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.folders.map((f) => f.name)).toEqual(['apps', 'zoo']);
    expect(result.data.files.map((f) => f.name)).toEqual(['apple.txt', 'zebra.txt']);
  });

  it('names the space from the prefix and passes the prefix through', async () => {
    api.on('objects.list', page([]));

    await listFiles('user-space', 'alice/documents/');

    expect(api.queryFor('objects.list')).toEqual({
      spaceKind: 'personal',
      spaceName: 'alice',
      prefix: 'alice/documents/'
    });
  });

  it('resolves the SHARED bucket to a shared space', async () => {
    api.on('objects.list', page([]));

    await listFiles('shared-space', 'project_alpha/reports/');

    expect(api.queryFor('objects.list')).toMatchObject({spaceKind: 'shared', spaceName: 'project_alpha'});
  });

  it('round-trips the continuation token and reports truncation from it', async () => {
    api.on('objects.list', page([], 'tok+en/with=padding'));

    const result = await listFiles('user-space', 'alice/', 'previous+token');

    expect(api.queryFor('objects.list')).toMatchObject({nextToken: 'previous+token'});
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(true);
    expect(result.data.nextContinuationToken).toBe('tok+en/with=padding');
  });

  it('drops the folder’s OWN placeholder from the files it reports', async () => {
    // A prefix's own zero-byte key is what makes the folder exist; listed as a file it is an
    // untitled zero-byte row in every folder the app created. The route drops it, and this is the
    // browser-side statement of that — the assertion that says which rows a caller may see.
    api.on('objects.list', page([{kind: 'file', key: 'alice/documents/report.pdf', size: 1024}]));

    const result = await listFiles('user-space', 'alice/documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.files.map((f) => f.name)).toEqual(['report.pdf']);
    expect(result.data.files.some((f) => f.name === '')).toBe(false);
  });

  it('reports the last page as not truncated', async () => {
    api.on('objects.list', page([], null));

    const result = await listFiles('user-space', 'alice/');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(false);
    expect(result.data.nextContinuationToken).toBeUndefined();
  });

  it('threads the abort signal into the request', async () => {
    api.on('objects.list', page([]));
    const controller = new AbortController();

    await listFiles('user-space', 'alice/', undefined, controller.signal);

    expect(mockRequest).toHaveBeenCalledWith('objects.list', expect.objectContaining({signal: controller.signal}));
  });

  it('returns a failure without throwing, keeping the code', async () => {
    api.on('objects.list', apiFailure('AccessDenied'));

    const result = await listFiles('user-space', 'bob/');

    expect(result).toEqual({
      success: false,
      error: {message: 'Unknown error listing files', code: 'AccessDenied'}
    });
  });

  it('makes exactly ONE call — no retry of its own', async () => {
    // The expired-credential refresh-and-retry that used to wrap every S3 call is gone: an expired
    // session is re-assumed server-side now, and an expired ID token is the transport's single 401
    // retry. A retry added back here would be a second one nobody declared.
    api.on('objects.list', apiFailure('InternalError'));

    await listFiles('user-space', 'alice/');

    expect(api.countOf('objects.list')).toBe(1);
  });
});

describe('ensurePrefixMarker', () => {
  it('writes the marker in ONE call, refusing to overwrite', async () => {
    api.on('objects.writeContent', {success: true, data: {key: 'alice/DO_NOT_DELETE.txt', etag: 'e'}});

    const result = await ensurePrefixMarker({bucket: 'user-space', username: 'alice'});

    expect(result).toEqual({success: true, data: {created: true}});
    expect(api.countOf('objects.writeContent')).toBe(1);
    expect(api.bodyFor('objects.writeContent')).toMatchObject({
      key: 'alice/DO_NOT_DELETE.txt',
      contentType: 'text/plain',
      overwrite: false
    });
  });

  it('reads a Conflict as "it is already there", not as a failure', async () => {
    api.on('objects.writeContent', apiFailure('Conflict'));

    const result = await ensurePrefixMarker({bucket: 'user-space', username: 'alice'});

    expect(result).toEqual({success: true, data: {created: false}});
  });

  it('surfaces any other failure without throwing', async () => {
    api.on('objects.writeContent', apiFailure('AccessDenied'));

    const result = await ensurePrefixMarker({bucket: 'user-space', username: 'alice'});

    expect(result).toEqual({
      success: false,
      error: {message: 'Failed to create prefix marker', code: 'AccessDenied'}
    });
  });

  it('asks once per session however many times it is called', async () => {
    api.on('objects.writeContent', {success: true, data: {key: 'alice/DO_NOT_DELETE.txt', etag: 'e'}});

    await ensurePrefixMarker({bucket: 'user-space', username: 'alice'});
    await ensurePrefixMarker({bucket: 'user-space', username: 'alice'});

    expect(api.countOf('objects.writeContent')).toBe(1);
  });
});

describe('deleteObject', () => {
  it('refuses the prefix marker with NO request at all', async () => {
    const result = await deleteObject({
      bucket: 'user-space',
      key: 'alice/DO_NOT_DELETE.txt',
      username: 'alice'
    });

    expect(result).toEqual({
      success: false,
      error: {
        message: 'This file keeps your storage space active and cannot be deleted.',
        code: 'ProtectedObject'
      }
    });
    expect(api.calls).toEqual([]);
  });

  it('deletes an ordinary object', async () => {
    api.on('objects.delete', {success: true, data: {key: 'alice/report.csv'}});

    const result = await deleteObject({bucket: 'user-space', key: 'alice/report.csv', username: 'alice'});

    expect(result).toEqual({success: true, data: {key: 'alice/report.csv'}});
    expect(api.bodyFor('objects.delete')).toEqual({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/report.csv'
    });
  });
});

describe('copyObject', () => {
  it('sends both ends of the copy and the overwrite flag', async () => {
    api.on('objects.copy', {success: true, data: {key: 'alice/copy.csv', etag: 'e'}});

    const result = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/report.csv',
      destKey: 'alice/copy.csv',
      username: 'alice',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/copy.csv'}});
    expect(api.bodyFor('objects.copy')).toEqual({
      source: {kind: 'personal', name: 'alice'},
      sourceKey: 'alice/report.csv',
      destination: {kind: 'personal', name: 'alice'},
      destinationKey: 'alice/copy.csv',
      overwrite: true
    });
  });

  it('resolves each END to its own space on a cross-bucket copy', async () => {
    api.on('objects.copy', {success: true, data: {key: 'project_alpha/report.csv', etag: 'e'}});

    await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/report.csv',
      destKey: 'project_alpha/report.csv',
      destBucket: 'shared-space',
      username: 'alice'
    });

    expect(api.bodyFor('objects.copy')).toMatchObject({
      source: {kind: 'personal', name: 'alice'},
      destination: {kind: 'shared', name: 'project_alpha'}
    });
  });

  it('turns a Conflict into the Collision sentence the app already shipped', async () => {
    // `Collision` is a passthrough code: it may never travel on the wire, so the wording is minted
    // here from the destination key this caller already holds.
    api.on('objects.copy', apiFailure('Conflict'));

    const result = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/report.csv',
      destKey: 'alice/taken.csv',
      username: 'alice'
    });

    expect(result).toEqual({
      success: false,
      error: {message: '"alice/taken.csv" already exists.', code: 'Collision'}
    });
  });

  it('costs ONE call, not a check and then a copy', async () => {
    api.on('objects.copy', apiFailure('Conflict'));

    await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/b.csv',
      username: 'alice'
    });

    expect(api.calls).toHaveLength(1);
  });

  it('refuses the prefix marker at either end, with no request', async () => {
    const asSource = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/DO_NOT_DELETE.txt',
      destKey: 'alice/x.txt',
      username: 'alice'
    });
    const asDestination = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/x.txt',
      destKey: 'alice/DO_NOT_DELETE.txt',
      username: 'alice'
    });

    expect(asSource.success).toBe(false);
    expect(asDestination.success).toBe(false);
    if (asSource.success || asDestination.success) return;
    expect(asSource.error.code).toBe('ProtectedObject');
    expect(asDestination.error.code).toBe('ProtectedObject');
    expect(api.calls).toEqual([]);
  });

  it('passes a non-collision failure through with its code', async () => {
    api.on('objects.copy', apiFailure('NotFound'));

    const result = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/gone.csv',
      destKey: 'alice/b.csv',
      username: 'alice'
    });

    expect(result).toEqual({success: false, error: {message: 'Failed to copy object', code: 'NotFound'}});
  });
});

describe('moveObject', () => {
  it('is ONE route, not a copy call followed by a delete call', async () => {
    // Two calls put a closed tab between them, and versioning is off: that is a lost file rather
    // than a failed move.
    api.on('objects.move', {success: true, data: {key: 'alice/b.csv', etag: 'e'}});

    const result = await moveObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/b.csv',
      username: 'alice'
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/b.csv'}});
    expect(api.routes()).toEqual(['objects.move']);
  });

  it('is a no-op success when source and destination are the same object', async () => {
    const result = await moveObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/a.csv',
      username: 'alice'
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/a.csv'}});
    expect(api.calls).toEqual([]);
  });

  it('still moves when the same key names a different object in another bucket', async () => {
    api.on('objects.move', {success: true, data: {key: 'project_alpha/a.csv', etag: 'e'}});

    await moveObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/a.csv',
      destBucket: 'shared-space',
      username: 'alice'
    });

    expect(api.countOf('objects.move')).toBe(1);
  });

  it('turns a Conflict into the Collision sentence', async () => {
    api.on('objects.move', apiFailure('Conflict'));

    const result = await moveObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/taken.csv',
      username: 'alice'
    });

    expect(result).toEqual({
      success: false,
      error: {message: '"alice/taken.csv" already exists.', code: 'Collision'}
    });
  });
});

describe('getDownloadUrl', () => {
  it('asks for a URL and returns it with its expiry', async () => {
    api.on('objects.downloadUrl', {
      success: true,
      data: {url: 'https://signed/report.csv', expiresAt: '2026-01-01T00:15:00Z'}
    });

    const result = await getDownloadUrl({bucket: 'user-space', key: 'alice/report.csv'});

    expect(result).toEqual({
      success: true,
      data: {url: 'https://signed/report.csv', expiresAt: '2026-01-01T00:15:00Z'}
    });
  });

  it('defaults the download name to the key’s last segment', async () => {
    api.on('objects.downloadUrl', {success: true, data: {url: 'https://signed/x', expiresAt: 'later'}});

    await getDownloadUrl({bucket: 'user-space', key: 'alice/reports/q1 "final".csv'});

    expect(api.bodyFor('objects.downloadUrl')).toEqual({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/reports/q1 "final".csv',
      // The RFC 6266 escaping moved to the route: the header is built where the URL is signed, so
      // a quote in a key cannot be escaped by one side and not the other.
      fileName: 'q1 "final".csv'
    });
  });

  it('surfaces a failure without throwing', async () => {
    api.on('objects.downloadUrl', apiFailure('AccessDenied'));

    const result = await getDownloadUrl({bucket: 'user-space', key: 'alice/x'});

    expect(result).toEqual({
      success: false,
      error: {message: 'Failed to generate download URL', code: 'AccessDenied'}
    });
  });
});

describe('folderExists', () => {
  it('asks the PREFIX question, not the object one', async () => {
    // The listing cannot answer this: it hides a folder's own marker object, so an empty folder
    // would report itself deleted. The `target` flag is what makes the answer raw.
    api.on('objects.exists', {success: true, data: {exists: true}});

    const result = await folderExists({bucket: 'user-space', prefix: 'alice/reports/'});

    expect(result).toEqual({success: true, data: true});
    expect(api.queryFor('objects.exists')).toEqual({
      spaceKind: 'personal',
      spaceName: 'alice',
      key: 'alice/reports/',
      target: 'prefix'
    });
  });

  it('reports an empty prefix as false', async () => {
    api.on('objects.exists', {success: true, data: {exists: false}});

    const result = await folderExists({bucket: 'user-space', prefix: 'alice/gone/'});

    expect(result).toEqual({success: true, data: false});
  });
});

describe('firstFreeName', () => {
  it('resolves the whole search in ONE call', async () => {
    // The browser used to walk (1)…(999) with a HeadObject each. Behind the API every probe would
    // be a browser → API → S3 round trip, which is strictly worse than what it replaced.
    api.on('objects.freeName', {success: true, data: {name: 'report (1).csv'}});

    const result = await firstFreeName({
      bucket: 'user-space',
      prefix: 'alice/',
      baseName: 'report.csv',
      kind: 'file'
    });

    expect(result).toEqual({success: true, data: 'report (1).csv'});
    expect(api.calls).toHaveLength(1);
    expect(api.bodyFor('objects.freeName')).toEqual({
      space: {kind: 'personal', name: 'alice'},
      prefix: 'alice/',
      baseName: 'report.csv',
      kind: 'file'
    });
  });

  it('separates EXHAUSTION from failure, which the old loop could not', async () => {
    // `firstFreeName` returned null both when 999 names were taken and when a probe errored, and
    // the caller rendered one sentence for either.
    api.on('objects.freeName', apiFailure('Conflict'));

    const result = await firstFreeName({
      bucket: 'user-space',
      prefix: 'alice/',
      baseName: 'report.csv',
      kind: 'file'
    });

    expect(result).toEqual({
      success: false,
      error: {message: 'Could not find an available name for the copy.', code: 'NoFreeName'}
    });
  });

  it('keeps a real failure’s own code', async () => {
    api.on('objects.freeName', apiFailure('AccessDenied'));

    const result = await firstFreeName({
      bucket: 'user-space',
      prefix: 'alice/',
      baseName: 'report.csv',
      kind: 'file'
    });

    expect(result).toEqual({
      success: false,
      error: {message: 'Could not find an available name for the copy.', code: 'AccessDenied'}
    });
  });
});

describe('uploadPercent', () => {
  it('maps loaded/total to a clamped whole percent', () => {
    expect(uploadPercent(0, 100)).toBe(0);
    expect(uploadPercent(50, 100)).toBe(50);
    expect(uploadPercent(100, 100)).toBe(100);
    expect(uploadPercent(5, 0)).toBe(100);
    expect(uploadPercent(200, 100)).toBe(100);
  });
});

describe('validateFolderName', () => {
  it('accepts a normal name', () => {
    expect(validateFolderName('reports')).toBeNull();
  });
});

describe('validateLeafName', () => {
  it('refuses a dot segment by name, and still accepts a dotted or dot-led name', () => {
    // The API refuses a key with a `.` or `..` segment as access denied, so a name the
    // browser let through would reach the user as a permission error rather than a reason.
    expect(validateLeafName('.', 'File name')).toBe('File name cannot be “.” or “..”.');
    expect(validateLeafName('..', 'File name')).toBe('File name cannot be “.” or “..”.');
    expect(validateLeafName('.env', 'File name')).toBeNull();
    expect(validateLeafName('...', 'File name')).toBeNull();
  });
});

describe('maxUploadBytes', () => {
  it('never exceeds what one PutObject can carry', () => {
    // The single-PUT limit is where the ceiling actually is now. An operator who raised the
    // configured maximum above it used to get multipart; without this clamp they would get an
    // EntityTooLarge from S3 at the END of a long transfer, with nothing failing earlier.
    expect(maxUploadBytes()).toBeLessThanOrEqual(S3_SINGLE_PUT_MAX_BYTES);
  });

  it('measures the clamp against the published PutObject limit', () => {
    expect(S3_SINGLE_PUT_MAX_BYTES).toBe(5 * 1024 * 1024 * 1024);
  });
});

describe('createFolder', () => {
  it('writes a zero-byte directory marker in one call', async () => {
    api.on('objects.writeContent', {success: true, data: {key: 'alice/reports/', etag: 'e'}});

    const result = await createFolder({bucket: 'user-space', prefix: 'alice/', name: 'reports'});

    expect(result).toEqual({success: true, data: {prefix: 'alice/reports/'}});
    expect(api.calls).toHaveLength(1);
    expect(api.bodyFor('objects.writeContent')).toEqual({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/reports/',
      body: '',
      contentType: 'application/x-directory',
      overwrite: false
    });
  });

  it('turns a Conflict into the collision sentence, naming the folder', async () => {
    api.on('objects.writeContent', apiFailure('Conflict'));

    const result = await createFolder({bucket: 'user-space', prefix: 'alice/', name: 'reports'});

    expect(result).toEqual({
      success: false,
      error: {message: 'A folder named "reports" already exists.', code: 'Collision'}
    });
  });

  it('refuses an invalid name before any request', async () => {
    const result = await createFolder({bucket: 'user-space', prefix: 'alice/', name: 'a/b'});

    expect(result).toEqual({
      success: false,
      error: {message: "Folder name cannot contain '/'.", code: 'InvalidName'}
    });
    expect(api.calls).toEqual([]);
  });

  it('checks the name against the folder it writes into, which no prompt can skip', async () => {
    // Every prompt in front of this is told the parent only by a caller that remembers to.
    const result = await createFolder({bucket: 'user-space', prefix: 'alice/', name: SHARED_TABLES_FOLDER});

    expect(result).toEqual({
      success: false,
      error: {
        message: '“shared_tables” is a folder the app manages at the top of a space. Pick another name.',
        code: 'InvalidName'
      }
    });
    expect(api.calls).toEqual([]);
  });
});

describe('getObjectMetadata', () => {
  it('maps the route’s answer onto ObjectMetadata, storage class and pairs included', async () => {
    api.on('objects.metadata', {
      success: true,
      data: {
        key: 'alice/report.pdf',
        size: 2048,
        lastModified: '2024-02-01T09:30:00.000Z',
        contentType: 'application/pdf',
        etag: 'abc123',
        storageClass: 'INTELLIGENT_TIERING',
        userMetadata: [
          {name: 'owner', value: 'alice'},
          {name: 'batch', value: '7'}
        ]
      }
    });

    const result = await getObjectMetadata({bucket: 'user-space', key: 'alice/report.pdf'});

    expect(result).toEqual({
      success: true,
      data: {
        key: 'alice/report.pdf',
        size: 2048,
        lastModified: new Date('2024-02-01T09:30:00.000Z'),
        contentType: 'application/pdf',
        etag: 'abc123',
        storageClass: 'INTELLIGENT_TIERING',
        userMetadata: {owner: 'alice', batch: '7'}
      }
    });
  });

  it('returns a NotFound error, not a throw, when the object is gone', async () => {
    api.on('objects.metadata', apiFailure('NotFound'));

    const result = await getObjectMetadata({bucket: 'user-space', key: 'alice/gone.pdf'});

    expect(result).toEqual({
      success: false,
      error: {message: 'This file no longer exists.', code: 'NotFound'}
    });
  });
});

/**
 * The transport under `uploadFile`, driven by hand.
 *
 * A stub rather than a real request because the assertions are about WHAT the upload does with the
 * events — chiefly that an intermediate progress value reaches the caller, which is the one thing
 * a `fetch` implementation cannot produce and every "the upload succeeded" test passes over.
 */
class FakeXhr {
  static last: FakeXhr | undefined;
  status = 200;
  opened: [string, string] | undefined;
  headers: Record<string, string> = {};
  sent: unknown;
  aborted = false;
  private listeners = new Map<string, ((event: unknown) => void)[]>();
  upload = {
    addEventListener: (event: string, handler: (e: unknown) => void) => {
      this.on(`upload:${event}`, handler);
    }
  };

  /** Set by a test that wants a header read back; empty means the response exposed none. */
  responseHeaders: Record<string, string> = {ETag: '"fixture-etag"'};

  constructor() {
    FakeXhr.last = this;
  }

  private on(event: string, handler: (e: unknown) => void) {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), handler]);
  }

  addEventListener(event: string, handler: (e: unknown) => void) {
    this.on(event, handler);
  }

  open(method: string, url: string) {
    this.opened = [method, url];
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  /**
   * What a real `XMLHttpRequest` does for a header the response did not expose: answers `null`.
   *
   * It does NOT throw, which is the whole reason the ETag round trip needs a check rather than a
   * try — a CORS regression that stops exposing `ETag` is silent at this layer and only shows up
   * as an assembly request full of nulls.
   */
  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name] ?? null;
  }

  send(body: unknown) {
    this.sent = body;
  }

  abort() {
    this.aborted = true;
    this.fire('abort');
  }

  fire(event: string, payload: unknown = {}) {
    for (const handler of this.listeners.get(event) ?? []) handler(payload);
  }

  progress(loaded: number, total: number) {
    this.fire('upload:progress', {loaded, total, lengthComputable: true});
  }
}

describe('uploadFile', () => {
  beforeEach(() => {
    FakeXhr.last = undefined;
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
  });

  /** A body with a size, without allocating one. */
  function blob(size: number): Blob {
    return {size, type: 'text/csv'} as Blob;
  }

  /**
   * The create route answering `single`, which is what every test in this block drives.
   *
   * The SERVER chooses the path, so a small body gets one presigned `PUT` and the browser never
   * sees a threshold. The multipart answer is `multipartUpload.test.ts`'s subject.
   */
  function mintedUrl(url = 'https://signed.example/put', expiresAt = '2999-01-01T00:00:00Z') {
    api.on('objects.upload', {success: true, data: {mode: 'single', url, expiresAt}});
  }

  it('mints a URL and PUTs the bytes to it', async () => {
    mintedUrl();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    FakeXhr.last!.fire('load');

    expect(await pending).toEqual({success: true, data: {key: 'alice/report.csv'}});
    expect(FakeXhr.last!.opened).toEqual(['PUT', 'https://signed.example/put']);
    expect(api.bodyFor('objects.upload')).toEqual({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/report.csv',
      contentType: 'text/csv',
      overwrite: false,
      // The planning input. No S3 call can supply it — the object does not exist yet — and
      // without it the route cannot decide which path this upload takes.
      size: 10
    });
  });

  it('sends the SIGNED content type, byte for byte', async () => {
    // A different one here fails the signature check at S3 and returns a 403 that reads as a
    // permissions problem rather than as a mismatched header.
    mintedUrl();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());
    FakeXhr.last!.fire('load');
    await pending;

    expect(FakeXhr.last!.headers['Content-Type']).toBe('text/csv');
  });

  it('reports an INTERMEDIATE progress value, not just 0 and 100', async () => {
    // THE assertion this transport exists for. `fetch` fires no upload-progress event, so a
    // `fetch` implementation uploads correctly and leaves the bar at 0% until it jumps to 100% —
    // "the upload succeeded" passes straight over the defect.
    mintedUrl();
    const seen: [number, number][] = [];
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/big.bin',
      body: blob(1000),
      contentType: 'application/octet-stream',
      onProgress: (loaded, total) => seen.push([loaded, total])
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    FakeXhr.last!.progress(400, 1000);
    FakeXhr.last!.fire('load');
    await pending;

    expect(seen.some(([loaded, total]) => loaded > 0 && loaded < total)).toBe(true);
  });

  it('refuses a file over the maximum size before asking for a URL', async () => {
    // A refusal that first asks the API for a URL has already paid for the thing it is refusing.
    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/huge.bin',
      body: blob(maxUploadBytes() + 1),
      contentType: 'application/octet-stream'
    });

    expect(result).toEqual({
      success: false,
      error: {message: `File exceeds the maximum upload size of ${maxUploadBytes()} bytes.`, code: 'TooLarge'}
    });
    expect(api.calls).toEqual([]);
  });

  it('turns the mint’s Conflict into a Collision and never opens a request', async () => {
    // The route mints NO url on a refused overwrite: a route that minted first and checked after
    // would already have handed out the capability.
    api.on('objects.upload', apiFailure('Conflict'));

    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/taken.csv',
      body: blob(10),
      contentType: 'text/csv'
    });

    expect(result).toEqual({
      success: false,
      error: {message: '"alice/taken.csv" already exists.', code: 'Collision'}
    });
    expect(FakeXhr.last).toBeUndefined();
  });

  it('resolves Cancelled and aborts the transfer when the signal fires mid-flight', async () => {
    mintedUrl();
    const controller = new AbortController();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv',
      signal: controller.signal
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    controller.abort();

    expect(await pending).toEqual({
      success: false,
      error: {message: 'Upload cancelled.', code: 'Cancelled'}
    });
    expect(FakeXhr.last!.aborted).toBe(true);
  });

  it('refuses an already-aborted signal without asking for a URL', async () => {
    const controller = new AbortController();
    controller.abort();

    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv',
      signal: controller.signal
    });

    expect(result).toEqual({success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}});
    expect(api.calls).toEqual([]);
  });

  it('detaches the abort listener when the upload finishes normally', async () => {
    // `{once: true}` fires a listener at most once but does NOT detach it, so a long-lived queue
    // signal accumulated one closure per completed file. Aborting AFTER a settled upload must
    // reach nothing.
    mintedUrl();
    const controller = new AbortController();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv',
      signal: controller.signal
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());
    FakeXhr.last!.fire('load');
    await pending;

    controller.abort();

    expect(FakeXhr.last!.aborted).toBe(false);
  });

  it('RESOLVES rather than rejecting when the transport itself throws', async () => {
    // A service in this app never throws, and a promise executor that throws REJECTS. The upload
    // queue awaits this with no catch, so a rejection leaves the item in `uploading` for ever with
    // its concurrency slot never freed and nothing said to the user. `xhr.open` throws on a
    // malformed URL and `setRequestHeader` on an invalid header value, both reachable from a route
    // answer this browser did not compose.
    class ThrowingXhr extends FakeXhr {
      open() {
        throw new SyntaxError("Failed to execute 'open' on 'XMLHttpRequest'");
      }
    }
    vi.stubGlobal('XMLHttpRequest', ThrowingXhr);
    mintedUrl('not a url at all');

    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toContain('open');
  });

  it('tells an EXPIRED link from a denial, which is what expiresAt is for', async () => {
    // A 403 here is routinely an expiry, not a permissions problem: the window is clamped to the
    // signing session's remaining life, and with no part-level retry a large file can simply
    // outlast it. Telling that user to contact an administrator is wrong twice — nothing is
    // misconfigured, and the thing that would help goes unsaid.
    mintedUrl('https://signed.example/put', '2020-01-01T00:00:00Z');
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    FakeXhr.last!.status = 403;
    FakeXhr.last!.fire('load');

    const result = await pending;
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadLinkExpired');
    expect(toUserText(result.error)).toBe('That upload ran out of time before it finished. Upload the file again.');
  });

  it('a 403 on a link that has NOT expired is a denial, not an expiry', async () => {
    mintedUrl();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    FakeXhr.last!.status = 403;
    FakeXhr.last!.fire('load');

    const result = await pending;
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
  });

  it('gives every other refusal a sentence a user can act on, never the generic one', async () => {
    // THE GUARD. A code with no rule resolves to "Something went wrong. Contact the
    // Administrator." — which is the wrong advice for a transfer that wrote nothing and can simply
    // be retried, and it is what an `Http${status}` code produced.
    const generic = 'Something went wrong. Contact the Administrator.';
    for (const status of [403, 500, 503]) {
      mintedUrl();
      const pending = uploadFile({
        bucket: 'user-space',
        key: 'alice/report.csv',
        body: blob(10),
        contentType: 'text/csv'
      });
      await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());
      FakeXhr.last!.status = status;
      FakeXhr.last!.fire('load');

      const result = await pending;
      expect(result.success).toBe(false);
      if (result.success) return;
      expect(toUserText(result.error), `status ${status}`).not.toBe(generic);
    }
  });

  it('does NOT send the bytes when the cancel lands while the URL is being minted', async () => {
    // `addEventListener('abort')` on an already-fired signal never runs, so a listener attached
    // after the mint is attached to a spent signal — the queue row would go straight from
    // `uploading` to Succeeded for a file the user stopped.
    const controller = new AbortController();
    api.on('objects.upload', {
      success: true,
      data: {mode: 'single', url: 'https://signed.example/put', expiresAt: '2999-01-01T00:00:00Z'}
    });
    mockRequest.mockImplementationOnce(async () => {
      controller.abort();
      return {
        success: true,
        data: {mode: 'single', url: 'https://signed.example/put', expiresAt: '2999-01-01T00:00:00Z'}
      };
    });

    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv',
      signal: controller.signal
    });

    expect(result).toEqual({success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}});
    expect(FakeXhr.last).toBeUndefined();
  });

  it('reports a dead connection as a network failure', async () => {
    mintedUrl();
    const pending = uploadFile({
      bucket: 'user-space',
      key: 'alice/report.csv',
      body: blob(10),
      contentType: 'text/csv'
    });
    await vi.waitFor(() => expect(FakeXhr.last).toBeDefined());

    FakeXhr.last!.fire('error');

    expect(await pending).toEqual({
      success: false,
      error: {message: 'Failed to upload file.', code: 'NetworkUnavailable'}
    });
  });
});

describe('the passthrough codes this surface owns are minted CLIENT-SIDE (FR-010)', () => {
  /**
   * A failure as the API really answers one: a machine code, and an EMPTY message.
   *
   * The empty message is the whole test. `apiRequest` puts the server's `detail` in the dev console
   * and nowhere else, so `error.message` arrives as `''` — and `??` does not fall back on the empty
   * string, which is why these services go through `fromApiFailure` and not `toServiceError`. What
   * each case asserts is the exact sentence the app shipped BEFORE the port, minted here from a
   * value this caller already held. There is no "and the server's prose did not leak" assertion
   * beside them: `apiRequest` never surfaces `detail` at all, so such an assertion could not fail
   * and would read as a guard where there is none. The guard is in `apiClient`'s own tests.
   */
  function serverFailure(code: string) {
    return {success: false as const, error: {message: '', code}};
  }

  it('Collision — from a copy, naming the destination the caller already holds', async () => {
    api.on('objects.copy', serverFailure('Conflict'));

    const result = await copyObject({
      bucket: 'user-space',
      sourceKey: 'alice/a.csv',
      destKey: 'alice/taken.csv',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toEqual({message: '"alice/taken.csv" already exists.', code: 'Collision'});
  });

  it('Collision — from an upload, before any byte is sent', async () => {
    api.on('objects.upload', serverFailure('Conflict'));

    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/taken.csv',
      body: {size: 10, type: 'text/csv'} as Blob,
      contentType: 'text/csv'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toEqual({message: '"alice/taken.csv" already exists.', code: 'Collision'});
  });

  it('ProtectedObject — minted before any request is made at all', async () => {
    const result = await deleteObject({
      bucket: 'user-space',
      key: 'alice/DO_NOT_DELETE.txt',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toEqual({
      message: 'This file keeps your storage space active and cannot be deleted.',
      code: 'ProtectedObject'
    });
    expect(api.calls).toEqual([]);
  });

  it('InvalidName — the validator stays in the browser, so the refusal costs nothing', async () => {
    const result = await createFolder({bucket: 'user-space', prefix: 'alice/', name: ' x'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toEqual({
      message: 'Folder name cannot start or end with spaces.',
      code: 'InvalidName'
    });
    expect(api.calls).toEqual([]);
  });

  it('TooLarge — the cap is enforced before a URL is asked for', async () => {
    const result = await uploadFile({
      bucket: 'user-space',
      key: 'alice/huge.bin',
      body: {size: maxUploadBytes() + 1, type: 'application/octet-stream'} as Blob,
      contentType: 'application/octet-stream'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('TooLarge');
    expect(result.error.message).toBe(`File exceeds the maximum upload size of ${maxUploadBytes()} bytes.`);
    expect(api.calls).toEqual([]);
  });

  it('renders each of them as its own sentence, never as the generic one', () => {
    // The other end of the same rule: a passthrough code returns the service's message unchanged,
    // so these four are the only wording a user ever sees for these conditions.
    for (const code of ['Collision', 'ProtectedObject', 'InvalidName', 'TooLarge']) {
      expect(toUserText({code, message: 'the service’s own sentence.'})).toBe('the service’s own sentence.');
    }
  });
});

describe('validateFolderName reserves the app-managed folder', () => {
  it('refuses the name the app manages', () => {
    // Moved here from the group row's own suite when that row was deleted. The reason changed
    // with it: the name used to be spent on a disclosure row that stood in for a prefix which did
    // not exist, and it is now a real folder holding the results, receipts and shared tables the
    // app writes. The refusal outlives the row because the collision it prevents is the same one
    // — two rows of that name at a space root, and a user hunting archive ids opening the wrong.
    expect(validateFolderName(SYSTEM_SETTINGS_FOLDER)).toMatch(/folder the app manages/);
  });

  it('leaves ordinary names, and near-misses, alone', () => {
    // Exact match only: a differently-cased or suffixed name is a distinct row and reads as one.
    expect(validateFolderName('reports')).toBeNull();
    expect(validateFolderName('System_Settings')).toBeNull();
    expect(validateFolderName('system_settings_old')).toBeNull();
  });
});

describe('validateFolderName refuses the app’s own folders inside system_settings', () => {
  // `system_settings/` is writable — no IAM Deny names it — so without this a user can create
  // `system_settings/archive/` themselves, and every rule then treats it as the app's: read-only
  // inside, undeletable, unrenamable, unarchivable, permanently, at the path the restore dialog
  // sends people to for their archive ids.
  it.each(MOVING_FOLDERS)('refuses “%s” when the parent is the app’s folder', (folder) => {
    expect(validateFolderName(folder, 'alice/system_settings/')).toMatch(/the app manages inside/);
  });

  it('leaves those same names alone anywhere else, which is the settled decision', () => {
    // Reserving them generally was considered and rejected: they are ordinary user paths once the
    // migration retires them, and refusing at every depth would take `alice/projects/archive/`
    // with it. This guard is scoped to the ONE parent where the collision is real.
    for (const folder of MOVING_FOLDERS) {
      expect(validateFolderName(folder)).toBeNull();
      expect(validateFolderName(folder, 'alice/')).toBeNull();
      expect(validateFolderName(folder, 'alice/projects/')).toBeNull();
    }
  });

  it('still refuses the app’s folder itself at every depth, parent or no parent', () => {
    expect(validateFolderName(SYSTEM_SETTINGS_FOLDER)).toMatch(/folder the app manages/);
    expect(validateFolderName(SYSTEM_SETTINGS_FOLDER, 'alice/projects/')).toMatch(/folder the app manages/);
  });
});

describe('validateFolderName refuses a name that lands on a picker-locked folder’s home', () => {
  /** The folder a name must be typed in to land on its home — the builder's answer, minus the leaf. */
  const parentOfHome = (root: string, name: string) => appManagedPrefix(root, name).slice(0, -`${name}/`.length);

  it.each(PICKER_LOCKED_FOLDERS)('refuses “%s” typed where its home is, in either kind of space', (name) => {
    for (const root of ['alice/', 'finance/']) {
      expect(validateFolderName(name, parentOfHome(root, name))).toMatch(
        new RegExp(`^“${name}” is a folder the app manages`)
      );
    }
  });

  it('says the folder is the app’s at the top of a space, which is where the rule holds', () => {
    expect(validateFolderName(SHARED_TABLES_FOLDER, 'finance/')).toBe(
      '“shared_tables” is a folder the app manages at the top of a space. Pick another name.'
    );
  });

  it('leaves every one of those names ordinary below the top, and without a parent', () => {
    // The space root is read off the parent. Comparing at the parent instead would refuse
    // `alice/projects/shared_tables/`, a folder the plane and the API both treat as the user's own.
    for (const name of PICKER_LOCKED_FOLDERS.filter((folder) => folder !== SYSTEM_SETTINGS_FOLDER)) {
      expect(validateFolderName(name, 'alice/projects/')).toBeNull();
      expect(validateFolderName(name, 'finance/q1/stage/')).toBeNull();
      expect(validateFolderName(name)).toBeNull();
    }
  });
});
