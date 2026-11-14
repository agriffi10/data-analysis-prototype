import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {VIEW_LINE_MARKER, viewChecksum} from '../../lib/savedViewLine';
import {toUserText} from '../../lib/errorMessages';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {getDatabase, listTables} from '../catalog/glue.service';
import {runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {listSavedQueries, readSavedQuery} from '../saved-queries/savedQueries.service';
import {readExplorationTabsState} from './explorationTabs';
import {buildSavedView} from './savedView';
import {fullExploration, renderedSql, renderExplorer, savedFile, savedFileText} from './savedView.testkit';

vi.mock('../catalog/glue.service', () => ({getDatabase: vi.fn(), listTables: vi.fn()}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});
const saved = savedFileText(fullExploration());
const sql = renderedSql(fullExploration());
const FILE = savedFile('Orders view');

async function openTheFile() {
  const view = renderExplorer();
  await view.user.click(await screen.findByRole('button', {name: 'Open saved view'}));
  await view.user.click(await screen.findByRole('button', {name: 'Open saved view Orders view'}));
  return view;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([]) as never);
  vi.mocked(listSavedQueries).mockResolvedValue(ok({queries: [FILE], isTruncated: false}));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a saved query that cannot reopen as a view', () => {
  it.each([
    ['saved from Query', `${sql}\n`, '“Orders view” has no Data Explorer view saved in it.'],
    [
      'edited since',
      saved.replace("'void'", "'paid'"),
      '“Orders view” has been edited since it was saved from the Data Explorer, so its view no longer describes it.'
    ],
    [
      'from a newer build',
      saved.replace(`${VIEW_LINE_MARKER}v1:`, `${VIEW_LINE_MARKER}v9:`),
      '“Orders view” was saved by a newer version of Data Quarry.'
    ],
    [
      'carrying a view that will not decode',
      `${sql}\n${VIEW_LINE_MARKER}v1:nonsense\n`,
      '“Orders view” carries a view that can’t be read.'
    ],
    [
      'larger than any file this build writes',
      // A VALID view under an oversized statement, so the size bound is the only thing refusing it.
      (() => {
        const big = `${sql}\n${'-- padding\n'.repeat(30_000)}`.trimEnd();
        const payload = btoa(JSON.stringify(buildSavedView(fullExploration())))
          .replace(/\+/g, '-')
          .replace(/\//g, '_')
          .replace(/=+$/, '');
        return `${big}\n${VIEW_LINE_MARKER}v1:${viewChecksum(big)}:${payload}\n`;
      })(),
      '“Orders view” is too large to open as a view.'
    ],
    [
      'over a database the user cannot reach',
      savedFileText(fullExploration('payroll')),
      'You don’t have access to payroll, the database this view explores.'
    ]
  ])('is refused when %s, with no tab and nothing run', async (_label, text, message) => {
    vi.mocked(readSavedQuery).mockResolvedValue(ok(text));

    await openTheFile();

    const dialog = await screen.findByRole('alertdialog', {name: 'Can’t be opened as a view'});
    expect(within(dialog).getByText(message)).toBeInTheDocument();
    expect(readExplorationTabsState('alice')?.tabs ?? []).toHaveLength(0);
    expect(runQuery).not.toHaveBeenCalled();
  });

  it('hands its SQL, without the view line, to a new Query tab that runs nothing', async () => {
    const text = saved.replace("'void'", "'paid'");
    vi.mocked(readSavedQuery).mockResolvedValue(ok(text));
    const {user, location} = await openTheFile();
    await screen.findByRole('alertdialog', {name: 'Can’t be opened as a view'});
    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);

    await user.click(screen.getByRole('button', {name: 'Open in Query'}));

    await waitFor(() => expect(window.location.pathname).toBe('/query'));
    expect(location().state).toEqual({
      openSql: {sql: sql.replace("'void'", "'paid'"), label: 'Orders view'}
    });
  });

  it('says the file could not be read, leaves the list open and offers no Open in Query', async () => {
    const error = {message: 'gone', code: 'NotFound'};
    vi.mocked(readSavedQuery).mockResolvedValue({success: false, error});

    await openTheFile();

    // A danger toast in the store's own words: the mapped sentence, never the raw error text.
    expect(await screen.findByRole('alert')).toHaveTextContent(toUserText(error));
    expect(screen.getByRole('dialog', {name: 'Open saved view'})).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Open saved view Orders view'})).toHaveAttribute(
        'aria-disabled',
        'false'
      )
    );
    expect(screen.queryByRole('alertdialog', {name: 'Can’t be opened as a view'})).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('gone');
  });
});
