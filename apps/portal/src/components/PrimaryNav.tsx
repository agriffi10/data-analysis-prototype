import {NavLink} from '../lib/navigation';
import {cx} from '../lib/cx';
import {DestinationIcon, type Destination} from './DestinationIcon';

type Tab = {to: string; label: string; icon: Destination};

const TABS: Tab[] = [
  {to: '/files', label: 'Files', icon: 'files'},
  {to: '/query', label: 'Query', icon: 'query'},
  {to: '/explore', label: 'Data Explorer', icon: 'explore'},
  {to: '/connections', label: 'Shared spaces', icon: 'connections'},
  {to: '/data-quality', label: 'Data quality', icon: 'dataQuality'}
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
 * Primary tab navigation (Files | Query | Data Explorer | Shared spaces | Data quality) in the authenticated
 * topbar. Underline tabs — deliberately distinct from the sidebar's filled
 * item so the two nav levels read differently. Route-driven via NavLink, so
 * deep links and back/forward set the active tab. The Header gates rendering
 * on auth status.
 *
 * **Gating arrives as a PREDICATE, not as a hook call**: this file lives in
 * `components/`, which may not import from `features/`, and the rule is worth more
 * than the convenience — `Header` is the one place that knows both the auth state and the
 * flags, so it is the one place that decides.
 *
 * A disabled tab is REMOVED, never rendered-and-disabled and never visually hidden: a
 * `hidden` tab is still in the accessibility tree, so it would remain announced and focusable
 * for a feature the environment says is not there.
 *
 * **The words are the navigation; the icons wait for `desktop`.** Between `tablet` and `desktop`
 * the bar cannot hold every tab's icon beside the named controls, and a label never wraps — a
 * two-line tab in a one-line bar is the failure, so a bar that is short of room should overflow
 * where a width sweep will see it rather than wrap where it looks almost right.
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
              'flex h-full items-center gap-2 whitespace-nowrap border-b-2 px-3 text-base font-medium',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              isActive ? 'border-accent text-accent-text' : 'border-transparent text-text-2 hover:text-text'
            )
          }>
          <DestinationIcon
            destination={tab.icon}
            className="hidden h-4 w-4 flex-none desktop:block"
          />
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
