import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {explorationOption, chooseExplorationOption} from './explorationOptions.testkit';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {
  FILTER_BY_VALUE_TYPES_REFUSAL,
  HELD_FILTER_BY_VALUE_REFUSAL,
  NO_CELL_TO_FILTER
} from './ExplorationResultsRegion';
import {CHOOSE_AT_MOST, TICK_AT_LEAST_ONE} from './FilterByValueDialog';
import {ALSO_SELECTED} from './columnValues';
import {
  COLUMNS,
  explorationStarts,
  gate,
  installAthena,
  lastExploration,
  listingStarts,
  seedTabs,
  storedTab,
  USERNAME,
  type AthenaStandIn
} from './columnValues.testkit';

// Filter by value from both of its entry points, and what its Apply writes. Every assertion is
// about the statement that reaches Athena, since the dialog's whole job is to write one filter.

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

let athena: AthenaStandIn;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  athena = installAthena();
  seedTabs([{id: 't1'}]);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

function render() {
  return renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated(USERNAME)});
}

type User = ReturnType<typeof render>['user'];

async function menuLabels(user: User, column: string): Promise<string[]> {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  const labels = (await screen.findAllByRole('menuitem')).map((item) => item.textContent ?? '');
  await user.keyboard('{Escape}');
  return labels;
}

async function openFromHeader(user: User, column = 'brnd_name'): Promise<HTMLElement> {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  await user.click(await screen.findByRole('menuitem', {name: 'Filter by value…'}));
  return screen.findByRole('dialog', {name: `Filter ${column} by value`});
}

async function apply(user: User, dialog: HTMLElement): Promise<void> {
  const before = explorationStarts().length;
  await user.click(within(dialog).getByRole('button', {name: 'Apply filter'}));
  await waitFor(() => expect(explorationStarts().length).toBe(before + 1));
}

describe('where Filter by value is offered', () => {
  it.each([
    ['a text column', 'brnd_name', true],
    ['a number column', 'qty', true],
    ['a date column', 'ship_date', false],
    ['a true/false column', 'active', false]
  ])('%s’s header menu %#', async (_case, column, offered) => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const labels = await menuLabels(user, column);

    if (offered) expect(labels[labels.indexOf('Clear sort') + 1]).toBe('Filter by value…');
    else expect(labels).not.toContain('Filter by value…');
  });

  it('is offered on a grouping column and not on the aggregate beside it', async () => {
    seedTabs([
      {
        id: 't1',
        grouping: {
          columns: ['brnd_name'],
          aggregates: [{fn: 'COUNT', column: '*'}],
          duplicatesOnly: false,
          showPercentage: false
        }
      }
    ]);
    athena.explorationResult = () => ({
      columns: [
        {name: 'brnd_name', type: 'varchar'},
        {name: 'count_all', type: 'bigint'}
      ],
      rows: [['Abilify', '40']]
    });
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const grouped = await menuLabels(user, 'brnd_name');
    const aggregate = await menuLabels(user, 'count_all');

    expect(grouped).toContain('Filter by value…');
    expect(aggregate).not.toContain('Filter by value…');
  });

  it('opens from the header menu as a dialog named for its column, starting one listing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openFromHeader(user);

    expect(dialog).toBeInTheDocument();
    await waitFor(() => expect(listingStarts()).toHaveLength(1));
  });

  it('replaces Filter by this value in Options, starting from the cell the cursor is on', async () => {
    const {user} = render();
    await user.click((await screen.findAllByRole('gridcell'))[0]); // brnd_name — Abilify

    await chooseExplorationOption(user, 'Filter by value…');

    const dialog = await screen.findByRole('dialog', {name: 'Filter brnd_name by value'});
    expect(within(dialog).getByRole('radio', {name: 'is one of'})).toBeChecked();
    expect(await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeChecked();
    expect(screen.queryByRole('menuitem', {name: 'Filter by this value'})).not.toBeInTheDocument();
  });

  it.each<[string, string, () => void, number | null]>([
    [
      'with no cell to start from',
      NO_CELL_TO_FILTER,
      () => (athena.explorationResult = () => ({columns: COLUMNS, rows: []})),
      null
    ],
    ['on a date cell', FILTER_BY_VALUE_TYPES_REFUSAL, () => {}, 2],
    [
      'in a tab held until its view is run',
      HELD_FILTER_BY_VALUE_REFUSAL,
      () => seedTabs([{id: 't1', awaitingRun: {space: 'team', leftOut: {links: 0, patterns: 0}}}]),
      null
    ]
  ])('is refused %s, and lists nothing', async (_case, refusal, arrange, cell) => {
    arrange();
    const {user} = render();
    if (cell !== null) await user.click((await screen.findAllByRole('gridcell'))[cell]);
    const item = await explorationOption(user, 'Filter by value…');

    await user.click(item);

    await waitFor(() => expect(item).toHaveAttribute('title', refusal));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(listingStarts()).toHaveLength(0);
  });

  it('opens unrefused on a number cell the list cannot tick, with nothing ticked', async () => {
    athena.explorationResult = () => ({columns: [{name: 'price', type: 'double'}], rows: [['NaN']]});
    athena.listingRows = () => [['NaN', '1', '1']];
    const {user} = render();
    await user.click((await screen.findAllByRole('gridcell'))[0]);

    await chooseExplorationOption(user, 'Filter by value…');

    const dialog = await screen.findByRole('dialog', {name: 'Filter price by value'});
    expect(await within(dialog).findByRole('checkbox', {name: 'NaN, 1 row'})).not.toBeChecked();
    expect(within(dialog).queryByRole('group', {name: ALSO_SELECTED})).not.toBeInTheDocument();
  });
});

