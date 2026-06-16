import { cx } from '../lib/cx';

type BrandMarkProps = {
  size?: 'sm' | 'md'; // sm = 24px square + text-base; md = 32px square + text-md (default)
  showWordmark?: boolean; // default true
  className?: string;
};

// Brand mark (SPEC-028) — the rounded accent square with a white upload-arrow
// icon plus the "S3 File Portal" wordmark. Shared by Header (SPEC-023) and
// LandingPage (SPEC-022).
export function BrandMark({
  size = 'md',
  showWordmark = true,
  className,
}: BrandMarkProps) {
  const square = size === 'sm' ? 'h-6 w-6' : 'h-8 w-8';
  const icon = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4';
  const wordmark = size === 'sm' ? 'text-base' : 'text-md';

  return (
    <div className={cx('flex items-center gap-2', className)}>
      <div
        className={cx(
          'flex flex-shrink-0 items-center justify-center rounded-md bg-accent',
          square,
        )}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={cx(icon, 'text-white')}
          aria-hidden="true"
        >
          <path d="M12 16V4M7 9l5-5 5 5" />
          <path d="M5 20h14" />
        </svg>
      </div>
      {showWordmark && (
        <span className={cx(wordmark, 'font-semibold text-text')}>
          S3 File Portal
        </span>
      )}
    </div>
  );
}
