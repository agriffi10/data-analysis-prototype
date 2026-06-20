import { Banner } from '../../components/Banner';

export type OperationError = { label: string; message: string };

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
export function OperationSummaryBanner({
  count,
  pastVerb,
  failVerb,
  errors,
  onDismiss,
}: Props) {
  return (
    <Banner
      variant={errors.length === 0 ? 'success' : 'warning'}
      role="status"
      onDismiss={onDismiss}
      className="mb-4"
      title={`${pastVerb} ${count} ${count === 1 ? 'item' : 'items'}.`}
    >
      {errors.length > 0 && (
        <>
          <p className="mt-1">
            Could not {failVerb} {errors.length}:
          </p>
          <ul className="mt-1 list-disc pl-5">
            {errors.map((e, i) => (
              <li key={`${e.label}-${i}`}>
                {e.label} — {e.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </Banner>
  );
}
