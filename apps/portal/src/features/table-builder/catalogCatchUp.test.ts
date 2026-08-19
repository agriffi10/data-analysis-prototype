import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {armCatalogCatchUp, drainCatalogCatchUp, useCatalogCatchUp} from './useCatalogCatchUp';
import {invalidateSchema} from '../catalog/useSchema';

vi.mock('../catalog/useSchema', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/useSchema')>()),
  invalidateSchema: vi.fn().mockResolvedValue(undefined)
}));

beforeEach(() => {
  vi.clearAllMocks();
  // Anything a previous case armed and did not drain would leak into the next one — module
  // state is the point of this hook, and the price is that a test has to say so.
  drainCatalogCatchUp(() => {});
});

/**
 * A table build lands minutes after the enqueue and announces itself in a notification nothing
 * in the tab hears. Without this, dropping a table invalidated the catalog and rebuilding it
 * did not — so the Data Explorer went on resolving to the pre-drop execution. That is the
 * reported bug on the path this exists to close.
 */
describe('catching the catalog up after an async build', () => {
  it('re-reads on focus, naming the table the build was asked for', () => {
    const client = createTestQueryClient();
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});

    armCatalogCatchUp('alice', 'sales_2026');
    act(() => window.dispatchEvent(new Event('focus')));

    // The table IS named: the control plane refuses a name that is not catalog-safe and refuses
    // one that already exists, so it creates exactly this name or fails. Naming it is what
    // keeps the re-read from resetting every other exploration of the database — which for a
    // mounted one is a billed execution for rows a brand-new table cannot have changed.
    expect(invalidateSchema).toHaveBeenCalledWith(client, 'alice', 'sales_2026');
  });

  // THE REASON IT IS MODULE STATE. The build lands minutes later, so navigating away is the
  // ordinary case — and both controls that enqueue one unmount when the user leaves that route.
  // Held per component, the arm died with the control that set it.
  it('survives the unmount of whatever armed it', () => {
    const client = createTestQueryClient();
    const arming = renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});
    armCatalogCatchUp('alice', 'sales_2026');
    arming.unmount();

    // A different screen, a different mount of the shell — the arm is still owed.
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});
    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).toHaveBeenCalledWith(client, 'alice', 'sales_2026');
  });

  it('disarms by firing, so an idle focus re-reads nothing', () => {
    const client = createTestQueryClient();
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});

    armCatalogCatchUp('alice', 'sales_2026');
    act(() => window.dispatchEvent(new Event('focus')));
    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).toHaveBeenCalledTimes(1);
  });

  it('re-reads every build in flight, not just the last one', () => {
    const client = createTestQueryClient();
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});

    armCatalogCatchUp('alice', 'sales_2026');
    armCatalogCatchUp('teamspace', 'orders');
    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).toHaveBeenCalledWith(client, 'alice', 'sales_2026');
    expect(invalidateSchema).toHaveBeenCalledWith(client, 'teamspace', 'orders');
  });

  it('is idempotent, so a retried enqueue does not re-read twice', () => {
    const client = createTestQueryClient();
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});

    armCatalogCatchUp('alice', 'sales_2026');
    armCatalogCatchUp('alice', 'sales_2026');
    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).toHaveBeenCalledTimes(1);
  });

  it('does nothing at all when nothing is owed', () => {
    const client = createTestQueryClient();
    renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});

    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).not.toHaveBeenCalled();
  });

  it('stops listening when the shell unmounts', () => {
    const client = createTestQueryClient();
    const shell = renderHookWithProviders(() => useCatalogCatchUp(), {queryClient: client});
    shell.unmount();

    armCatalogCatchUp('alice', 'sales_2026');
    act(() => window.dispatchEvent(new Event('focus')));

    expect(invalidateSchema).not.toHaveBeenCalled();
  });
});
