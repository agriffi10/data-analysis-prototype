import {Button} from '../../components/Button';
import {TrashIcon} from '../../components/icons';
import {TOOLBAR_ACTION_ICON, TOOLBAR_ACTION_LABEL} from '../../components/toolbarAction';
import {ArchiveButton} from '../archive';
import {useSelection, itemId, type SelectableItem} from './selectionContext';

// Bulk-action glyphs (icon-only on mobile).
function BulkCopyIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={TOOLBAR_ACTION_ICON}
      aria-hidden="true">
      <rect
        x="9"
        y="9"
        width="11"
        height="11"
        rx="2"
      />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function QualityCheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={TOOLBAR_ACTION_ICON}
      aria-hidden="true">
      {/* A magnifier over a document — inspecting, not changing. */}
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6" />
      <circle
        cx="16"
        cy="13"
        r="4"
      />
      <path d="M19 16l3 3" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={TOOLBAR_ACTION_ICON}
      aria-hidden="true">
      {/* An arrow leaving a tray — handing something over, not moving it away. */}
      <path d="M12 3v11" />
      <path d="M8 7l4-4 4 4" />
      <path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
    </svg>
  );
}

function BulkMoveIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={TOOLBAR_ACTION_ICON}
      aria-hidden="true">
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <path d="M10 8l4 4-4 4" />
      <path d="M14 12H3" />
    </svg>
  );
}

/**
 * The action bar shown while one or more items are selected: select-all, the count, and the
 * operations the selection can take (delete, move, copy, rename, download, check quality, send).
 * Every button is disabled rather than hidden while an operation is in flight, so the bar's
 * shape never jumps under the pointer.
 *
 * @example
 * <SelectionToolbar allItems={items} onRequestDelete={openDelete} onRequestMove={openMove} … />
 */
