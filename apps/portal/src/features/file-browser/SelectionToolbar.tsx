import {Button} from '../../components/Button';
import {TrashIcon} from '../../components/icons';
import {ArchiveButton} from '../archive';
import {useSelection, itemId, type SelectableItem} from './selectionContext';

// Bulk-action glyphs (icon-only on mobile, SPEC-099 FR-006).
function BulkCopyIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[15px] w-[15px]"
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
      className="h-[15px] w-[15px]"
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
      className="h-[15px] w-[15px]"
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
      className="h-[15px] w-[15px]"
      aria-hidden="true">
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <path d="M10 8l4 4-4 4" />
      <path d="M14 12H3" />
    </svg>
  );
}

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
  isBusy
}: {
  allItems: SelectableItem[];
  onRequestDelete: () => void;
  onRequestMove: () => void;
  onRequestCopy: () => void;
  /** Absent when the space can't be resolved (no space name) — the action is then omitted. */
  onRequestQualityCheck?: () => void;
  /**
   * Absent in the dev-unauth path and while the `files` flag is off (SPEC-167 FR-001) — the
   * action is then omitted rather than disabled, which is SPEC-163's rule: hidden means removed.
   */
  onRequestSend?: () => void;
  /**
   * SPEC-172. Absent in the dev-unauth path, while the `files` flag is off, and inside the
   * read-only `archive/` folder — removed rather than disabled, which is SPEC-163's rule.
   */
  onRequestArchive?: () => void;
  /**
   * Why the CURRENT SELECTION can't be archived (a portal-managed root). Disables Archive with
   * the reason attached, rather than removing it: the action exists here, and this selection is
   * what it refuses.
   */
  archiveDisabledReason?: string;
  /**
   * Why writes are unavailable in this folder at all (SPEC-172 FR-004). Move and Delete carry it
   * too — IAM denies both beneath `archive/`, so offering either only ever produced an
   * AccessDenied for a rule this app wrote.
   */
  writeLockReason?: string;
  isBusy: boolean;
}) {
  const {count, isSelected, selectAll, clear} = useSelection();

  const allSelected = allItems.length > 0 && allItems.every((i) => isSelected(itemId(i)));
  const someSelected = allItems.some((i) => isSelected(itemId(i)));

  const active = count > 0;

  // A focused bulk-action bar (SPEC-096): whole-selection Copy / Move / Delete
  // only (Download + Rename live in the details panel, SPEC-097). Labelled at
  // ≥ tablet, icon-only on mobile (SPEC-099 FR-006).
  return (
    <div
      className={`mb-4 flex h-11 items-center gap-2 rounded-lg border px-3 tablet:gap-3 tablet:px-4 ${
        active ? 'border-accent bg-accent-soft' : 'border-border bg-surface'
      }`}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-accent"
        checked={allSelected}
        ref={(el) => {
          if (el) el.indeterminate = someSelected && !allSelected;
        }}
        onChange={() => (allSelected ? clear() : selectAll(allItems))}
        aria-label="Select all"
      />

      <span
        aria-live="polite"
        className={`text-sm font-semibold ${active ? 'text-accent-text' : 'text-text-3'}`}>
        {active ? `${count} selected` : 'Select all'}
      </span>

      <div className="flex-1" />

      {/* SPEC-113: a read-only diagnostic on ONE file or folder. It lives here rather
          than on the top toolbar because it is scoped to the SELECTION, like its
          neighbours — and here it is already reachable at every breakpoint (labelled
          at ≥ tablet, icon-only on mobile) without a second mount. `user_settings` and
          `_data-quality-reports` need no guard: they are filtered out of the listing
          entirely, so they can never be selected. */}
      {onRequestQualityCheck && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
          onClick={onRequestQualityCheck}
          disabled={count !== 1 || isBusy}
          aria-label="Check data quality of the selected item">
          <QualityCheckIcon />
          <span className="hidden tablet:inline">Check quality</span>
        </Button>
      )}

      {/* SPEC-167: a send is a copy INTO SOMEONE ELSE'S space, so it sits beside Copy rather
          than anywhere new — one or many items, files and folders alike. Labelled at ≥ tablet,
          icon-only on mobile, exactly like its neighbours. */}
      {onRequestSend && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
          onClick={onRequestSend}
          disabled={count === 0 || isBusy}
          aria-label="Send selected items to someone">
          <SendIcon />
          <span className="hidden tablet:inline">Send to…</span>
        </Button>
      )}

      {/* SPEC-172: archiving is a copy OUT of this space followed by a delete, so it sits
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
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
        onClick={onRequestCopy}
        disabled={count === 0 || isBusy}
        aria-label="Copy selected items">
        <BulkCopyIcon />
        <span className="hidden tablet:inline">Copy</span>
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
        disabledReason={count > 0 ? writeLockReason : undefined}
        aria-label="Move selected items">
        <BulkMoveIcon />
        <span className="hidden tablet:inline">Move</span>
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 !text-danger hover:!bg-danger-soft hover:!text-danger tablet:!h-8 tablet:!px-3"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
        disabledReason={count > 0 ? writeLockReason : undefined}
        aria-label="Delete selected items">
        <TrashIcon />
        <span className="hidden tablet:inline">Delete</span>
      </Button>
    </div>
  );
}
