'use client';
import type {CSSProperties, ReactNode} from 'react';
import {Link, type LinkProps} from './Link';
import {normalizePathname, resolveTo} from './address';
import {useSeam} from './seamContext';

type ActiveState = {isActive: boolean};

export type NavLinkProps = Omit<LinkProps, 'className' | 'children' | 'style'> & {
  className?: string | ((state: ActiveState) => string | undefined);
  children?: ReactNode | ((state: ActiveState) => ReactNode);
  style?: CSSProperties | ((state: ActiveState) => CSSProperties | undefined);
  /** Active only on the exact path, not beneath it. */
  end?: boolean;
};

/**
 * A `Link` that knows whether it points at the current page, as react-router's does: active on its
 * path and, unless `end`, beneath it at a segment boundary; `aria-current="page"` when active; and
 * `className`, `style` and `children` may each be a function of `{isActive}`. Matched
 * case-sensitively, as Next routes.
 *
 * @returns The link.
 *
 * @example
 * <NavLink to="/files" className={({isActive}) => (isActive ? 'on' : 'off')}>Files</NavLink>
 */
export function NavLink({className, children, style, end = false, ...props}: NavLinkProps) {
  const {location} = useSeam();
  const here = normalizePathname(location.pathname);
  const target = resolveTo(props.to, location).pathname;
  const isActive =
    here === target || (!end && target !== '/' && here.startsWith(target) && here.charAt(target.length) === '/');
  const state = {isActive};
  return (
    <Link
      aria-current={isActive ? 'page' : undefined}
      {...props}
      className={typeof className === 'function' ? className(state) : className}
      style={typeof style === 'function' ? style(state) : style}>
      {typeof children === 'function' ? children(state) : children}
    </Link>
  );
}
