import {cx} from '../lib/cx';

/** The chip's own `<li>` shape, in one place. Named so the copy guard can find it. */
const CHIP_SHELL =
  'flex min-w-0 max-w-full items-center gap-1 rounded-full border border-border bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm text-text';

type ChipListProps = {
  /** The list's accessible name, e.g. "Recipients". */
  ariaLabel: string;
  /** The BLOCK's own margin, which belongs to the caller — `mt-2` under a field, `mb-2` above one. */
  className?: string;
  children: React.ReactNode;
};

/**
 * The wrapping list for {@link Chip}. Owns the flow (left-to-right, wrapping at the container
 * width) and nothing else — the surrounding margin is positional and stays with the caller.
 *
 * @example
 * <ChipList ariaLabel="Recipients" className="mb-2">…</ChipList>
 */
export function ChipList({ariaLabel, className, children}: ChipListProps) {
  return (
    <ul
      aria-label={ariaLabel}
      className={cx('flex flex-wrap gap-1.5', className)}>
      {children}
    </ul>
  );
}

type ChipProps = {
  /** The value, rendered monospaced and truncated when it cannot fit. */
  name: string;
  /** An optional kind tag before the name (`USER` / `SPACE`), where a list mixes kinds. */
  tag?: string;
  /**
   * The remove button's ACCESSIBLE NAME, supplied whole by the caller. Never derived here:
   * the registry and every removal test query these buttons by name, and the fleet rule forbids
   * a reason becoming one.
   */
  removeLabel: string;
  onRemove: () => void;
  disabled?: boolean;
};

/**
 * One removable chip — the single implementation behind the recipient lists in
 * `UsernameChipsField`, `TableShareDialog` and `SendFilesDialog`, and the Data Explorer's filters
 * beside its Filter rows button.
 *
 * The three were byte-identical `<li>`s that had begun to drift: the remove target was `h-6 w-6`
 * in one and `h-5 w-5` in the other two — 21px and 17.5px, both under WCAG 2.2 SC 2.5.8's 24px
 * minimum. Consistency was coincidence, and nothing was holding it.
 *
 * WIDTH IS BOUNDED HERE, which none of the copies did. A username may be 63 characters
 * (`^[a-z][a-z0-9_]{2,62}$`), and at roughly 62px of chrome plus ~8.7px per monospaced
 * character that extrapolates to a ~610px chip inside a 448px dialog. The name truncates
 * instead, carrying its full value as a `title` for hover and in the remove button's accessible
 * name for everyone else, and the remove target stays `flex-none` so it is reachable at any
 * length.
 *
 * @example
 * <Chip name={r.name} tag="SPACE" removeLabel={`Remove space ${r.name}`} onRemove={() => remove(r)} />
 */
export function Chip({name, tag, removeLabel, onRemove, disabled = false}: ChipProps) {
  return (
    <li className={CHIP_SHELL}>
      {tag && <span className="flex-none text-xs uppercase tracking-wide text-text-3">{tag}</span>}
      <span
        // `title` is the hover affordance for a truncated name; keyboard and screen-reader users
        // get the full value from the remove button's own accessible name.
        title={name}
        className="min-w-0 truncate font-mono">
        {name}
      </span>
      <button
        type="button"
        aria-label={removeLabel}
        disabled={disabled}
        onClick={onRemove}
        className={cx(
          // 24 CSS px is WCAG 2.2 SC 2.5.8's minimum pointer target. It is written absolutely
          // because it is a THRESHOLD, not a step on the spacing scale: that scale is rem-derived,
          // so `h-6` draws 21px at this app's 14px root while reading as if it met the minimum,
          // and `h-7` clears it by half a pixel today but falls under it if the root ever shrinks.
          // `flex-none` keeps the target that size however long the name beside it is.
          'grid h-[24px] w-[24px] flex-none place-items-center rounded-full text-text-3',
          'hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2',
          'focus-visible:ring-accent disabled:opacity-45'
        )}>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="h-3 w-3"
          aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </li>
  );
}
