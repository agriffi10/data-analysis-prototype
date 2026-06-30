import type {ReactNode} from 'react';
import {cx} from '../lib/cx';

type PageLayoutProps = {
  // The page title (rendered as the sole <h1>) and an optional supporting line.
  title: ReactNode;
  subtitle?: ReactNode;
  // Right-aligned action cluster in the page header (buttons, filters, …).
  actions?: ReactNode;
  // Extends the content column — callers cap the width and set the row gap here
  // (e.g. `max-w-[920px] gap-3`). The base padding/flex is always applied.
  contentClassName?: string;
  children: ReactNode;
};

// Shared full-width page chrome for the top-level management surfaces (Connections,
// Notifications). Renders the design's `.page-head` — title + optional subtitle on
// the left, an actions cluster on the right, with a bottom border — above a padded,
// width-capped content column. The outer element is the page's `<main id="main">`
// landmark and the sole vertical scroll container (the skip-link target; mirrors
// docs/design/notifications.html + shared-connections.html). Overlays (modals,
// drawers, toasts) are fixed-position and belong as siblings of this component, not
// inside `children`.
export function PageLayout({title, subtitle, actions, contentClassName, children}: PageLayoutProps) {
  return (
    <main
      id="main"
      className="flex flex-1 flex-col overflow-auto">
      <div className="flex items-center gap-4 border-b border-border px-6 py-5">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-text">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-text-2">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-none items-center gap-2">{actions}</div>}
      </div>

      <div className={cx('flex flex-col px-6 py-6', contentClassName)}>{children}</div>
    </main>
  );
}
