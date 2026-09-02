import {cx} from '../../lib/cx';
import {Menu, type MenuItem} from '../../components/Menu';

export type TableMenuItem = {
  key: string;
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean; // a hairline above this item (e.g. before Drop)
};

type Props = {
  // Names the table for the accessible label (e.g. "Options for sales_2026").
  tableName: string;
  items: TableMenuItem[];
};

/**
 * the kebab (⋮) + popover, now composed from the shared `Menu` primitive
 * — behavior/a11y unchanged. Clicks stop propagation so opening the
 * menu never toggles the table row.
 *
 * @example
 * <TableActionsMenu tableName="orders" items={[{label: 'Preview rows', onSelect: preview}]} />
 */
export function TableActionsMenu({tableName, items}: Props) {
  const menuItems: MenuItem[] = items.flatMap((item) => {
    const action: MenuItem = {
      kind: 'action',
      label: item.label,
      onSelect: item.onSelect,
      tone: item.danger ? 'danger' : 'default',
      disabled: item.disabled
    };
    return item.separatorBefore ? [{kind: 'separator'}, action] : [action];
  });

  return (
    <Menu
      ariaLabel={`${tableName} actions`}
      className="flex-none"
      items={menuItems}
      trigger={({open, toggle, ref, menuId}) => (
        <button
          ref={ref}
          type="button"
          aria-label={`Options for ${tableName}`}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={(e) => {
            e.stopPropagation();
            toggle();
          }}
          className={cx(
            'grid h-[24px] w-[24px] place-items-center rounded-sm text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
            open && 'bg-surface-2 text-text'
          )}>
          <svg
            viewBox="0 0 24 24"
            fill="currentColor"
            className="h-4 w-4"
            aria-hidden="true">
            <circle
              cx="12"
              cy="5"
              r="1.6"
            />
            <circle
              cx="12"
              cy="12"
              r="1.6"
            />
            <circle
              cx="12"
              cy="19"
              r="1.6"
            />
          </svg>
        </button>
      )}
    />
  );
}
