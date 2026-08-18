import type {ReactNode} from 'react';
import {cx} from '../lib/cx';

export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';

const TONES: Record<StatusTone, string> = {
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  neutral: 'border border-border bg-surface-2 text-text-2'
};

/** The dot, in one place. Named so the copy guard can point at it. */
const DOT = 'h-[7px] w-[7px] flex-none rounded-full bg-current';

type StatusPillProps = {
  tone: StatusTone;
  /**
   * The leading dot. On by default — every site that used this shape had one, and it is the
   * redundant signal that keeps the pill from being colour-only.
   */
  dot?: boolean;
  /** Pulses the dot for a state that is still moving (uploading, provisioning, leaving). */
  pulse?: boolean;
  /** A caller-specific concern the pill has no opinion on, e.g. `capitalize`. */
  className?: string;
  children: ReactNode;
};

/**
 * A status as a tinted pill with a dot and a TEXT LABEL.
 *
 * THE LABEL ALWAYS CARRIES THE MEANING. The tone and the dot are redundant signals, so a user
 * who cannot distinguish the tones loses nothing (WCAG 1.4.1) — that rule was written out
 * separately at all seven sites that hand-rolled this shape, and is now enforced by the
 * component having no colour-only mode.
 *
 * The dot is `bg-current`, so it always agrees with the label beside it. `QueryHistoryRow`'s
 * neutral rows previously dimmed their dot to `text-text-3` against `text-text-2` text, and
 * `UploadList`'s neutral pills carried no border; both now match the rest. Those are the two
 * deliberate visual changes in this consolidation.
 *
 * @example
 * <StatusPill tone="warning" pulse>Uploading</StatusPill>
 */
export function StatusPill({tone, dot = true, pulse = false, className, children}: StatusPillProps) {
  return (
    <span
      className={cx(
        'inline-flex flex-none items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold',
        TONES[tone],
        className
      )}>
      {dot && (
        <span
          aria-hidden="true"
          className={cx(DOT, pulse && 'animate-pulse')}
        />
      )}
      {children}
    </span>
  );
}
