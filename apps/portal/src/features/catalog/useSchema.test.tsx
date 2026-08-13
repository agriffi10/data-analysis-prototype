import {beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {getDatabase, listTables} from './glue.service';
import {useAllSchemas, useSchema} from './useSchema';
import type {GlueTableSummary} from './catalog.types';
import * as glue from './glue.service';

vi.mock('./glue.service', async (importActual) => {
  const actual = await importActual<typeof glue>();
  return {...actual, getDatabase: vi.fn(), listTables: vi.fn()};
});

// ─── from useSchema.test.tsx ───
describe('useSchema', () => {
  // The hook (never exercised elsewhere — SchemaBrowser/DatabaseNode tests mock it
  // out) over its mocked Glue service boundary. Covers useSchema loading/disabled/
  // error and the useAllSchemas fan-out that drops databases that fail to load.

  const mockGetDatabase = vi.mocked(getDatabase);
  const mockListTables = vi.mocked(listTables);

  const table = (name: string): GlueTableSummary => ({name, columns: []});
  const okDb = (name: string) => ({success: true as const, data: {name}});
  const okTables = (tables: GlueTableSummary[]) => ({success: true as const, data: tables});

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useSchema', () => {
    it('is disabled and fetches nothing while the database name is null', () => {
      const {result} = renderHookWithProviders(() => useSchema(null));
      expect(result.current.fetchStatus).toBe('idle');
      expect(mockGetDatabase).not.toHaveBeenCalled();
    });

    it('loads a database and its tables', async () => {
      mockGetDatabase.mockResolvedValue(okDb('alice'));
      mockListTables.mockResolvedValue(okTables([table('orders'), table('sales')]));

      const {result} = renderHookWithProviders(() => useSchema('alice'));

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.data?.database.name).toBe('alice');
      expect(result.current.data?.tables.map((t) => t.name)).toEqual(['orders', 'sales']);
    });

    it('surfaces a database-load failure as an error state', async () => {
      mockGetDatabase.mockResolvedValue({success: false, error: {message: 'nope', code: 'NotFound'}});

      const {result} = renderHookWithProviders(() => useSchema('ghost'));

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.error).toEqual(expect.objectContaining({message: 'nope'}));
    });
  });

  describe('useAllSchemas', () => {
    it('returns a DatabaseSchema per successfully-loaded database and omits failures', async () => {
      mockGetDatabase.mockImplementation(async (name: string) =>
        name === 'broken' ? {success: false, error: {message: 'x'}} : okDb(name)
      );
      mockListTables.mockImplementation(async (name: string) => okTables([table(`${name}_t`)]));

      const {result} = renderHookWithProviders(() => useAllSchemas(['alice', 'broken', 'bob']));

      await waitFor(() => expect(result.current).toHaveLength(2));
      expect(result.current.map((s) => s.database)).toEqual(['alice', 'bob']);
      expect(result.current[0].tables.map((t) => t.name)).toEqual(['alice_t']);
    });

    it('yields an empty list when no database names are supplied', () => {
      const {result} = renderHookWithProviders(() => useAllSchemas([]));
      expect(result.current).toEqual([]);
      expect(mockGetDatabase).not.toHaveBeenCalled();
    });
  });
});
