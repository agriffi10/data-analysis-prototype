import {cx} from '../lib/cx';
import {useCopyToClipboard} from '../lib/useCopyToClipboard';
import {CopyIcon, CheckIcon} from './icons';

type Props = {
  // The exact text written to the clipboard.
  value: string;
  // What the value is, woven into the accessible label, e.g. "path" → "Copy path".
  label: string;
  className?: string;
};

// Icon-only copy-to-clipboard button. Swaps to a check on success and announces
// the result through a polite live region (the icon itself is decorative). The
// static aria-label keeps the control's name stable for assistive tech.
export function CopyButton({value, label, className}: Props) {
  const {copied, copy} = useCopyToClipboard();

  return (
    <button
      type="button"
      onClick={() => void copy(value)}
      aria-label={`Copy ${label}`}
      title={`Copy ${label}`}
      className={cx(
        'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        className
      )}>
      {copied ? <CheckIcon className="h-4 w-4 text-success" /> : <CopyIcon className="h-4 w-4" />}
      <span
        role="status"
        className="sr-only">
        {copied ? `${label} copied` : ''}
      </span>
    </button>
  );
}
