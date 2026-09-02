import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
  __resetSavedQueriesFolderCache,
  deleteSavedQuery,
  ensureSavedQueriesFolder,
  isLinkedSavedQuery,
  listSavedQueries,
  readSavedQuery,
  savedQueryKey,
  savedQueryName,
  validateSavedQueryName,
  writeSavedQuery
} from './savedQueries.service';
import {SAVED_QUERIES_MARKER_BODY} from '../file-browser';
import type {SavedQueryLink} from './savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

// The AWS boundary is the only seam (react.md §21): the service composes
// `objectExists`/`deleteObject` from the file browser and `readJsonDocument` from `lib/`,
// and every one of them lands on this same client.
const {mockSend} = vi.hoisted(() => ({mockSend: vi.fn()}));

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: mockSend
}));

// `spaceFor` asks which bucket is the shared-space one, and that answer comes from the runtime
// configuration document — absent in a unit test, which would resolve every space to `personal`
// and make the shared-space assertions below agree with the wrong answer.
vi.mock('../../lib/userSpace', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/userSpace')>()),
  userSpaceBucket: () => 'user-space',
  sharedSpaceBucket: () => 'shared-space'
}));

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};

const SHARED: QuerySpace = {
  id: 'project_alpha',
  label: 'project_alpha',
  bucket: 'shared-space',
  rootPrefix: 'project_alpha/',
  rootLabel: 'project_alpha'
};

beforeEach(() => {
  vi.clearAllMocks();
  __resetSavedQueriesFolderCache();
});

/** The route's answer when a key is absent — one spelling now, where the SDK had three. */
function notFound() {
  return {success: false as const, error: {message: '', code: 'NotFound'}};
}

/** A write or a copy answering successfully. */
function written(key = 'k') {
  return {success: true as const, data: {key, etag: 'e'}};
}

/** One page from the listing route: files and folders in one array, each with a `kind`. */
function listed(
  contents: {Key: string; Size?: number; LastModified?: Date}[],
  rest: {IsTruncated?: boolean; NextContinuationToken?: string; CommonPrefixes?: {Prefix: string}[]} = {}
) {
  return {
    success: true as const,
    data: {
      items: contents.map((object) => ({
        kind: 'file' as const,
        key: object.Key,
        size: object.Size ?? 0,
        lastModified: (object.LastModified ?? new Date(0)).toISOString()
      })),
      nextToken: rest.NextContinuationToken ?? null
    }
  };
}

/** Every call to one route, in order — the successor of filtering by SDK command type. */
const callsTo = (route: string) => mockSend.mock.calls.filter((call) => call[0] === route);

describe('the name ↔ key rules (FR-004)', () => {
  it('never doubles the extension, and strips it case-insensitively', () => {
    expect(savedQueryKey('alice/', 'report.sql')).toBe('alice/saved_queries/report.sql');
    // A key already in the bucket may carry any case — the store still reads it.
    expect(savedQueryName('alice/saved_queries/REPORT.SQL')).toBe('REPORT');
  });

  it('LOWERCASES a typed extension, so one name is one key (SPEC-175 FR-002 AC4)', () => {
    // `savedQueryName` strips the extension case-insensitively, so `report.SQL` left alone
    // would be a second object rendering identically to `report.sql` everywhere the user
    // can see — and a re-save from a tab linked to one would resolve to, and replace, the
    // other. The STEM is untouched: `REPORT` and `report` stay two visible names.
    for (const typed of ['report', 'report.sql', 'report.SQL', 'report.Sql']) {
      expect(savedQueryKey('alice/', typed)).toBe('alice/saved_queries/report.sql');
    }
    expect(savedQueryKey('alice/', 'REPORT.SQL')).toBe('alice/saved_queries/REPORT.sql');
    expect(savedQueryName(savedQueryKey('alice/', 'REPORT.SQL'))).toBe('REPORT');
  });
});

