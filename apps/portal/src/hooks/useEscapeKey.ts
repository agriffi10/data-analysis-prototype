import {useEffect} from 'react';

/**
 * Calls `onEscape` when the Escape key is pressed, while `enabled` (default
 * true). Pass `enabled={!busy}` to ignore Escape during an in-flight action,
 * or gate it off while a nested dialog owns Escape.
 *
 * @example
 * useEscapeKey(onClose, open && !busy);
 */
export function useEscapeKey(onEscape: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onEscape();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onEscape, enabled]);
}
