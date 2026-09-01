import {cx} from '../lib/cx';
import {DatabaseIcon} from './icons';

type BrandMarkProps = {
  /** 'sm' = an `h-6` square + text-base; 'md' (default) = an `h-8` square + text-md. */
  size?: 'sm' | 'md';
  /** Render the "Data Workspace" text next to the square; default true. */
  showWordmark?: boolean;
  className?: string;
};

/**
 * App brand mark — rounded accent square with a database icon plus the
 * "Data Workspace" wordmark. Shared by the Header and the landing page.
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
        <DatabaseIcon className={cx(icon, 'text-white')} />
      </div>
      {showWordmark && <span className={cx(wordmark, 'font-semibold text-text')}>Data Workspace</span>}
    </div>
  );
}
