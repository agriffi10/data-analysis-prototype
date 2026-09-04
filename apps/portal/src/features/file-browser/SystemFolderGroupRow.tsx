import {Badge} from '../../components/Badge';
import {ChevronDownIcon, ChevronRightIcon, FolderRowIcon} from '../../components/icons';
import {SYSTEM_FOLDER_GROUP_NAME, systemFolderGroupCaption} from './systemFolders';

type Props = {
  /** How many folders the row is standing in for; shown so a collapsed row says what it hides. */
  count: number;
  expanded: boolean;
  onToggle: () => void;
  /** Reserve the (empty) checkbox column so the row aligns with selectable rows. */
  selectable: boolean;
  /** `grid` (default) = the ≥ tablet table row; `mobile` = the 56px two-line card row. */
  variant?: 'grid' | 'mobile';
};

/**
 * The `system_settings` disclosure row — one listing row standing in for the app-managed
 * folders at a space root, collapsed by default.
 *
 * Navigation is not what it does: there is no such prefix to open, so the row toggles and
 * nothing else, and it carries no checkbox because selecting a group that is not a key would
 * have to mean selecting its members, which is what the members' own rows are for. The empty
 * spacer keeps the checkbox column aligned exactly as the `..` row does.
 *
 * @example
 * <SystemFolderGroupRow count={3} expanded={false} onToggle={toggle} selectable={writable} />
 */
export function SystemFolderGroupRow({count, expanded, onToggle, selectable, variant = 'grid'}: Props) {
  const Chevron = expanded ? ChevronDownIcon : ChevronRightIcon;
  const caption = systemFolderGroupCaption(count);

  if (variant === 'mobile') {
    return (
      <li className="flex h-14 items-center border-b border-border-2 pl-3 pr-2 last:border-0 hover:bg-surface-2">
        <button
          className="flex min-w-0 flex-1 items-center gap-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`${SYSTEM_FOLDER_GROUP_NAME}: ${caption}`}>
          <Chevron className="h-4 w-4 flex-none text-text-3" />
          <FolderRowIcon />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-base font-medium text-text-2">{SYSTEM_FOLDER_GROUP_NAME}</span>
            <span className="block truncate text-xs text-text-3">{caption}</span>
          </span>
        </button>
      </li>
    );
  }

  return (
    <li className="flex h-12 items-center border-b border-border-2 last:border-0 hover:bg-surface-2">
      {selectable && (
        <span
          className="w-10 shrink-0"
          aria-hidden="true"
        />
      )}
      <button
        className="flex min-w-0 flex-1 items-center gap-2.5 px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-label={`${SYSTEM_FOLDER_GROUP_NAME}: ${caption}`}>
        <Chevron className="h-4 w-4 flex-none text-text-3" />
        <FolderRowIcon />
        <span className="truncate text-base font-medium text-text-2">{SYSTEM_FOLDER_GROUP_NAME}</span>
      </button>
      <span className="w-24 pr-4 text-right text-sm text-text-3">—</span>
      <span className="w-40 pr-4" />
      <span className="hidden w-28 pr-4 text-right desktop:block">
        <Badge>Managed</Badge>
      </span>
      <span className="w-44 pr-4" />
    </li>
  );
}
