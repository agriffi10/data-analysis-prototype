import { NavLink } from 'react-router-dom';
import { useAuth } from '../features/auth';
import { cx } from '../lib/cx';
import { FolderIcon } from './icons';

// Left navigation sidebar for the authenticated app shell (design-system §5 /
// mockup.html). 248px surface panel with a right hairline border. Currently it
// holds only the "My Files" user-space entry — the Shared Connections section
// from the design is intentionally omitted until the connections feature exists.
// Hidden below md so the file browser fills narrow viewports.
export function Sidebar() {
  const { user } = useAuth();
  const label = user?.username ?? 'My Files';

  return (
    <aside
      aria-label="My files navigation"
      className="hidden w-[248px] flex-shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-surface px-3 py-4 md:flex"
    >
      <p className="px-3 pb-2 pt-3 text-xs font-semibold uppercase tracking-[.04em] text-text-3">My Files</p>
      <NavLink
        to="/files"
        className={({ isActive }) =>
          cx(
            'flex items-center gap-3 rounded-md px-3 py-2 text-base font-medium',
            isActive ? 'bg-accent-soft text-accent-text' : 'text-text-2 hover:bg-surface-2 hover:text-text'
          )
        }
      >
        <FolderIcon className="h-[18px] w-[18px] flex-none" />
        <span className="min-w-0 truncate">{label}</span>
        <span className="ml-auto flex-none text-xs text-text-3">user space</span>
      </NavLink>
    </aside>
  );
}
