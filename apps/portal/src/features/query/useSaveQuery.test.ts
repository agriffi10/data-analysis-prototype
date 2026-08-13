import {act, renderHook, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {useSaveQuery} from './useSaveQuery';
import {ensureSavedQueriesFolder, writeSavedQuery} from './savedQueries.service';
import type {QueryTab, SavedQuery} from './query.types';
import type {QuerySpace} from '../catalog/catalog.types';

vi.mock('./savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./savedQueries.service')>()),
  // The name/key helpers stay REAL: `isLinkedSavedQuery` is the rule that decides whether
  // a re-save skips the second confirm, and a stub would decide it for the test.
  ensureSavedQueriesFolder: vi.fn(),
  writeSavedQuery: vi.fn()
}));

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};

const TEAM: QuerySpace = {
  id: 'teamspace',
  label: 'teamspace',
  bucket: 'shared-space',
  rootPrefix: 'teamspace/',
  rootLabel: 'teamspace'
};

const ok = <T>(data: T) => ({success: true as const, data});
const fail = (message: string, code?: string) => ({
  success: false as const,
  error: {message, ...(code ? {code} : {})}
});

const written = (name: string): SavedQuery => ({
  spaceId: PERSONAL.id,
  bucket: PERSONAL.bucket,
  key: `alice/saved_queries/${name}.sql`,
  name,
  updatedAt: '2026-08-12T00:00:00.000Z',
  size: 10
});

function tab(over: Partial<QueryTab> = {}): QueryTab {
  return {id: 'a', label: 'Query 1', sql: 'SELECT 1;', ...over};
}

function setup(over: {activeTab?: QueryTab; spaces?: QuerySpace[]} = {}) {
  const onSaved = vi.fn();
  const toast = {push: vi.fn(), dismiss: vi.fn()};
  const view = renderHook(() =>
    useSaveQuery({
      spaces: over.spaces ?? [PERSONAL],
      defaultSpace: (over.spaces ?? [PERSONAL])[0] ?? null,
      activeTab: over.activeTab ?? tab(),
      onSaved,
      toast
    })
  );
  return {...view, onSaved, toast};
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(ok(undefined));
  vi.mocked(writeSavedQuery).mockImplementation(async ({name}) => ok(written(name)));
});

