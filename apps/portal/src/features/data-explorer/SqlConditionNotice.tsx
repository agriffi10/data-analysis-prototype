import {Button} from '../../components/Button';

export type SqlConditionNoticeProps = {
  /** The stored condition, shown exactly as it was typed. */
  expression: string;
  /** Takes the condition off — one apply, and so one execution. */
  onRemove: () => void;
  /** Opens the whole statement in Query. Absent while the `query` flag is off. */
  onOpenInQuery?: () => void;
};

/**
 * A condition typed into the filter box the Explorer no longer has, kept rather than dropped.
 *
 * A tab, a history entry or a saved view written before the builder can still carry one. It still
 * applies — the statement renders it exactly as it always did — so it is shown here verbatim, with
 * the two ways out: remove it, or open the statement in Query, where SQL is edited. Converting it
 * into conditions would need a SQL parser, and whatever the parser missed would vanish unannounced,
 * which is the one outcome a user's filter must never meet.
 */
export function SqlConditionNotice({expression, onRemove, onOpenInQuery}: SqlConditionNoticeProps) {
  return (
    <div
      role="group"
      aria-label="Condition written in SQL"
      className="flex flex-none flex-wrap items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-2">
      <p className="min-w-0 flex-1 basis-64 text-sm text-text-2">
        Also filtered by a condition written in SQL, which the Explorer no longer edits:{' '}
        <code className="break-all font-mono text-text">{expression}</code>
      </p>
      <Button
        size="sm"
        onClick={onRemove}>
        Remove SQL condition
      </Button>
      {onOpenInQuery && (
        <Button
          size="sm"
          onClick={onOpenInQuery}>
          Open in Query
        </Button>
      )}
    </div>
  );
}
