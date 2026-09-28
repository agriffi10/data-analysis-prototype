import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {
  billedListings,
  installAthena,
  LISTING_BYTES,
  listingStarts,
  seedTabs,
  USERNAME,
  type AthenaStandIn
} from './columnValues.testkit';

// A listing whose watch reaches its ceiling while Athena still says RUNNING. The ceiling is thirty
// minutes in the app, so it is shortened here — its own file, because the constant is mocked for
// every test in it — and the listing is held RUNNING until the test lets it finish.

vi.mock('../catalog/catalog.constants', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/catalog.constants')>()),
  POLL_INTERVAL_MS: 10,
  MAX_POLL_DURATION_MS: 80
}));
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
  athena.listingState = 'RUNNING';
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

async function openListing(user: User): Promise<HTMLElement> {
  await user.click(await screen.findByRole('button', {name: /^Column options: brnd_name/}));
  await user.click(await screen.findByRole('menuitem', {name: 'Filter by value…'}));
  return screen.findByRole('dialog', {name: 'Filter brnd_name by value'});
}

describe('a listing still running when its watch gave up', () => {
  it('watches again on Try again, starting nothing, and bills it once when it lands', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);
    const tryAgain = await within(dialog).findByRole('button', {name: 'Try again'}, {timeout: 3000});
    athena.listingState = 'SUCCEEDED';

    await user.click(tryAgain);

    expect(await within(dialog).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
  });

  it('watches again when the dialog is opened again, starting nothing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openListing(user);
    await within(dialog).findByRole('button', {name: 'Try again'}, {timeout: 3000});
    await user.click(within(dialog).getByRole('button', {name: 'Cancel'}));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    athena.listingState = 'SUCCEEDED';

    const again = await openListing(user);

    expect(await within(again).findByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(listingStarts()).toHaveLength(1);
    await waitFor(() => expect(Object.values(billedListings('t1'))).toEqual([LISTING_BYTES]));
  });
});
