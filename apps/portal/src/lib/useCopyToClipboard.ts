import {useCallback, useEffect, useRef, useState} from 'react';

export type UseCopyToClipboardResult = {
  /** Transient flag for "copied!" UI feedback; auto-resets. */
  copied: boolean;
  copy: (text: string) => Promise<void>;
};

/**
 * Copies text to the clipboard and flags a transient `copied` state.
 *
 * Never throws — Clipboard API rejections (insecure context, denied
 * permission) are swallowed and the copy simply doesn't confirm. The flag
 * auto-resets after `resetMs`; the timer is cleared on unmount.
 */
export function useCopyToClipboard(resetMs = 1500): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), resetMs);
      } catch {
        // Clipboard unavailable (insecure context / denied permission). Non-fatal.
        setCopied(false);
      }
    },
    [resetMs]
  );

  return {copied, copy};
}
