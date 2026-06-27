import {useEffect} from 'react';

// Calls `onEscape` when the Escape key is pressed, while `enabled` (default true).
// Consolidates the keydown-listener Effect that was duplicated across every modal
// and drawer. Pass `enabled={!busy}` to ignore Escape during an in-flight action.
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
