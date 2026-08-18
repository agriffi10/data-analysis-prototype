import type {ReactNode} from 'react';
import {cx} from '../lib/cx';

type PageLayoutProps = {
  /** The page title, rendered as the sole `<h1>`. */
  title: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned action cluster in the page header (buttons, filters, …). */
  actions?: ReactNode;
  /**
   * Extends the content column — callers cap the width and set the row gap here
   * (e.g. `max-w-[920px] gap-3`). The base padding/flex is always applied.
   */
  contentClassName?: string;
  /**
   * When true, the header stacks below `tablet`: title (+ subtitle) on the first
   * line, then the `actions` cluster on its own full-width row beneath it. At
   * `≥ tablet` the header is the usual single inline row (title left, actions
   * right). Default false — other hosts (Connections/Help) are unaffected unless
   * they opt in.
   */
  stackActionsOnMobile?: boolean;
  children: ReactNode;
};

/**
 * Shared full-width page chrome for top-level management surfaces
 * (Connections, Notifications): header with title/subtitle/actions above a
 * padded, width-capped content column. The outer element is the page's
 * `<main id="main">` landmark — the skip-link target — and the sole vertical
 * scroll container. Overlays (modals, drawers, toasts) are fixed-position and
 * belong as siblings of this component, not inside `children`.
 *
 * @example
 * <PageLayout
 *   title="Notifications"
 *   subtitle="Updates about your spaces"
 *   actions={<Button onClick={markAllRead}>Mark all read</Button>}
 *   contentClassName="max-w-[920px] gap-3">
 *   <NotificationsList />
 * </PageLayout>
 */
export function PageLayout({
  title,
  subtitle,
  actions,
  contentClassName,
  stackActionsOnMobile = false,
  children
}: PageLayoutProps) {
  return (
    <main
      id="main"
      className="flex flex-1 flex-col overflow-auto">
      <div
        className={cx(
          'border-b border-border px-6 py-5',
          // Opt-in: stack the actions under the title below tablet; inline row at
          // ≥ tablet. Default: the shipped single inline row at every width.
          stackActionsOnMobile
            ? 'flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:gap-4'
            : 'flex items-center gap-4'
        )}>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-text">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-text-2">{subtitle}</p>}
        </div>
        {actions && (
          <div
            className={cx(
              'flex items-center gap-2',
              stackActionsOnMobile ? 'flex-wrap tablet:flex-none' : 'flex-none'
            )}>
            {actions}
          </div>
        )}
      </div>

      <div className={cx('flex flex-col px-6 py-6', contentClassName)}>{children}</div>
    </main>
  );
}
