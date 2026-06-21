import { type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { cx } from '../lib/cx';

// Primary tab navigation (Files | Query) in the authenticated topbar
// (SPEC-035 FR-001, design-system §6). Underline tabs — distinct from the
// sidebar's filled accent-soft item so the two nav levels read differently.
// Route-driven via NavLink, so deep-links + back/forward set the active tab.
// Rendered only in the authenticated shell (the Header gates on auth status).

type Tab = { to: string; label: string; icon: ReactNode };

const TABS: Tab[] = [
  {
    to: '/files',
    label: 'Files',
    icon: (
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    ),
  },
  {
    to: '/query',
    label: 'Query',
    icon: (
      <>
        <ellipse cx="12" cy="6" rx="8" ry="3" />
        <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
        <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
      </>
    ),
  },
];

export function PrimaryNav() {
  return (
    <nav aria-label="Primary" className="flex h-full items-center gap-1">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) =>
            cx(
              'flex h-full items-center gap-2 border-b-2 px-3 text-base font-medium',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              isActive
                ? 'border-accent text-accent-text'
                : 'border-transparent text-text-2 hover:text-text',
            )
          }
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4 flex-none"
            aria-hidden="true"
          >
            {tab.icon}
          </svg>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
