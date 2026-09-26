import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {readExplorationTabsState} from './explorationTabs';
import {chooseExplorationOption} from './explorationOptions.testkit';
import {fullExploration, renderExplorer} from './savedView.testkit';

vi.mock('../catalog/glue.service', () => ({getDatabase: vi.fn(), listTables: vi.fn()}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});

/** A session holding one tab reopened from a shared space's saved view, as a reload finds it. */
function seedHeldTab(awaitingRun: unknown) {
  const exploration = fullExploration();
  sessionStorage.setItem(
    `${EXPLORATION_TABS_STORAGE_PREFIX}alice`,
    JSON.stringify({
      version: 1,
      tabs: [
        {id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}, awaitingRun}
      ],
      activeTabId: 't1'
    })
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 10, engineExecutionTimeMillis: 1})
  );
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({columns: [{name: 'region', type: 'varchar'}], rows: [['west']]}) as never
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a held tab', () => {
  it.each([
    ['as it was stored', {space: 'teamspace', leftOut: {links: 0, patterns: 0}}, /saved in teamspace/],
    ['when what was stored is malformed', 'garbage', /saved in a shared space/]
  ])('stays held across a reload %s', async (_label, awaitingRun, text) => {
    seedHeldTab(awaitingRun);

    renderExplorer();

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run'})).toBeInTheDocument();
    expect(runQuery).not.toHaveBeenCalled();
  });

  it('shows none of the rows an identical, unheld tab already ran', async () => {
    const exploration = fullExploration();
    const tab = (id: string, label: string) => ({
      id,
      label,
      exploration,
      scannedByExecution: {},
      history: {past: [], future: []}
    });
    sessionStorage.setItem(
      `${EXPLORATION_TABS_STORAGE_PREFIX}alice`,
      JSON.stringify({
        version: 1,
        tabs: [
          tab('a', 'first'),
          {...tab('b', 'second'), awaitingRun: {space: 'teamspace', leftOut: {links: 0, patterns: 0}}}
        ],
        activeTabId: 'a'
      })
    );
    const {user} = renderExplorer();
    await waitFor(() => expect(getQueryResults).toHaveBeenCalled());

    await user.click(screen.getByRole('tab', {name: /second/}));

    expect(await screen.findByRole('button', {name: 'Run'})).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(readExplorationTabsState('alice')?.tabs[1].scannedByExecution).toEqual({});
  });

  it('runs once and stops holding when the user changes its query', async () => {
    seedHeldTab({space: 'teamspace', leftOut: {links: 0, patterns: 0}});
    const {user} = renderExplorer();
    await screen.findByRole('button', {name: 'Run'});

    await chooseExplorationOption(user, 'Remove all filters, sorts and grouping');

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('button', {name: 'Run'})).not.toBeInTheDocument();
    expect(readExplorationTabsState('alice')?.tabs[0]).not.toHaveProperty('awaitingRun');
  });
});
