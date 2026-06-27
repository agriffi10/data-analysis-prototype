import { describe, it, expect, vi, beforeEach, type MockedFunction } from 'vitest';

vi.mock('../../lib/glueClient', () => ({ getGlueClient: vi.fn() }));

import { getGlueClient } from '../../lib/glueClient';
import { getDatabase, listTables } from './glue.service';

const mockGetClient = getGlueClient as unknown as MockedFunction<() => Promise<unknown>>;

type Sent = { input: Record<string, unknown> };
function clientWithSend(send: (cmd: Sent) => Promise<unknown>) {
  mockGetClient.mockResolvedValue({ success: true, data: { send } });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getDatabase', () => {
  it('returns the database name when it exists', async () => {
    clientWithSend(vi.fn(async () => ({ Database: { Name: 'alice' } })));

    const result = await getDatabase('alice');

    expect(result).toEqual({ success: true, data: { name: 'alice' } });
  });

  it('maps EntityNotFoundException to a clean NotFound error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('missing'), {
          name: 'EntityNotFoundException',
        });
      })
    );

    const result = await getDatabase('alice');

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('NotFound');
  });
});

describe('listTables', () => {
  it('normalizes tables + columns and paginates past the page cap', async () => {
    const send = vi
      .fn<(cmd: Sent) => Promise<unknown>>()
      .mockResolvedValueOnce({
        TableList: [
          {
            Name: 'events',
            TableType: 'EXTERNAL_TABLE',
            StorageDescriptor: {
              Location: 's3://user-bucket/alice/events/',
              Columns: [
                { Name: 'id', Type: 'bigint' },
                { Name: 'ts', Type: 'timestamp' },
              ],
            },
          },
        ],
        NextToken: 'page2',
      })
      .mockResolvedValueOnce({
        TableList: [{ Name: 'lookup', StorageDescriptor: { Columns: [] } }],
      });
    clientWithSend(send);

    const result = await listTables('alice');

    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].input).toMatchObject({ NextToken: 'page2' });
    expect(result).toEqual({
      success: true,
      data: [
        {
          name: 'events',
          tableType: 'EXTERNAL_TABLE',
          location: 's3://user-bucket/alice/events/',
          columns: [
            { name: 'id', type: 'bigint' },
            { name: 'ts', type: 'timestamp' },
          ],
        },
        { name: 'lookup', tableType: undefined, location: undefined, columns: [] },
      ],
    });
  });

  it('treats a not-yet-created database as an empty schema (not an error)', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('no db'), {
          name: 'EntityNotFoundException',
        });
      })
    );

    const result = await listTables('alice');

    expect(result).toEqual({ success: true, data: [] });
  });

  it('maps AccessDenied to a clean error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('denied'), {
          name: 'AccessDeniedException',
        });
      })
    );

    const result = await listTables('bob');

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDeniedException');
  });
});
