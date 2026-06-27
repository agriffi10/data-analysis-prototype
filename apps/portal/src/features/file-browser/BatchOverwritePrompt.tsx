import { Button } from '../../components/Button';

type Props = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

// SPEC-019/039 FR-005: one Overwrite-all / Cancel confirmation covering a whole
// batch whose destination already has matching items. Shared between Move and
// Copy (react-best-practices abstraction pass).
export function BatchOverwritePrompt({ count, onOverwriteAll, onCancel }: Props) {
  return (
    <div
      role="alertdialog"
      aria-label="Destination already has items"
      className="mb-4 rounded-lg border border-warning-soft bg-warning-soft p-4 text-sm text-warning"
    >
      <p className="font-medium">{count} item(s) already exist at the destination.</p>
      <div className="mt-3 flex gap-2">
        <Button variant="danger" size="sm" onClick={onOverwriteAll}>
          Overwrite all
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
