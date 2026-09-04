import {CopyButton} from '../../components/CopyButton';
import {SECTION_CAPTION} from '../../components/fieldStyles';

type Props = {
  label: string;
  value: string;
  // When set, renders a copy-to-clipboard button; the string is woven into the
  // button's label, e.g. "path" → "Copy path".
  copyLabel?: string;
  /**
   * Show the label exactly as given, rather than in the drawer's uppercase caption style.
   *
   * Opt-in because almost every label here is a fixed word this component chose — "Size",
   * "Storage class" — which the caption style suits. The exception is a user's own custom
   * metadata key, which is data: upper-casing it claims they named it something they did
   * not. Defaulting this on would restyle all twelve fixed labels to fix the one.
   */
  preserveLabelCase?: boolean;
};

/**
 * One labelled, read-only row in a details drawer (file metadata or folder).
 * Optionally trails a copy-to-clipboard button for the value.
 *
 * @example
 * <DetailField label="Key" value={file.key} copyLabel="key" />
 */
export function DetailField({label, value, copyLabel, preserveLabelCase = false}: Props) {
  return (
    <div className="border-b border-border-2 py-3 last:border-0">
      {/* The reset goes on an inner span, not beside `uppercase` on the `dt`: which of two
          competing classes wins on one element is Tailwind's emitted order to decide, and
          no test in this repo can observe `text-transform` under jsdom. */}
      <dt className={SECTION_CAPTION}>
        {preserveLabelCase ? <span className="normal-case tracking-normal">{label}</span> : label}
      </dt>
      <dd className="mt-1 flex items-start gap-2">
        <span className="min-w-0 flex-1 break-all text-sm text-text">{value}</span>
        {copyLabel && (
          <CopyButton
            value={value}
            label={copyLabel}
          />
        )}
      </dd>
    </div>
  );
}
