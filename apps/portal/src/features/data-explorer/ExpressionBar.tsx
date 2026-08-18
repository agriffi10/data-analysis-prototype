import {useState} from 'react';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';

export type ExpressionBarProps = {
  /** The applied expression, or null when there is none. */
  expression: string | null;
  /** Applies the fragment — the gesture that mints an execution. */
  onApply: (expression: string | null) => void;
};

/**
 * A free-text `WHERE` fragment, applied on an explicit gesture.
 *
 * **Never on change.** Every apply here is an Athena execution and a bill, so a keystroke
 * cannot be one — the bar holds its own text and hands it over on Enter or on Apply, and
 * nothing else in this component talks to the query.
 *
 * The fragment is the user's own SQL and reaches the statement verbatim, exactly as
 * Monaco's buffer does: `sqlLiteral` is for values the app quotes on a user's behalf, and
 * escaping this would only break the operators the bar exists to offer.
 *
 * **It is not gated on the `query` flag**: a flag is presentation, never
 * authorization — it revokes no grant and the IAM boundary is identical either way — so
 * gating this input would buy nothing and cost the feature the filters people actually
 * write. The accepted cost is stated plainly in the spec: an environment that turns
 * `query` off to tidy SQL away still offers a SQL input here.
 */
export function ExpressionBar({expression, onApply}: ExpressionBarProps) {
  const applied = expression ?? '';
  const [text, setText] = useState(applied);

  // Re-seeded during render when the APPLIED expression changes underneath the bar —
  // history navigation and Remove all both rewrite it. A failed apply changes nothing
  // here, which is what leaves the offending text in place to be corrected.
  const [previousApplied, setPreviousApplied] = useState(applied);
  if (previousApplied !== applied) {
    setPreviousApplied(applied);
    setText(applied);
  }

  const submit = () => onApply(text.trim() === '' ? null : text);

  return (
    <div className="flex flex-none items-end gap-2">
      <div className="min-w-0 flex-1">
        <Input
          className="font-mono text-sm"
          label="Filter expression"
          placeholder="status = 'open' AND qty > 100"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
            e.preventDefault();
            submit();
          }}
        />
      </div>
      <Button onClick={submit}>Apply expression</Button>
    </div>
  );
}
