import {IconButton} from '../../components/IconButton';
import {FeedbackIcon} from '../../components/icons';

type FeedbackButtonProps = {
  /** Opens the dialog. The host owns whether it is mounted. */
  onOpen: () => void;
};

/**
 * The header's Give feedback control, beside the help control.
 *
 * Rendered at `tablet` and above only, and the host decides that by NOT MOUNTING it below —
 * never by a `tablet:` class. The mobile header is already over budget at 375px, so the control
 * belongs in the navigation drawer there; and a CSS-hidden button is still in the accessibility
 * tree and still in the DOM, which is exactly what a test counting the header's controls would
 * miss.
 *
 * @example
 * {!isMobile && <FeedbackButton onOpen={() => setFeedbackOpen(true)} />}
 */
export function FeedbackButton({onOpen}: FeedbackButtonProps) {
  return (
    <IconButton
      label="Give feedback"
      onClick={onOpen}>
      <FeedbackIcon className="h-5 w-5" />
    </IconButton>
  );
}