describe('what Apply writes', () => {
  it.each([
    [
      'is one of, with NULL',
      'is one of',
      ['Abilify, 40 rows', 'NULL, 2 rows'],
      `WHERE ("brnd_name" IN ('Abilify') OR "brnd_name" IS NULL)`
    ],
    [
      'is not one of, with (empty)',
      'is not one of',
      ['Abilify, 40 rows', '(empty), 3 rows'],
      `WHERE "brnd_name" NOT IN ('', 'Abilify')`
    ],
    ['only NULL, as a list', 'is one of', ['NULL, 2 rows'], 'WHERE "brnd_name" IS NULL']
  ])('%s', async (_case, match, ticks, where) => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await user.click(within(dialog).getByRole('radio', {name: match}));
    for (const name of ticks) await user.click(await within(dialog).findByRole('checkbox', {name}));

    await apply(user, dialog);

    expect(lastExploration()).toContain(where);
  });

  it('stores only NULL as an is one of list rather than switching operator', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await user.click(await within(dialog).findByRole('checkbox', {name: 'NULL, 2 rows'}));

    await apply(user, dialog);

    await waitFor(() =>
      expect(storedTab('t1').exploration.query.filters).toEqual([
        {column: 'brnd_name', operator: 'in', values: [], includesNull: true, valueKind: 'string'}
      ])
    );
  });

  it('emits a number column’s ticked value bare', async () => {
    athena.listingRows = () => [
      ['10', '4', '2'],
      ['20', '1', '2']
    ];
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user, 'qty');
    await user.click(await within(dialog).findByRole('checkbox', {name: '10, 4 rows'}));

    await apply(user, dialog);

    expect(lastExploration()).toContain('WHERE "qty" IN (10)');
  });

  it('reopens an is not one of filter as itself', async () => {
    seedTabs([{id: 't1', filters: [{column: 'brnd_name', operator: 'notIn', values: ['x'], valueKind: 'string'}]}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openFromHeader(user);

    expect(within(dialog).getByRole('radio', {name: 'is not one of'})).toBeChecked();
    expect(
      within(within(dialog).getByRole('group', {name: ALSO_SELECTED})).getByRole('checkbox', {name: 'x'})
    ).toBeChecked();
  });

  it('clears the filter when every value of a whole list is kept', async () => {
    seedTabs([{id: 't1', filters: [{column: 'brnd_name', operator: 'in', values: ['Abilify'], valueKind: 'string'}]}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    await user.click(within(dialog).getByRole('button', {name: 'Select all shown'}));

    await apply(user, dialog);

    expect(lastExploration()).not.toContain('WHERE');
  });

  it('writes all 1,000 values of a list cut short, rather than clearing', async () => {
    athena.listingRows = () => Array.from({length: 1000}, (_, i) => [`v${i}`, '1', '1500']);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await within(dialog).findByRole('checkbox', {name: 'v0, 1 row'});
    await user.click(within(dialog).getByRole('button', {name: 'Select all shown'}));

    await apply(user, dialog);

    expect(lastExploration().match(/'v\d+'/g)).toHaveLength(1000);
  });

  it('applies the cell it was opened on before the list has landed', async () => {
    athena.listingGate = gate();
    const {user} = render();
    await user.click((await screen.findAllByRole('gridcell'))[0]);
    await chooseExplorationOption(user, 'Filter by value…');
    const dialog = await screen.findByRole('dialog', {name: 'Filter brnd_name by value'});

    await apply(user, dialog);

    expect(lastExploration()).toContain(`WHERE "brnd_name" IN ('Abilify')`);
    await act(async () => athena.listingGate?.release());
  });
});

describe('what Apply refuses', () => {
  it.each([
    ['nothing ticked', 'is one of'],
    ['only the NULL that is not one of always leaves out', 'is not one of']
  ])('refuses %s, and starts nothing', async (_case, match) => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    await user.click(within(dialog).getByRole('radio', {name: match}));
    const before = explorationStarts().length;

    await user.click(within(dialog).getByRole('button', {name: 'Apply filter'}));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(TICK_AT_LEAST_ONE);
    expect(explorationStarts()).toHaveLength(before);
  });

  it('refuses more than 1,000 values, and starts nothing', async () => {
    seedTabs([{id: 't1', filters: [{column: 'brnd_name', operator: 'in', values: ['zzz'], valueKind: 'string'}]}]);
    athena.listingRows = () => Array.from({length: 1000}, (_, i) => [`v${i}`, '1', '1500']);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openFromHeader(user);
    await within(dialog).findByRole('checkbox', {name: 'v0, 1 row'});
    await user.click(within(dialog).getByRole('button', {name: 'Select all shown'}));
    const before = explorationStarts().length;

    await user.click(within(dialog).getByRole('button', {name: 'Apply filter'}));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(CHOOSE_AT_MOST);
    expect(explorationStarts()).toHaveLength(before);
  });
});
