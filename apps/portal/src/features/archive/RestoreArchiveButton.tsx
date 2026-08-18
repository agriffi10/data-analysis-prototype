import {Button} from '../../components/Button';

type Props = {
  onClick: () => void;
  /** Fills the mobile action bar's row; the top toolbar's sits at its natural width. */
  fullWidth?: boolean;
};

/**
 * The Restore Archived Data entry point, on the file browser's primary toolbar.
 *
 * It belongs beside Upload and New folder rather than on the selection toolbar, because a
 * restore has no selection: what it needs is an id the user pastes. That is also why the label
 * says "Archived Data" and not "Archive" — the two controls do opposite things and must not read
 * as a pair of near-identical words.
 */
export function RestoreArchiveButton({onClick, fullWidth = false}: Props) {
  return (
    <Button
      variant="default"
      className={fullWidth ? '!h-11 flex-1' : 'shrink-0'}
      onClick={onClick}>
      Restore Archived Data
    </Button>
  );
}