describe('validateSavedQueryName (FR-004)', () => {
  it.each([
    ['', /empty/i],
    ['   ', /empty/i],
    [' leading', /spaces/i],
    ['trailing ', /spaces/i],
    ['a/b', /'\/'/],
    ['tab\there', /control characters/i],
    // 126 characters + `.sql` = 130, over the 128 ceiling — measured on the RESULTING
    // basename, because the extension the user did not type still counts toward the key.
    ['x'.repeat(126), /128 characters/]
  ])('refuses %j', (name, expected) => {
    expect(validateSavedQueryName(name)).toMatch(expected);
  });
});

describe('isLinkedSavedQuery (SPEC-175 FR-004)', () => {
  // The most dangerous predicate in the save path: a `true` here is what lets the write
  // skip the HEAD and clobber, so every edge is asserted directly rather than through a
  // caller where a wrong answer mostly still looks right.
  const LINK: SavedQueryLink = {
    spaceId: 'personal',
    bucket: 'user-space',
    key: 'alice/saved_queries/Monthly.sql',
    name: 'Monthly'
  };

  it('is true for the name that resolves to the linked key, extension typed or not', () => {
    expect(isLinkedSavedQuery(LINK, PERSONAL, 'Monthly')).toBe(true);
    expect(isLinkedSavedQuery(LINK, PERSONAL, 'Monthly.sql')).toBe(true);
    expect(isLinkedSavedQuery(LINK, PERSONAL, '  Monthly  ')).toBe(true);
  });

  it('is false for a different NAME in the linked space', () => {
    expect(isLinkedSavedQuery(LINK, PERSONAL, 'Monthly-v2')).toBe(false);
    // Keys are case-sensitive, so this is a different file and must take the HEAD.
    expect(isLinkedSavedQuery(LINK, PERSONAL, 'monthly')).toBe(false);
  });

  it('is false for a link whose space is a different bucket at the same key', () => {
    // Contrived, and deliberately asserted: the key alone is not identity across buckets.
    const crossBucket: SavedQueryLink = {...LINK, bucket: 'shared-space'};
    expect(isLinkedSavedQuery(crossBucket, PERSONAL, 'Monthly')).toBe(false);
  });
});

describe('ensureSavedQueriesFolder (FR-001)', () => {
  it('writes the marker in ONE call, refusing to overwrite', async () => {
    mockSend.mockResolvedValue(written());

    const result = await ensureSavedQueriesFolder(PERSONAL);

    expect(result.success).toBe(true);
    // ONE call, not a check and then a write. The check the browser used to make first is now the
    // route's own `overwrite: false`, so the two cannot disagree and the caller pays one round
    // trip. The bucket no longer travels either: the API resolves the space from verified claims.
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(callsTo('objects.writeContent')[0][1].body).toMatchObject({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/saved_queries/DO_NOT_DELETE.txt',
      body: SAVED_QUERIES_MARKER_BODY,
      overwrite: false
    });
  });

  it('reads the route’s Conflict as "already there", not as a failure', async () => {
    mockSend.mockResolvedValue({success: false, error: {message: '', code: 'Conflict'}});

    const result = await ensureSavedQueriesFolder(PERSONAL);

    expect(result).toEqual({success: true, data: undefined});
  });

  it('checks each space separately', async () => {
    mockSend.mockResolvedValue(written());

    await ensureSavedQueriesFolder(PERSONAL);
    await ensureSavedQueriesFolder(SHARED);

    expect(callsTo('objects.writeContent').map((c) => c[1].body.key)).toEqual([
      'alice/saved_queries/DO_NOT_DELETE.txt',
      'project_alpha/saved_queries/DO_NOT_DELETE.txt'
    ]);
  });
});

