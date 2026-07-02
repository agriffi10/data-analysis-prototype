import {cx} from '../lib/cx';
import {UploadIcon} from './icons';

type BrandMarkProps = {
  /** 'sm' = 24px square + text-base; 'md' (default) = 32px square + text-md. */
  size?: 'sm' | 'md';
  /** Render the "S3 File Portal" text next to the square; default true. */
  showWordmark?: boolean;
  className?: string;
};

/**
 * App brand mark — rounded accent square with an upload-arrow icon plus the
 * "S3 File Portal" wordmark. Shared by the Header and the landing page.
 *
 * @example
 * <BrandMark size="sm" showWordmark={false} />
 */
export function BrandMark({size = 'md', showWordmark = true, className}: BrandMarkProps) {
  const square = size === 'sm' ? 'h-6 w-6' : 'h-8 w-8';
  const icon = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4';
  const wordmark = size === 'sm' ? 'text-base' : 'text-md';

  return (
    <div className={cx('flex items-center gap-2', className)}>
      <div className={cx('flex shrink-0 items-center justify-center rounded-md bg-accent', square)}>
        <UploadIcon className={cx(icon, 'text-white')} />
      </div>
      {showWordmark && <span className={cx(wordmark, 'font-semibold text-text')}>S3 File Portal</span>}
    </div>
  );
}
