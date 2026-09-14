import {Button} from '../../components/Button';

const LABEL = 'Restore Archived Data';

type Props = {
  onClick: () => void;
  /**
   * `toolbar` — the top toolbar's, at its natural width with the whole label.
   * `action-bar` — the mobile action bar's, filling its share of the row and reading "Restore".
   */
  placement?: 'toolbar' | 'action-bar';
};

/**
 * The Restore Archived Data entry point, on the file browser's primary toolbar.
 *
 * It belongs beside Upload and New folder rather than on the selection toolbar, because a
 * restore has no selection: what it needs is an id the user pastes. That is also why the label
 * says "Archived Data" and not "Archive" — the two controls do opposite things and must not read
 * as a pair of near-identical words.
 *
 * In the mobile action bar the visible word is "Restore" alone. The bar splits a phone's width
 * three ways, and in a third of it the whole label wraps to three lines — taller than the button,
 * so the text spills out above and below it. The accessible name stays the whole label, which
 * the visible word begins, as SC 2.5.3 asks: a screen reader, voice control and every test find
 * the control by the same name at every width.
 */
export function RestoreArchiveButton({onClick, placement = 'toolbar'}: Props) {
  const inActionBar = placement === 'action-bar';
  return (
    <Button
      variant="default"
      className={inActionBar ? '!h-11 flex-1' : 'shrink-0'}
      aria-label={inActionBar ? LABEL : undefined}
      onClick={onClick}>
      {inActionBar ? 'Restore' : LABEL}
    </Button>
  );
}
