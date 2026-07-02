import {forwardRef} from 'react';
import {cx} from '../lib/cx';

type IconButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: 'sm' | 'md';
  /** Applied as aria-label — the accessible name (the icon child is decorative). */
  label: string;
};

const BASE =
  'inline-flex items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text disabled:opacity-45 disabled:cursor-not-allowed transition-colors';

const SIZES = {sm: 'h-7 w-7', md: 'h-8 w-8'} as const;

/**
 * Ghost icon-only button — close buttons, row actions. Pass the icon as the
 * child; the required `label` supplies the accessible name. Forwards all
 * native `<button>` attributes and a ref.
 *
 * @example
 * <IconButton label="Close panel" onClick={onClose}>
 *   <CloseIcon className="h-4 w-4" />
 * </IconButton>
 */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({size = 'md', label, className, type, ...rest}, ref) => (
    <button
      ref={ref}
      type={type ?? 'button'}
      aria-label={label}
      className={cx(BASE, SIZES[size], className)}
      {...rest}
    />
  )
);

IconButton.displayName = 'IconButton';
