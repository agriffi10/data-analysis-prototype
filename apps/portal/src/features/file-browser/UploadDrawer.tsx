import { useEffect, type ReactNode } from 'react';
import { IconButton } from '../../components/IconButton';

type Props = {
  open: boolean;
  onClose: () => void;
  destinationLabel?: string; // current folder the upload targets
  children: ReactNode;
};

// Right slide-over drawer hosting the upload flow (dropzone + collision +
// errors). Replaces the always-visible dropzone with the design-system upload
// drawer pattern: a 420px surface panel over a translucent scrim, dismissed via
// the close button, scrim click, or Escape. Non-animated (consistent with the
// metadata panel — slide animation is deferred until an animation lib lands).
export function UploadDrawer({ open, onClose, destinationLabel, children }: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Upload files"
        className="flex h-full w-full max-w-[420px] flex-col bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-border px-5">
          <h2 className="text-md font-semibold text-text">Upload</h2>
          {destinationLabel && (
            <span className="min-w-0 truncate text-sm text-text-3">
              to {destinationLabel}
            </span>
          )}
          <div className="flex-1" />
          <IconButton label="Close upload panel" onClick={onClose}>
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
            </svg>
          </IconButton>
        </div>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
          {children}
        </div>
      </aside>
    </div>
  );
}
