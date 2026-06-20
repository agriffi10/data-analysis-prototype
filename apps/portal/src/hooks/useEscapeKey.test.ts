import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';
import { useEscapeKey } from './useEscapeKey';

describe('useEscapeKey', () => {
  it('calls the handler on Escape while enabled', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it('ignores other keys', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape));
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onEscape).not.toHaveBeenCalled();
  });

  it('does nothing when disabled', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape, false));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onEscape).not.toHaveBeenCalled();
  });

  it('removes the listener on unmount', () => {
    const onEscape = vi.fn();
    const { unmount } = renderHook(() => useEscapeKey(onEscape));
    unmount();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onEscape).not.toHaveBeenCalled();
  });
});
