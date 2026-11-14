import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {useLocation} from '../../lib/navigation';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {getDatabase, listTables} from '../catalog/glue.service';
import {useRefreshLink} from './useRefreshLink';
import type {Connection} from '../connections/connection.types';

vi.mock('../catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));

const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
// Present in the rail but not usable: the case the guard exists for, since an absent database
// would fail the comparison on its own.
const deleting: Connection = {id: 'bob', label: 'bob', database: 'bob', kind: 'shared', status: 'deleting'};
const sales = {name: 'sales_2026', location: 's3://b/alice/sales/', columns: [{name: 'region', type: 'string'}]};

function render(route: string, connections: Connection[] = [personal]) {
  return renderHookWithProviders(() => ({link: useRefreshLink(connections, false), location: useLocation()}), {
    route
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getDatabase).mockImplementation(async (name: string) => ({success: true, data: {name}}));
  vi.mocked(listTables).mockResolvedValue({success: true, data: [sales]});
});

describe('useRefreshLink', () => {
  it('resolves a link to the rail’s table, carrying the removed columns it names', async () => {
    const {result} = render('/query?refreshTable=alice.sales_2026&removed=region');

    await waitFor(() => expect(result.current.link.target).not.toBeNull());

    expect(result.current.link.target?.table.name).toBe('sales_2026');
    expect(result.current.link.target?.pending?.columns).toEqual(['region']);
  });

  it('resolves to nothing, and reads no schema, for a database that is listed but not usable', async () => {
    const {result} = render('/query?refreshTable=bob.sales_2026&removed=region', [personal, deleting]);

    // Settle whatever the hook is going to do; the assertion is that it did nothing.
    await act(async () => {});

    expect(result.current.link.target).toBeNull();
    expect(getDatabase).not.toHaveBeenCalled();
    expect(listTables).not.toHaveBeenCalled();
  });

  it('clear() retires the two parameters from the URL and leaves the rest', async () => {
    const {result} = render('/query?refreshTable=alice.sales_2026&removed=region&space=personal');
    await waitFor(() => expect(result.current.link.target).not.toBeNull());

    act(() => result.current.link.clear());

    expect(result.current.location.search).toBe('?space=personal');
    expect(result.current.link.target).toBeNull();
  });
});
