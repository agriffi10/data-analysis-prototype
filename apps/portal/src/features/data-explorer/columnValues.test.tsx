import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {CACHE_HIT_TEXT} from './CostIndicator';
import {evictExplorations} from './useExplorationEviction';
import {readValuesPages} from './columnValuesStore';
import {getQueryResults, getQueryStatus} from '../catalog/athena.service';
import {ATHENA_QUERY_STRING_MAX, renderExplorationSql} from './renderExplorationSql';
import {emptyExplorationQuery} from './exploration';
import {formatBytes} from '../../lib/format';
import {
  billedListings,
  explorationStarts,
  gate,
  gateListingStart,
  installAthena,
  isListing,
  LISTING_BYTES,
  listingStarts,
  ok,
  seedTabs,
  storedTab,
  USERNAME,
  type AthenaStandIn
} from './columnValues.testkit';

// The values listing's lifecycle, driven through the real workspace with Athena mocked at the
// service: every assertion is about how many listing statements reached `StartQueryExecution`
// and which tab paid for them, because a listing is a bill.

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
  return renderWithProviders(<DataExplorerWorkspace />, {
    route: '/explore',
    auth: authenticated(USERNAME),
    strictMode: true
  });
}

type User = ReturnType<typeof render>['user'];

async function openListing(user: User, column = 'brnd_name'): Promise<HTMLElement> {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  await user.click(await screen.findByRole('menuitem', {name: 'Filter by value…'}));
  return screen.findByRole('dialog', {name: `Filter ${column} by value`});
}

async function cancel(user: User, dialog: HTMLElement): Promise<void> {
  await user.click(within(dialog).getByRole('button', {name: 'Cancel'}));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
}

const SOURCE = {kind: 'table', spaceId: 'personal', database: USERNAME, table: 'orders'} as const;

const scannedSentence = `This query scanned ${formatBytes(LISTING_BYTES)}`;

describe('a values listing is one billed execution per filter state', () => {
  it('starts one listing on open, bills it once, and a reopen scans nothing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const first = await openListing(user);
    expect(await within(first).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(within(first).getByText(new RegExp(scannedSentence))).toBeInTheDocument();
    await cancel(user, first);
    const second = await openListing(user);

    expect(await within(second).findByText(new RegExp(CACHE_HIT_TEXT))).toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
    expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]);
  });

  it('starts none when only the column’s own filter changed, and one when another column’s did', async () => {
    seedTabs([{id: 't1', filters: [{column: 'brnd_name', operator: 'in', values: ['x'], valueKind: 'string'}]}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));

    await cancel(user, await openListing(user, 'qty'));
    const again = await openListing(user);
    await within(again).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    const beforeOther = listingStarts().length;
    await cancel(user, again);
    await user.click(await screen.findByRole('button', {name: /^Column options: qty/}));
    await user.click(await screen.findByRole('menuitem', {name: 'Filter: is null'}));
    await openListing(user);

    await waitFor(() => expect(listingStarts()).toHaveLength(beforeOther + 1));
    // The brnd_name listings never carried brnd_name's own filter; the last one carries qty's.
    expect(listingStarts().filter((sql) => sql.startsWith('SELECT "brnd_name"'))).toHaveLength(2);
    expect(listingStarts().at(-1)).toContain('WHERE "qty" IS NULL');
  });

  it('leaves the tab’s filter history alone', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openListing(user);
    await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'});

    expect(storedTab('t1').history.past).toHaveLength(0);
  });
});

