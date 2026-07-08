import {Menu, type MenuItem} from '../components/Menu';

export type LandingNavLink = {label: string; href: string};

export type LandingNavMenuProps = {
  links: LandingNavLink[];
};

/**
 * Mobile-only (`< tablet`) hamburger disclosure for the landing page's section
 * anchors (Features / Security), so they stay reachable below `tablet` where the
 * inline link group is hidden (SPEC-104). Composes the shared `Menu` primitive —
 * each anchor navigates via the URL hash and closes the panel; Escape /
 * outside-click close are inherited.
 *
 * @example
 * <LandingNavMenu links={[{label: 'Features', href: '#features'}]} />
 */
export function LandingNavMenu({links}: LandingNavMenuProps) {
  const items: MenuItem[] = links.map((link) => ({
    kind: 'action',
    label: link.label,
    onSelect: () => {
      window.location.hash = link.href;
    }
  }));

  return (
    <Menu
      ariaLabel="Site navigation"
      align="left"
      className="tablet:hidden"
      items={items}
      trigger={({open, toggle, ref, menuId}) => (
        <button
          ref={ref}
          type="button"
          aria-label="Open menu"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={toggle}
          className="inline-flex h-10 w-10 items-center justify-center rounded-md text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-5 w-5"
            aria-hidden="true">
            <path
              strokeLinecap="round"
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>
      )}
    />
  );
}
