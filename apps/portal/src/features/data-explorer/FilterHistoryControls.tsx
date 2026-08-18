import {Button} from '../../components/Button';

export type FilterHistoryControlsProps = {
  canGoBack: boolean;
  canGoForward: boolean;
  onBack: () => void;
  onForward: () => void;
};

export const NO_HISTORY_BACK = 'This is the earliest set of filters in this tab.';
export const NO_HISTORY_FORWARD = 'This is the latest set of filters in this tab.';

/**
 * Back and forward through this tab's recent query descriptions.
 *
 * Both refusals ride `Button.disabledReason` rather than `disabled`, so the control keeps
 * its place in the tab order and says why it is unavailable — "the button is
 * greyed out" is the state, and the reason for it is the only useful part.
 *
 * Stepping restores a DESCRIPTION. Whether that costs anything is then the execution
 * cache's business: an identical statement resolves to the run already made.
 */
export function FilterHistoryControls({canGoBack, canGoForward, onBack, onForward}: FilterHistoryControlsProps) {
  return (
    <>
      <Button
        size="sm"
        aria-label="Back to previous filters"
        disabledReason={canGoBack ? undefined : NO_HISTORY_BACK}
        onClick={onBack}>
        ‹ Back
      </Button>
      <Button
        size="sm"
        aria-label="Forward to next filters"
        disabledReason={canGoForward ? undefined : NO_HISTORY_FORWARD}
        onClick={onForward}>
        Forward ›
      </Button>
    </>
  );
}
