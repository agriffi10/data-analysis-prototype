import { describe, it, expect, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { invalidateListing } from './queryClient';
import { fileBrowserKeys } from '../features/file-browser/fileBrowserKeys';

describe('invalidateListing', () => {
  it('invalidates exactly the listing key for the given bucket + prefix', async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();

    await invalidateListing(client, 'my-bucket', 'alice/');

    expect(spy).toHaveBeenCalledWith({
      queryKey: fileBrowserKeys.list('my-bucket', 'alice/'),
    });
  });

  it('produces a key that matches the factory (single source of truth)', () => {
    expect(fileBrowserKeys.list('b', 'p/')).toEqual([
      'file-browser',
      'list',
      'b',
      'p/',
    ]);
  });
});