describe('useSaveQuery (SPEC-175)', () => {
  it('refuses an invalid name with NO request at all (FR-002 AC3)', async () => {
    const {result} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'a/b'}));

    await waitFor(() => expect(result.current.error).toMatch(/cannot contain/i));
    expect(result.current.open).toBe(true);
    expect(writeSavedQuery).not.toHaveBeenCalled();
    expect(ensureSavedQueriesFolder).not.toHaveBeenCalled();
  });

  it('writes even when the folder marker call FAILS (FR-002 AC6)', async () => {
    // The marker is best effort by design — the `PutObject` creates the prefix on its own,
    // so a failed `ensureSavedQueriesFolder` must not become a refusal to save.
    vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(fail('no', 'AccessDenied'));
    const {result, onSaved} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(written('Quarterly'), 'SELECT 1;'));
    expect(writeSavedQuery).toHaveBeenCalledTimes(1);
  });

  it('survives the folder call REJECTING, not just returning a failed result', async () => {
    // The service does not throw by contract; a breach of it must not take the save down
    // with an unhandled rejection (the SPEC-173 lesson, one layer up).
    vi.mocked(ensureSavedQueriesFolder).mockRejectedValue(new Error('boom'));
    const {result, onSaved} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('locks submit while the write is in flight, and unlocks on BOTH outcomes (FR-006 AC5)', async () => {
    let settle: (r: ReturnType<typeof ok<SavedQuery>> | ReturnType<typeof fail>) => void = () => {};
    vi.mocked(writeSavedQuery).mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = resolve;
        })
    );

    const {result} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));
    await waitFor(() => expect(result.current.busy).toBe(true));

    await act(async () => settle(fail('nope', 'AccessDenied')));
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.error).toMatch(/permission/i);

    vi.mocked(writeSavedQuery).mockImplementation(async ({name}) => ok(written(name)));
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.error).toBeNull();
  });

  it('opens on the LINKED tab’s space even when the REMEMBERED one differs (FR-001 AC3)', () => {
    // The two must be discriminated, and everywhere else in this suite they agree — so a
    // `linkedSpace ?? defaultSpace` with either operand deleted would pass. Here they are
    // deliberately different, and getting it wrong writes a COPY into the shared space and
    // re-links the tab to it, silently, while every visible cue stays consistent.
    const linked = {spaceId: 'personal', bucket: 'user-space', key: 'alice/saved_queries/Monthly.sql', name: 'Monthly'};
    const {result} = renderHook(() =>
      useSaveQuery({
        spaces: [PERSONAL, TEAM],
        defaultSpace: TEAM,
        activeTab: tab({savedQuery: linked, label: 'Monthly'}),
        onSaved: vi.fn(),
        toast: {push: vi.fn(), dismiss: vi.fn()}
      })
    );
    expect(result.current.initialSpace).toEqual(PERSONAL);
  });

  it('opens on the REMEMBERED space when the tab is unlinked (FR-001 AC2)', () => {
    // The other half of the same fork, and the reason the pair has to be asserted together.
    const {result} = renderHook(() =>
      useSaveQuery({
        spaces: [PERSONAL, TEAM],
        defaultSpace: TEAM,
        activeTab: tab(),
        onSaved: vi.fn(),
        toast: {push: vi.fn(), dismiss: vi.fn()}
      })
    );
    expect(result.current.initialSpace).toEqual(TEAM);
  });

  it('falls back to the remembered space when the LINK’s space is no longer offered', () => {
    // FR-001 AC4: membership revoked. The dialog then resolves it to personal itself, but
    // the hook must not hand it a space that is not in the list.
    const linked = {
      spaceId: 'gone',
      bucket: 'shared-space',
      key: 'gone/saved_queries/Monthly.sql',
      name: 'Monthly'
    };
    const {result} = renderHook(() =>
      useSaveQuery({
        spaces: [PERSONAL],
        defaultSpace: PERSONAL,
        activeTab: tab({savedQuery: linked, label: 'Monthly'}),
        onSaved: vi.fn(),
        toast: {push: vi.fn(), dismiss: vi.fn()}
      })
    );
    expect(result.current.initialSpace).toEqual(PERSONAL);
  });

  it('opens on the LINKED tab’s name and space, and writes it through without a confirm', async () => {
    // FR-004: the file being replaced is the one whose name the user is looking at.
    const linked = {spaceId: 'personal', bucket: 'user-space', key: 'alice/saved_queries/Monthly.sql', name: 'Monthly'};
    const {result} = setup({activeTab: tab({savedQuery: linked, label: 'Monthly'})});

    expect(result.current.initialName).toBe('Monthly');
    expect(result.current.initialSpace).toEqual(PERSONAL);

    act(() => result.current.save({space: PERSONAL, name: 'Monthly'}));
    await waitFor(() => expect(writeSavedQuery).toHaveBeenCalledWith(expect.objectContaining({overwrite: true})));
    expect(result.current.collision).toBeNull();
  });

  it('takes any OTHER key through the collision round-trip, keeping what was chosen', async () => {
    vi.mocked(writeSavedQuery).mockImplementation(async ({name, overwrite}) =>
      overwrite ? ok(written(name)) : fail(`“${name}” already exists.`, 'Collision')
    );
    const {result, onSaved} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));

    await waitFor(() => expect(result.current.collision).toEqual({space: PERSONAL, name: 'Quarterly'}));
    expect(result.current.open).toBe(false);

    // Backing out returns to the dialog with BOTH halves of the choice intact, and drops
    // the confirm — the next Save re-decides against the key rather than replaying it.
    act(() => result.current.cancelReplace());
    expect(result.current.open).toBe(true);
    expect(result.current.initialName).toBe('Quarterly');
    expect(result.current.initialSpace).toEqual(PERSONAL);
    expect(result.current.collision).toBeNull();

    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));
    await waitFor(() => expect(result.current.collision).not.toBeNull());
    act(() => result.current.confirmReplace());
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(written('Quarterly'), 'SELECT 1;'));
    expect(result.current.collision).toBeNull();
    expect(result.current.open).toBe(false);
  });

  it('drops a failed attempt’s message and name when the dialog is re-opened', async () => {
    // A stale error over a fresh, empty field would be a message about nothing.
    vi.mocked(writeSavedQuery).mockResolvedValue(fail('nope', 'AccessDenied'));
    const {result} = setup();
    act(() => result.current.save({space: PERSONAL, name: 'Quarterly'}));
    await waitFor(() => expect(result.current.error).not.toBeNull());

    act(() => result.current.openDialog());
    expect(result.current.error).toBeNull();
    expect(result.current.initialName).toBe('');
  });
});