export function SelectionToolbar({
  allItems,
  onRequestDelete,
  onRequestMove,
  onRequestCopy,
  onRequestQualityCheck,
  onRequestSend,
  onRequestArchive,
  archiveDisabledReason,
  writeLockReason,
  deleteDisabledReason,
  moveDisabledReason,
  spaceBusyReason,
  isBusy
}: {
  allItems: SelectableItem[];
  onRequestDelete: () => void;
  onRequestMove: () => void;
  onRequestCopy: () => void;
  /** Absent when the space can't be resolved (no space name) — the action is then omitted. */
  onRequestQualityCheck?: () => void;
  /**
   * Absent in the dev-unauth path and while the `files` flag is off — the
   * action is then omitted rather than disabled, which is the rule: hidden means removed.
   */
  onRequestSend?: () => void;
  /**
   * Absent in the dev-unauth path, while the `files` flag or the `archive` switch is off, and
   * inside the read-only `archive/` folder — removed rather than disabled, which is the rule.
   */
  onRequestArchive?: () => void;
  /**
   * Why the CURRENT SELECTION can't be archived (a portal-managed root). Disables Archive with
   * the reason attached, rather than removing it: the action exists here, and this selection is
   * what it refuses.
   */
  archiveDisabledReason?: string;
  /**
   * Why writes are unavailable in this folder at all. Move and Delete carry it
   * too — IAM denies both beneath `archive/`, so offering either only ever produced an
   * AccessDenied for a rule this app wrote.
   */
  writeLockReason?: string;
  /**
   * Why THIS SELECTION can't be deleted — a portal-managed root folder.
   * Distinct from `writeLockReason`, which is about the folder the user is standing IN.
   */
  deleteDisabledReason?: string;
  /** The same, for a move. A move is a rename here, so the wording differs from delete's. */
  moveDisabledReason?: string;
  /**
   * Why this SPACE will not take another operation from this session right now — an operation
   * of its own is still with the control plane.
   *
   * Deliberately not folded into `isBusy`, which reports work THIS BROWSER is doing and is false
   * for the minutes a plane run takes. It is also the last of the three reasons: a write lock and
   * a protected selection are facts about where you are and what you picked, where this one
   * passes on its own.
   */
  spaceBusyReason?: string;
  isBusy: boolean;
}) {
  const {count, isSelected, selectAll, clear} = useSelection();

  const allSelected = allItems.length > 0 && allItems.every((i) => isSelected(itemId(i)));
  const someSelected = allItems.some((i) => isSelected(itemId(i)));

  const active = count > 0;

  // A focused bulk-action bar: whole-selection Copy / Move / Delete
  // only (Download + Rename live in the details panel). Icon-only on
  // mobile, words alone at tablet, both at desktop. At tablet the six
  // words fit only once the glyphs, some gap and some padding give their
  // room back, and the count truncates rather than push an action out —
  // at tablet only: below it a truncated "128 selected" reads as "12…".
  return (
    <div
      className={`mb-4 flex h-11 items-center gap-2 rounded-lg border px-3 tablet:px-4 desktop:gap-3 ${
        active ? 'border-accent bg-accent-soft' : 'border-border bg-surface'
      }`}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-accent disabled:cursor-not-allowed disabled:opacity-45"
        checked={allSelected}
        // Nothing selectable is on screen — a listing whose only rows sit inside a collapsed
        // group. Clicking would call selectAll([]) and change nothing, which reads as a broken
        // control rather than an empty one.
        disabled={allItems.length === 0}
        ref={(el) => {
          if (el) el.indeterminate = someSelected && !allSelected;
        }}
        onChange={() => (allSelected ? clear() : selectAll(allItems))}
        aria-label="Select all"
      />

      <span
        aria-live="polite"
        className={`text-sm font-semibold tablet:min-w-0 tablet:truncate ${active ? 'text-accent-text' : 'text-text-3'}`}>
        {active ? `${count} selected` : 'Select all'}
      </span>

      <div className="flex-1" />

      {/* a read-only diagnostic on ONE file or folder. It lives here rather
          than on the top toolbar because it is scoped to the SELECTION, like its
          neighbours — and here it is already reachable at every breakpoint (a glyph
          on mobile, a word from tablet up) without a second mount. `user_settings` and
          `_data-quality-reports` need no guard: they are filtered out of the listing
          entirely, so they can never be selected. */}
      {onRequestQualityCheck && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
          onClick={onRequestQualityCheck}
          disabled={count !== 1 || isBusy}
          aria-label="Check data quality of the selected item">
          <QualityCheckIcon />
          <span className={TOOLBAR_ACTION_LABEL}>Check data quality</span>
        </Button>
      )}

      {/* a send is a copy INTO SOMEONE ELSE'S space, so it sits beside Copy rather
          than anywhere new — one or many items, files and folders alike. Shaped exactly like
          its neighbours at every width. */}
      {onRequestSend && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
          onClick={onRequestSend}
          disabled={count === 0 || isBusy}
          aria-label="Send to another user">
          <SendIcon />
          <span className={TOOLBAR_ACTION_LABEL}>Send to…</span>
        </Button>
      )}

      {/* archiving is a copy OUT of this space followed by a delete, so it sits
          between Send and Delete — the last of the "this leaves here" actions. Unlike the
          data-quality check it takes the WHOLE selection: archiving a set is the normal case. */}
      {onRequestArchive && (
        <ArchiveButton
          onClick={onRequestArchive}
          disabled={count === 0 || isBusy}
          disabledReason={count > 0 ? archiveDisabledReason : undefined}
          label="Archive selected items"
        />
      )}

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
        onClick={onRequestCopy}
        disabled={count === 0 || isBusy}
        disabledReason={count > 0 ? spaceBusyReason : undefined}
        aria-label="Copy selected items">
        <BulkCopyIcon />
        <span className={TOOLBAR_ACTION_LABEL}>Copy</span>
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
        disabledReason={count > 0 ? (writeLockReason ?? moveDisabledReason ?? spaceBusyReason) : undefined}
        aria-label="Move selected items">
        <BulkMoveIcon />
        <span className={TOOLBAR_ACTION_LABEL}>Move</span>
      </Button>

      <Button
        variant="dangerOutline"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-2 desktop:!px-3"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
        disabledReason={count > 0 ? (writeLockReason ?? deleteDisabledReason ?? spaceBusyReason) : undefined}
        aria-label="Delete selected items">
        <TrashIcon className={TOOLBAR_ACTION_ICON} />
        <span className={TOOLBAR_ACTION_LABEL}>Delete</span>
      </Button>
    </div>
  );
}
