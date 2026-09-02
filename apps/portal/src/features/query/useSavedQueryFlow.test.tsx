import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {useToast} from '../../components/toastContext';
import {
  deleteSavedQuery,
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery
} from '../saved-queries/savedQueries.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {QUERY_TABS_MAX, QUERY_TABS_STORAGE_PREFIX} from './query.constants';
import {useQueryTabs} from './useQueryTabs';
import {useSavedQueryFlow} from './useSavedQueryFlow';
import type {SavedQuery} from '../saved-queries/savedQueries.types';

vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
// The space resolver asks which buckets exist; a unit test has no runtime document to answer.
vi.mock('../../lib/userSpace', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/userSpace')>()),
  spaceBuckets: () => ({user: 'user-space', shared: 'shared-space'})
}));

const monthly: SavedQuery = {
  spaceId: 'personal',
  bucket: 'user-space',
  key: 'alice/saved_queries/Monthly.sql',
  name: 'Monthly',
  updatedAt: '2026-07-01T10:00:00.000Z',
  size: 24
};

function render() {
  const focusEditor = vi.fn();
  const onTabLimit = vi.fn();
  const onOpened = vi.fn();
  const rendered = renderHookWithProviders(() => {
    const tabs = useQueryTabs('alice');
    const toast = useToast();
    const flow = useSavedQueryFlow({
      username: 'alice',
      sharedSpacesEnabled: false,
      tabs,
      toast,
      focusEditor,
      onTabLimit,
      onOpened
    });
    return {tabs, flow};
  });
  return {...rendered, focusEditor, onTabLimit, onOpened};
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: true, data: {version: 1, connections: []}});
  vi.mocked(ensureSavedQueriesFolder).mockResolvedValue({success: true, data: undefined});
  vi.mocked(listSavedQueries).mockResolvedValue({success: true, data: {queries: [], isTruncated: false}});
  vi.mocked(readSavedQuery).mockResolvedValue({success: true, data: 'SELECT 1;'});
  vi.mocked(deleteSavedQuery).mockResolvedValue({success: true, data: undefined});
});

describe('useSavedQueryFlow', () => {
  it('opens a saved query into a linked tab with ONE read, and hands the editor back', async () => {
    const {result, onOpened, focusEditor} = render();

    act(() => result.current.flow.openSaved(monthly));

    await waitFor(() => expect(result.current.tabs.tabs.map((t) => t.label)).toContain('Monthly'));
    expect(readSavedQuery).toHaveBeenCalledTimes(1);
    expect(readSavedQuery).toHaveBeenCalledWith({bucket: 'user-space', key: monthly.key});
    expect(result.current.tabs.activeTab.savedQuery?.key).toBe(monthly.key);
    expect(onOpened).toHaveBeenCalledTimes(1);
    expect(focusEditor).toHaveBeenCalledTimes(1);
  });

  it('opens NO tab and says which file is gone when its body cannot be read', async () => {
    vi.mocked(readSavedQuery).mockResolvedValue({
      success: false,
      error: {message: '“Monthly” no longer exists.', code: 'SavedQueryNotFound'}
    });
    const {result, onOpened} = render();
    const before = result.current.tabs.tabs.length;

    act(() => result.current.flow.openSaved(monthly));

    expect(await screen.findByText('“Monthly” no longer exists.')).toBeInTheDocument();
    expect(result.current.tabs.tabs).toHaveLength(before);
    expect(onOpened).not.toHaveBeenCalled();
  });

  it('checks the tab cap BEFORE reading, so a refused open costs no request', async () => {
    const tabs = Array.from({length: QUERY_TABS_MAX}, (_, i) => ({id: `t${i}`, label: `Query ${i + 1}`, sql: ''}));
    sessionStorage.setItem(
      `${QUERY_TABS_STORAGE_PREFIX}alice`,
      JSON.stringify({version: 1, tabs, activeTabId: 't0', nextQueryNumber: QUERY_TABS_MAX + 1})
    );
    const {result, onTabLimit} = render();
    expect(result.current.tabs.tabs).toHaveLength(QUERY_TABS_MAX);

    act(() => result.current.flow.openSaved(monthly));

    expect(onTabLimit).toHaveBeenCalledTimes(1);
    expect(readSavedQuery).not.toHaveBeenCalled();
  });
});
