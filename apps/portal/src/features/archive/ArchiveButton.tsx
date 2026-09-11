import {Button} from '../../components/Button';
import {TOOLBAR_ACTION_ICON, TOOLBAR_ACTION_LABEL} from '../../components/toolbarAction';

/** A box being closed and put away — stored, not thrown out. Deliberately not the trash glyph. */
function ArchiveIcon({className = 'h-[15px] w-[15px]'}: {className?: string}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <rect
        x="3"
        y="4"
        width="18"
        height="4"
        rx="1"
      />
      <path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8" />
      <path d="M10 12h4" />
    </svg>
  );
}

type Props = {
  onClick: () => void;
  /**
   * Unavailable, and why. A protected root cannot be archived (the plane refuses it as
   * `reserved_folder`), and saying so where the control is beats letting the user find out from
   * a notification. Rendered through `Button`'s `disabledReason`, so the control stays focusable.
   */
  disabledReason?: string;
  /** In flight, or another operation is running. A busy control is not a refusal. */
  disabled?: boolean;
  /**
   * `toolbar` — icon-only on mobile, the label alone at tablet and both at desktop, like
   * Copy / Move / Delete beside it.
   * `panel` — full width and always labelled, like the details panels' Rename.
   */
  placement?: 'toolbar' | 'panel';
  /** The accessible name. Every gated-surface row and journey test queries by it. */
  label: string;
};

/**
 * The Archive entry point, in the two homes a per-item action has in this file browser: the
 * selection toolbar and the two details panels.
 *
 * There is no context menu — rows carry a Details button and nothing else — so a single item
 * that has not been selected is reachable only through its panel, and a selection only through
 * the toolbar. Both are needed, and one component renders both rather than two drifting copies.
 *
 * It owns no state and knows nothing about what is selected: the caller decides what "archive"
 * means in its context, which is the whole selection on the toolbar and one item in a panel.
 */
export function ArchiveButton({onClick, disabledReason, disabled = false, placement = 'toolbar', label}: Props) {
  if (placement === 'panel') {
    return (
      <Button
        variant="default"
        className="!h-11 w-full gap-2 tablet:!h-[38px]"
        onClick={onClick}
        disabled={disabled}
        disabledReason={disabledReason}
        aria-label={label}>
        <ArchiveIcon />
        Archive
      </Button>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
      onClick={onClick}
      disabled={disabled}
      disabledReason={disabledReason}
      aria-label={label}>
      <ArchiveIcon className={TOOLBAR_ACTION_ICON} />
      <span className={TOOLBAR_ACTION_LABEL}>Archive</span>
    </Button>
  );
}
