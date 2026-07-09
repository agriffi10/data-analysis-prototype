import {Banner} from '../../components/Banner';
import {toUserMessage} from '../../lib/errorMessages';

/** `code` is the stable app/AWS code; the banner maps it to friendly text (SPEC-106). */
export type OperationError = {label: string; message?: string; code?: string};

type Props = {
  count: number; // how many items succeeded
  pastVerb: string; // "Deleted" / "Moved" / "Copied"
  failVerb: string; // "delete" / "move" / "copy"
  errors: OperationError[];
  onDismiss: () => void;
};

// SPEC-018/019/039: result banner for a bulk delete/move/copy — success count
// plus any per-item failures. Shared shell extracted from the three near-identical
// FileBrowser banners (react-best-practices abstraction pass).
export function OperationSummaryBanner({count, pastVerb, failVerb, errors, onDismiss}: Props) {
  return (
    <Banner
      variant={errors.length === 0 ? 'success' : 'warning'}
      // Clean result is a polite status; a partial failure is an error-class
      // message and should assert (WCAG 4.1.3).
      role={errors.length === 0 ? 'status' : 'alert'}
      onDismiss={onDismiss}
      className="mb-4"
      title={`${pastVerb} ${count} ${count === 1 ? 'item' : 'items'}.`}>
      {errors.length > 0 && (
        <>
          <p className="mt-1">
            Could not {failVerb} {errors.length}:
          </p>
          <ul className="mt-1 list-disc pl-5">
            {errors.map((e, i) => (
              <li key={`${e.label}-${i}`}>
                {e.label} — {toUserMessage({code: e.code, message: e.message}).message}
              </li>
            ))}
          </ul>
        </>
      )}
    </Banner>
  );
}
