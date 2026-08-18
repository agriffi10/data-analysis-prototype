import {type ReactNode} from 'react';
import {NavLink} from 'react-router';
import {cx} from '../lib/cx';

type Tab = {to: string; label: string; icon: ReactNode};

const TABS: Tab[] = [
  {
    to: '/files',
    label: 'Files',
    icon: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  },
  {
    to: '/query',
    label: 'Query',
    icon: (
      <>
        <ellipse
          cx="12"
          cy="6"
          rx="8"
          ry="3"
        />
        <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
        <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
      </>
    )
  },
  {
    to: '/explore',
    label: 'Data Explorer',
    icon: (
      <>
        <rect
          x="3"
          y="4"
          width="18"
          height="16"
          rx="2"
        />
        <path d="M3 9h18M9 9v11" />
      </>
    )
  },
  {
    to: '/connections',
    label: 'Connections',
    icon: (
      <>
        <circle
          cx="7"
          cy="7"
          r="3"
        />
        <circle
          cx="17"
          cy="17"
          r="3"
        />
        <path d="M10 7h4a3 3 0 0 1 3 3v4M7 10v4a3 3 0 0 0 3 3h4" />
      </>
    )
  },
  {
    to: '/data-quality',
    label: 'Data quality',
    icon: (
      <>
        <path d="M9 12l2 2 4-4" />
        <path d="M21 12a9 9 0 1 1-3.5-7.1" />
      </>
    )
  }
];

export type PrimaryNavProps = {
  /**
   * Is this destination's feature on? Required, not defaulted — a default would make an
   * unwired caller ship every tab while looking correct, which is the one failure this
   * prop exists to prevent.
   */
  isPathEnabled: (to: string) => boolean;
};

/**
 * Primary tab navigation (Files | Query | Data Explorer | Connections | Data quality) in the authenticated
 * topbar. Underline tabs — deliberately distinct from the sidebar's filled
 * item so the two nav levels read differently. Route-driven via NavLink, so
 * deep links and back/forward set the active tab. The Header gates rendering
 * on auth status.
 *
 * **Gating arrives as a PREDICATE, not as a hook call** (SPEC-163 FR-001): this file lives in
 * `components/`, which may not import from `features/`, and the rule is worth more
 * than the convenience — `Header` is the one place that knows both the auth state and the
 * flags, so it is the one place that decides.
 *
 * A disabled tab is REMOVED, never rendered-and-disabled and never visually hidden: a
 * `hidden` tab is still in the accessibility tree, so it would remain announced and focusable
 * for a feature the environment says is not there.
 *
 * @example
 * <PrimaryNav isPathEnabled={(to) => !hidden.has(to)} />
 */
export function PrimaryNav({isPathEnabled}: PrimaryNavProps) {
  return (
    <nav
      aria-label="Primary"
      className="flex h-full items-center gap-1">
      {TABS.filter((tab) => isPathEnabled(tab.to)).map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({isActive}) =>
            cx(
              'flex h-full items-center gap-2 border-b-2 px-3 text-base font-medium',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              isActive ? 'border-accent text-accent-text' : 'border-transparent text-text-2 hover:text-text'
            )
          }>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4 flex-none"
            aria-hidden="true">
            {tab.icon}
          </svg>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