describe('listSavedQueries (FR-004)', () => {
  it('lists ONE level of the folder, at the listing page size', async () => {
    mockSend.mockResolvedValue(listed([]));

    await listSavedQueries({space: PERSONAL});

    // The bucket, the delimiter and the page size are the ROUTE's business now — it delimits and
    // bounds every listing itself, which is the thinness rule the API asserts on its own side.
    // What the browser still owns, and what this asserts, is which folder it asked for.
    expect(callsTo('objects.list')[0][1].query).toMatchObject({
      spaceKind: 'personal',
      spaceName: 'alice',
      prefix: 'alice/saved_queries/'
    });
  });

  it('offers top-level .sql files and NOTHING else', async () => {
    // FR-004: the folder is ordinary, so a user may drop anything into it. The filter is
    // the whole defence — a CSV, an extensionless file and the marker are all normal
    // files that belong to the file browser and are invisible here.
    mockSend.mockResolvedValue(
      listed(
        [
          {Key: 'alice/saved_queries/DO_NOT_DELETE.txt'},
          {Key: 'alice/saved_queries/notes.csv'},
          {Key: 'alice/saved_queries/README'},
          {Key: 'alice/saved_queries/report.sql'},
          {Key: 'alice/saved_queries/REPORT.SQL'}
        ],
        {CommonPrefixes: [{Prefix: 'alice/saved_queries/archive/'}]}
      )
    );

    const result = await listSavedQueries({space: PERSONAL});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.queries.map((q) => q.name)).toEqual(['report', 'REPORT']);
  });

  it('does NOT return a .sql file one level down — the depth check is the browser’s half', async () => {
    // A nested key can only reach the response if the route's delimiter is dropped, and the route
    // is where that is asserted. This is the OTHER half: the top-level rule is written down here,
    // in TypeScript, and it catches the key the delimiter would have.
    mockSend.mockResolvedValue(
      listed([{Key: 'alice/saved_queries/archive/old.sql'}, {Key: 'alice/saved_queries/current.sql'}])
    );

    const result = await listSavedQueries({space: PERSONAL});

    expect(result.success && result.data.queries.map((q) => q.key)).toEqual(['alice/saved_queries/current.sql']);
  });

  it('carries the space, the key, the name, the modified time and the size', async () => {
    mockSend.mockResolvedValue(
      listed([{Key: 'project_alpha/saved_queries/q1.sql', Size: 42, LastModified: new Date('2026-08-11T09:00:00Z')}])
    );

    const result = await listSavedQueries({space: SHARED});

    expect(result.success && result.data.queries[0]).toEqual({
      spaceId: 'project_alpha',
      bucket: 'shared-space',
      key: 'project_alpha/saved_queries/q1.sql',
      name: 'q1',
      updatedAt: '2026-08-11T09:00:00.000Z',
      size: 42
    });
  });

  it('threads the continuation token and reports the next one', async () => {
    mockSend.mockResolvedValue(listed([], {IsTruncated: true, NextContinuationToken: 'page-2'}));

    const result = await listSavedQueries({space: PERSONAL, continuationToken: 'page-1'});

    expect(callsTo('objects.list')[0][1].query.nextToken).toBe('page-1');
    expect(result.success && result.data).toMatchObject({isTruncated: true, nextContinuationToken: 'page-2'});
  });

  it('treats a missing folder as an EMPTY list, not an error', async () => {
    mockSend.mockResolvedValue(listed([]));

    const result = await listSavedQueries({space: PERSONAL});

    expect(result).toEqual({success: true, data: {queries: [], isTruncated: false, nextContinuationToken: undefined}});
  });
});

describe('readSavedQuery (FR-004)', () => {
  it('returns the object body as a string — a .sql file rides the document route unparsed', async () => {
    mockSend.mockResolvedValue({success: true, data: {body: 'SELECT 1', etag: 'e'}});

    const result = await readSavedQuery({bucket: 'user-space', key: 'alice/saved_queries/q1.sql'});

    expect(result).toEqual({success: true, data: 'SELECT 1'});
    expect(callsTo('objects.readContent')[0][1].query).toMatchObject({key: 'alice/saved_queries/q1.sql'});
  });

  it('names the query in a user-safe message when the file is gone', async () => {
    mockSend.mockResolvedValue(notFound());

    const result = await readSavedQuery({bucket: 'user-space', key: 'alice/saved_queries/Q1 revenue.sql'});

    expect(result.success).toBe(false);
    if (result.success) return;
    // A user looking at twenty-five rows needs to know WHICH one vanished.
    expect(result.error.message).toContain('Q1 revenue');
    expect(result.error.message).not.toContain('NotFound');
    expect(result.error.code).toBe('SavedQueryNotFound');
  });
});