describe('a listing outlives the dialog that asked for it', () => {
  it('keeps watching after Cancel, and bills the tab when it settles', async () => {
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));

    await act(async () => athena.listingGate?.release());

    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
    const reopened = await openListing(user);
    await within(reopened).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    expect(listingStarts()).toHaveLength(1);
  });

  it('starts nothing on a reopen before it settles, and calls that first run a scan, not a cache hit', async () => {
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    const reopened = await openListing(user);
    expect(within(reopened).getByText('Counting the values…')).toBeInTheDocument();

    await act(async () => athena.listingGate?.release());

    expect(await within(reopened).findByText(new RegExp(scannedSentence))).toBeInTheDocument();
    expect(within(reopened).queryByText(new RegExp(CACHE_HIT_TEXT))).not.toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
  });

  it('reads no results while the listing is still running', async () => {
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const reads = vi.mocked(getQueryResults).mock.calls.length;

    await openListing(user);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));

    expect(vi.mocked(getQueryResults).mock.calls.length).toBe(reads);
    await act(async () => athena.listingGate?.release());
  });

  it('bills the tab that asked, even after a switch to another tab', async () => {
    seedTabs([{id: 't1'}, {id: 't2'}], 't1');
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    await user.click(screen.getByRole('tab', {name: /orders t2/}));

    await act(async () => athena.listingGate?.release());

    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
    expect(billedListings('t2')).toEqual({});
  });

  it('bills a second tab that asks for a listing another tab already settled', async () => {
    seedTabs([{id: 't1'}, {id: 't2'}], 't1');
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const first = await openListing(user);
    await within(first).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    await cancel(user, first);
    await user.click(screen.getByRole('tab', {name: /orders t2/}));
    await screen.findAllByRole('gridcell');

    const second = await openListing(user);

    expect(await within(second).findByText(new RegExp(scannedSentence))).toBeInTheDocument();
    await waitFor(() => expect(Object.values(billedListings('t2'))).toEqual([LISTING_BYTES]));
    expect(listingStarts()).toHaveLength(1);
  });

  it('shows only the listing it asked for when an earlier one settles late', async () => {
    athena.listingGate = gate();
    athena.listingRows = (sql) => (sql.includes('WHERE') ? [['Zyrtec', '5', '1']] : [['Abilify', '40', '1']]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    await user.click(await screen.findByRole('button', {name: /^Column options: qty/}));
    await user.click(await screen.findByRole('menuitem', {name: 'Filter: is null'}));
    const dialog = await openListing(user);

    await act(async () => athena.listingGate?.release());

    expect(await within(dialog).findByRole('checkbox', {name: 'Zyrtec, 5 rows'})).toBeInTheDocument();
    expect(within(dialog).queryByRole('checkbox', {name: /^Abilify/})).not.toBeInTheDocument();
    await waitFor(() => expect(Object.keys(billedListings('t1'))).toHaveLength(2));
  });
});

describe('a listing that failed starts again only when asked', () => {
  it('stays failed while the dialog is open, and Try again starts exactly one', async () => {
    athena.listingState = 'FAILED';
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);
    const retry = await within(dialog).findByRole('button', {name: 'Try again'});
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(listingStarts()).toHaveLength(1);

    await user.click(retry);

    await waitFor(() => expect(listingStarts()).toHaveLength(2));
  });

  it('starts one when the dialog is closed and opened again', async () => {
    athena.listingState = 'FAILED';
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);
    await within(dialog).findByRole('button', {name: 'Try again'});

    await cancel(user, dialog);
    await openListing(user);

    await waitFor(() => expect(listingStarts()).toHaveLength(2));
  });

  it('reads a succeeded listing again rather than running it again', async () => {
    athena.failedListingReads = 1;
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);

    await user.click(await within(dialog).findByRole('button', {name: 'Try again'}));

    expect(await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
  });

  it('starts nothing for a statement too long to run, and says so', async () => {
    // Sized so the exploration fits exactly and only the listing, whose projection is longer,
    // is over Athena's limit: an exploration over it would leave no grid to open the menu from.
    const filterOn = (value: string) => [{column: 'ship_date', operator: '=' as const, value}];
    const overhead = renderExplorationSql(SOURCE, {...emptyExplorationQuery(), filters: filterOn('')}).length;
    seedTabs([{id: 't1', filters: filterOn('x'.repeat(ATHENA_QUERY_STRING_MAX - overhead))}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openListing(user);

    expect(await within(dialog).findByText(/too long/i)).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', {name: 'Try again'})).not.toBeInTheDocument();
    expect(listingStarts()).toHaveLength(0);
  });
});

describe('a catalog change never starts a listing', () => {
  it('bills a listing it caught mid-run once, and the next open starts one', async () => {
    athena.listingGate = gate();
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));

    act(() => evictExplorations(queryClient, USERNAME, 'orders'));
    await act(async () => athena.listingGate?.release());

    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
    expect(listingStarts()).toHaveLength(1);
    await openListing(user);
    await waitFor(() => expect(listingStarts()).toHaveLength(2));
  });

  it('leaves an open listing on screen, and the next open starts one', async () => {
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);
    await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'});

    act(() => evictExplorations(queryClient, USERNAME, 'orders'));

    expect(within(dialog).getByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
    await cancel(user, dialog);
    await openListing(user);
    await waitFor(() => expect(listingStarts()).toHaveLength(2));
  });
});

