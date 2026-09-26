import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {QueryClient} from '@tanstack/react-query';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery,
  writeSavedQuery
} from '../saved-queries/savedQueries.service';
import {readExplorationTabsState} from './explorationTabs';
import {chooseExplorationOption} from './explorationOptions.testkit';
import {fullExploration, renderedSql, renderExplorer, savedFile, savedFileText} from './savedView.testkit';
import type {SavedQuery} from '../saved-queries/savedQueries.types';

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
vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  ensureSavedQueriesFolder: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});
const connections = (...names: string[]) =>
  ok({version: 1, connections: names.map((name) => ({name, role: 'member', status: 'active'}))});

/** Each space's `saved_queries/` folder, and each file's text, as the store answers them. */
function store(files: {file: SavedQuery; text: string}[]) {
  vi.mocked(listSavedQueries).mockImplementation(async ({space}) =>
    ok({queries: files.filter(({file}) => file.spaceId === space.id).map(({file}) => file), isTruncated: false})
  );
  vi.mocked(readSavedQuery).mockImplementation(async ({key}) =>
    ok(files.find(({file}) => file.key === key)?.text ?? '')
  );
}

/** Open the drawer from the picker, choose a space, and open one file. */
async function openFromDrawer(user: ReturnType<typeof renderExplorer>['user'], name: string, space = 'alice') {
  await user.click(await screen.findByRole('button', {name: 'Open saved view'}));
  const drawer = await screen.findByRole('dialog', {name: 'Open saved view'});
  if (space !== 'alice') await user.selectOptions(within(drawer).getByRole('combobox'), space);
  await user.click(await within(drawer).findByRole('button', {name: `Open saved view ${name}`}));
}

const storedTab = () => readExplorationTabsState('alice')?.tabs.at(-1);

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(connections('teamspace') as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 10, engineExecutionTimeMillis: 1})
  );
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({columns: [{name: 'region', type: 'varchar'}], rows: [['west']]}) as never
  );
  vi.mocked(writeSavedQuery).mockImplementation(async ({name}) => ok(savedFile(name)));
  vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(ok(undefined));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a view reopened from the personal folder', () => {
  it('comes back whole, runs, and stays linked to its file', async () => {
    const exploration = fullExploration();
    store([{file: savedFile('Orders view'), text: savedFileText(exploration)}]);
    const {user} = renderExplorer();

    await openFromDrawer(user, 'Orders view');

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0].sql).toBe(renderedSql(exploration));
    const tab = storedTab();
    expect(tab?.exploration.query).toEqual(exploration.query);
    expect(tab?.exploration.presentation).toEqual(exploration.presentation);
    expect(tab?.savedQuery).toEqual({
      spaceId: 'personal',
      bucket: 'user-space',
      key: 'alice/saved_queries/Orders view.sql',
      name: 'Orders view'
    });
    expect(tab?.history).toEqual({past: [], future: []});
    expect(within(screen.getByRole('list', {name: 'Column filters'})).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.queryByRole('dialog', {name: 'Open saved view'})).not.toBeInTheDocument();

    await chooseExplorationOption(user, 'Save as query');
    const dialog = await screen.findByRole('dialog', {name: 'Save query'});
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Orders view');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));
    await waitFor(() =>
      expect(writeSavedQuery).toHaveBeenCalledWith(expect.objectContaining({name: 'Orders view', overwrite: true}))
    );
  });

  it('waits for the connections list before deciding a shared database is out of reach', async () => {
    const exploration = fullExploration('teamspace');
    store([{file: savedFile('Team view'), text: savedFileText(exploration)}]);
    vi.mocked(readSharedConnectionsCache)
      .mockResolvedValueOnce(connections() as never)
      .mockResolvedValue(connections('teamspace') as never);
    const {user} = renderExplorer();

    await openFromDrawer(user, 'Team view');

    await waitFor(() =>
      expect(storedTab()?.exploration.source).toMatchObject({spaceId: 'teamspace', database: 'teamspace'})
    );
    expect(screen.queryByRole('alertdialog', {name: 'Saved view can’t be opened'})).not.toBeInTheDocument();
  });
});

describe('a view reopened from a shared space’s folder', () => {
  it('is held, unlinked, and without the author’s link columns and pattern rules until the user runs it', async () => {
    const exploration = fullExploration('teamspace');
    store([{file: savedFile('Team view', 'teamspace'), text: savedFileText(exploration)}]);
    const {user} = renderExplorer();

    await openFromDrawer(user, 'Team view', 'teamspace');

    expect(
      await screen.findByText(/This view was saved in teamspace, where any member can change it/)
    ).toBeInTheDocument();
    expect(screen.getByText('Left out: 1 link column, 2 pattern color rules.')).toBeInTheDocument();
    expect(screen.queryByText('Running…')).not.toBeInTheDocument();
    await user.click(screen.getByText('Generated SQL'));
    expect(screen.getByLabelText('Generated SQL')).toHaveValue(renderedSql(exploration));
    expect(runQuery).not.toHaveBeenCalled();
    const formatting = storedTab()?.exploration.presentation.formatting;
    expect(Object.keys(formatting?.transformers ?? {})).toEqual(['amount']);
    expect(formatting?.rules.map((rule) => rule.id)).toEqual(['r3']);
    expect(storedTab()?.savedQuery).toBeUndefined();

    await user.click(screen.getByRole('button', {name: 'Run'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    await chooseExplorationOption(user, 'Save as query');
    expect(within(await screen.findByRole('dialog', {name: 'Save query'})).getByLabelText('Name')).toHaveValue('');
  });

  it('is held even when the view it holds explores the opener’s own database', async () => {
    store([{file: savedFile('Your data', 'teamspace'), text: savedFileText(fullExploration('alice'))}]);
    const {user} = renderExplorer();

    await openFromDrawer(user, 'Your data', 'teamspace');

    expect(await screen.findByRole('button', {name: 'Run'})).toBeInTheDocument();
    expect(storedTab()?.exploration.source).toMatchObject({spaceId: 'personal', database: 'alice'});
    expect(runQuery).not.toHaveBeenCalled();
  });
});

describe('the list of saved views', () => {
  it('shows a view saved a moment ago, although the listing was cached before the save', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {queries: {staleTime: 30_000, gcTime: Infinity, retry: false}}
    });
    const listed: SavedQuery[] = [savedFile('Older view')];
    vi.mocked(listSavedQueries).mockImplementation(async () => ok({queries: [...listed], isTruncated: false}));
    vi.mocked(readSavedQuery).mockResolvedValue(ok(savedFileText(fullExploration())));
    vi.mocked(writeSavedQuery).mockImplementation(async ({name}) => {
      listed.push(savedFile(name));
      return ok(savedFile(name));
    });
    const {user} = renderExplorer({queryClient});
    await openFromDrawer(user, 'Older view');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(listSavedQueries).toHaveBeenCalledTimes(1);

    await chooseExplorationOption(user, 'Save as query');
    const dialog = await screen.findByRole('dialog', {name: 'Save query'});
    await user.clear(within(dialog).getByLabelText('Name'));
    await user.type(within(dialog).getByLabelText('Name'), 'Newer view');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));
    await waitFor(() => expect(writeSavedQuery).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', {name: 'New exploration'}));
    await user.click(await screen.findByRole('button', {name: 'Open saved view'}));

    expect(await screen.findByRole('button', {name: 'Open saved view Newer view'})).toBeInTheDocument();
    expect(listSavedQueries).toHaveBeenCalledTimes(2);
  });
});
