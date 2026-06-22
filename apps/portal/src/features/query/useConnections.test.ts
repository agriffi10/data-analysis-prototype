import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useConnections } from './useConnections';

describe('useConnections (SPEC-047 FR-001)', () => {
  it('returns exactly one personal connection for a signed-in user', () => {
    const { result } = renderHook(() => useConnections('alice'));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.connections).toEqual([
      { id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal' },
    ]);
  });

  it('returns an empty list when there is no username', () => {
    const { result } = renderHook(() => useConnections(null));
    expect(result.current.connections).toEqual([]);
  });

  it('keeps a stable reference while the username is unchanged', () => {
    const { result, rerender } = renderHook(({ u }) => useConnections(u), {
      initialProps: { u: 'alice' as string | null },
    });
    const first = result.current.connections;
    rerender({ u: 'alice' });
    expect(result.current.connections).toBe(first);
  });
});
