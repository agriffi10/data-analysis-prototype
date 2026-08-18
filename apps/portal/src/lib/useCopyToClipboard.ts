import {useCallback, useEffect, useRef, useState} from 'react';

export type UseCopyToClipboardResult = {
  /** Transient flag for "copied!" UI feedback; auto-resets. */
  copied: boolean;
  /** Resolves TRUE when the text reached the clipboard, false when the write was refused. */
  copy: (text: string) => Promise<boolean>;
};

/**
 * Copies text to the clipboard and flags a transient `copied` state.
 *
 * Never throws — Clipboard API rejections (insecure context, denied
 * permission) are swallowed and the copy simply doesn't confirm. The flag
 * auto-resets after `resetMs`; the timer is cleared on unmount.
 *
 * It RETURNS the outcome as well, because swallowing is only safe for a caller whose
 * confirmation is the `copied` flag itself: a caller that closes its dialog and announces
 * success separately would otherwise say the copy worked when the write was refused
 *. Callers that render the flag can go on ignoring the return.
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
        return true;
      } catch {
        // Clipboard unavailable (insecure context / denied permission). Non-fatal.
        setCopied(false);
        return false;
      }
    },
    [resetMs]
  );

  return {copied, copy};
}