describe('a start in flight answers everyone who asked', () => {
  it('bills a start an eviction caught in flight once, and the next open starts one', async () => {
    const start = gateListingStart();
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);

    act(() => evictExplorations(queryClient, USERNAME, 'orders'));
    await act(async () => start.release());

    expect(await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
    await cancel(user, dialog);
    await openListing(user);
    await waitFor(() => expect(listingStarts()).toHaveLength(2));
  });

  it('offers Try again when a start an eviction caught in flight then fails', async () => {
    const start = gateListingStart(true);
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);

    act(() => evictExplorations(queryClient, USERNAME, 'orders'));
    await act(async () => start.release());

    expect(await within(dialog).findByRole('button', {name: 'Try again'})).toBeInTheDocument();
    expect(within(dialog).queryByText('Counting the values…')).not.toBeInTheDocument();
  });

  it.each([
    ['with nothing else happening', false],
    ['when an eviction caught the start in flight', true]
  ])('bills a second tab that joined a start %s', async (_case, evict) => {
    seedTabs([{id: 't1'}, {id: 't2'}], 't1');
    const start = gateListingStart();
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    await user.click(screen.getByRole('tab', {name: /orders t2/}));
    await screen.findAllByRole('gridcell');
    const second = await openListing(user);

    if (evict) act(() => evictExplorations(queryClient, USERNAME, 'orders'));
    await act(async () => start.release());

    expect(await within(second).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    await waitFor(() => expect(Object.values(billedListings('t2'))).toEqual([LISTING_BYTES]));
    expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]);
    expect(listingStarts()).toHaveLength(1);
  });

  it('bills each of two tabs that asked while it ran, and a reopen is then a cache hit', async () => {
    seedTabs([{id: 't1'}, {id: 't2'}], 't1');
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    await user.click(screen.getByRole('tab', {name: /orders t2/}));
    await screen.findAllByRole('gridcell');
    const second = await openListing(user);

    await act(async () => athena.listingGate?.release());

    expect(await within(second).findByText(new RegExp(scannedSentence))).toBeInTheDocument();
    await waitFor(() => expect(Object.values(billedListings('t2'))).toEqual([LISTING_BYTES]));
    expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]);
    await cancel(user, second);
    expect(await within(await openListing(user)).findByText(new RegExp(CACHE_HIT_TEXT))).toBeInTheDocument();
  });

  it('keeps watching when New exploration takes the tab panel away', async () => {
    athena.listingGate = gate();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    await user.click(screen.getByRole('button', {name: 'New exploration'}));

    await act(async () => athena.listingGate?.release());

    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
  });

  it('does not let an older failed run drop the newer run cached in its place', async () => {
    const gates = new Map<string, ReturnType<typeof gate>>();
    const gateOf = (id: string) => gates.get(id) ?? gates.set(id, gate()).get(id)!;
    const failed = new Set<string>();
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) => {
      const listing = isListing(athena.sqlOf.get(queryExecutionId) ?? '');
      if (listing) await gateOf(queryExecutionId).promise;
      return ok({
        queryExecutionId,
        state: failed.has(queryExecutionId) ? 'FAILED' : 'SUCCEEDED',
        dataScannedBytes: listing ? LISTING_BYTES : 2048,
        engineExecutionTimeMillis: 1
      });
    }) as never);
    const {user, queryClient} = render();
    await screen.findAllByRole('gridcell');
    await cancel(user, await openListing(user));
    act(() => evictExplorations(queryClient, USERNAME, 'orders'));
    // The eviction re-runs the exploration on screen; its grid redraws before the menu is usable.
    await waitFor(() => expect(explorationStarts()).toHaveLength(2));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)));
    const second = await openListing(user);
    await waitFor(() => expect(listingStarts()).toHaveLength(2));
    const [older, newer] = [...athena.sqlOf].filter(([, sql]) => isListing(sql)).map(([id]) => id);

    failed.add(older);
    await act(async () => gateOf(older).release());
    await act(async () => gateOf(newer).release());

    await within(second).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    await cancel(user, second);
    await within(await openListing(user)).findByRole('checkbox', {name: 'Abilify, 40 rows'});
    expect(listingStarts()).toHaveLength(2);
  });
});

describe('readValuesPages', () => {
  const page = (rows: (string | null)[][], nextToken?: string) =>
    ok({columns: [], rows, ...(nextToken ? {nextToken} : {})}) as never;
  const rows = (count: number, valueCount: number) =>
    Array.from({length: count}, (_, i) => [`v${i}`, '1', String(valueCount)]);

  it('follows a nextToken to the cap', async () => {
    vi.mocked(getQueryResults)
      .mockResolvedValueOnce(page(rows(999, 1000), 't'))
      .mockResolvedValueOnce(page(rows(1, 1000)));

    const read = await readValuesPages('exec-1');

    expect(read.success && read.data.entries).toHaveLength(1000);
    expect(read.success && read.data.valueCount).toBe(1000);
  });

  it('reads one page when there is no nextToken', async () => {
    vi.mocked(getQueryResults).mockResolvedValueOnce(page(rows(3, 3)));

    await readValuesPages('exec-1');

    expect(getQueryResults).toHaveBeenCalledTimes(1);
  });

  it('fails whole when a page fails, never returning part of the list', async () => {
    vi.mocked(getQueryResults)
      .mockResolvedValueOnce(page(rows(999, 1500), 't'))
      .mockResolvedValueOnce({success: false, error: {message: 'x', code: 'ServiceUnavailable'}} as never);

    const read = await readValuesPages('exec-1');

    expect(read.success).toBe(false);
  });
});