describe('writeSavedQuery (FR-004)', () => {
  it('refuses a collision rather than clobbering, in ONE call, NAMING the query', async () => {
    // The name in the sentence is the one the user sees in the list — `report`, not
    // `report.sql` — so it is minted here from the key rather than taken from the wire.
    mockSend.mockResolvedValue({success: false, error: {message: '', code: 'Conflict'}});

    const result = await writeSavedQuery({space: PERSONAL, name: 'report', sql: 'SELECT 1'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(result.error.message).toBe('“report” already exists.');
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(callsTo('objects.writeContent')[0][1].body).toMatchObject({
      key: 'alice/saved_queries/report.sql',
      overwrite: false
    });
  });

  it('writes with overwrite when asked, and returns the SavedQuery just written', async () => {
    mockSend.mockResolvedValue(written());

    const result = await writeSavedQuery({space: PERSONAL, name: 'report', sql: 'SELECT 1', overwrite: true});

    expect(callsTo('objects.writeContent')[0][1].body).toMatchObject({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/saved_queries/report.sql',
      body: 'SELECT 1',
      contentType: 'text/plain; charset=utf-8',
      overwrite: true
    });
    expect(result.success && result.data).toMatchObject({
      spaceId: 'personal',
      bucket: 'user-space',
      key: 'alice/saved_queries/report.sql',
      name: 'report'
    });
  });

  it('writes into a shared space at the space’s own root', async () => {
    mockSend.mockResolvedValue(written());

    const result = await writeSavedQuery({space: SHARED, name: 'q1', sql: 'SELECT 2'});

    expect(result.success).toBe(true);
    expect(callsTo('objects.writeContent')[0][1].body).toMatchObject({
      space: {kind: 'shared', name: 'project_alpha'},
      key: 'project_alpha/saved_queries/q1.sql'
    });
  });
});

describe('deleteSavedQuery (FR-004)', () => {
  it('delegates to deleteObject, so the prefix-marker refusal applies unchanged', async () => {
    mockSend.mockResolvedValue({success: true, data: {key: 'alice/saved_queries/report.sql'}});

    const result = await deleteSavedQuery({
      bucket: 'user-space',
      key: 'alice/saved_queries/report.sql',
      username: 'alice'
    });

    expect(result).toEqual({success: true, data: undefined});
  });
});

describe('savedQueryName is the ONLY place a `.sql` extension is stripped (SPEC-174 FR-004 AC4)', () => {
  it('no other module in the query feature strips the extension itself', async () => {
    // A tab label and a list row must never disagree about what a file is called, and the
    // way that happens is a second extension-strip at a call site. A sweep, not a
    // description: the duplicate this forbids would pass every other test in the suite.
    // Verified against a deliberate violation (a `.replace(/\.sql$/, '')` on the tab label
    // in `QueryWorkspace.handleOpenSaved`), which it caught.
    const files = import.meta.glob('./*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
      string,
      string
    >;
    const offenders = Object.entries(files)
      .filter(([path]) => !path.includes('savedQueries.service'))
      .filter(([, body]) => /\.sql/i.test(body) && /(replace|slice|split|endsWith)\([^\n]*\.sql/i.test(body))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});

describe('writeSavedQuery refusals', () => {
  it('refuses an invalid name before any request is made', async () => {
    const result = await writeSavedQuery({space: PERSONAL, name: 'a/b', sql: 'SELECT 1;'});

    expect(result).toEqual({success: false, error: expect.objectContaining({code: 'InvalidName'})});
    expect(mockSend).not.toHaveBeenCalled();
  });
});
