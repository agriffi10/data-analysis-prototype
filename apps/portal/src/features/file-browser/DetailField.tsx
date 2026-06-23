import { CopyButton } from '../../components/CopyButton';

type Props = {
  label: string;
  value: string;
  // When set, renders a copy-to-clipboard button; the string is woven into the
  // button's label, e.g. "path" → "Copy path".
  copyLabel?: string;
};

// One labelled, read-only row in a details drawer (file metadata or folder).
// Optionally trails a copy-to-clipboard button for the value.
export function DetailField({ label, value, copyLabel }: Props) {
  return (
    <div className="border-b border-border-2 py-3 last:border-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-text-3">
        {label}
      </dt>
      <dd className="mt-1 flex items-start gap-2">
        <span className="min-w-0 flex-1 break-all text-sm text-text">{value}</span>
        {copyLabel && <CopyButton value={value} label={copyLabel} />}
      </dd>
    </div>
  );
}
