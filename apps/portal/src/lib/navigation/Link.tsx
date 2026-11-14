'use client';
import type {AnchorHTMLAttributes, MouseEvent} from 'react';
import {committedAddress, hrefOf, isRefusedTarget, resolveTo} from './address';
import {useSeam} from './seamContext';
import type {To} from './navigation.types';

export type LinkProps = {to: To; replace?: boolean; state?: unknown} & Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  'href'
>;

/**
 * A plain anchor; a primary click with no modifier, and no other `target`, navigates through the
 * seam. Following a link to the address already shown is a replace, as react-router's is.
 *
 * A target outside the portal renders no `href` and a click goes nowhere: a link to another site is
 * authored as a plain `<a>`, never through the seam.
 *
 * @param props.to - Where the link goes.
 * @param props.replace - Replace the current entry rather than push; defaults to whether `to` is
 *   the address already shown.
 * @param props.state - What the navigation carries to the destination's first render.
 * @returns The anchor.
 *
 * @example
 * <Link to="/help#files">Help</Link>
 */
export function Link({to, replace, state, onClick, target, ...rest}: LinkProps) {
  const {location, navigate} = useSeam();
  const offSite = isRefusedTarget(to, location);

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
    if (target && target !== '_self') return;
    event.preventDefault();
    if (offSite) {
      navigate(to);
      return;
    }
    const here = committedAddress();
    navigate(to, {replace: replace ?? hrefOf(resolveTo(to, here)) === hrefOf(here), state});
  };

  return (
    <a
      {...rest}
      target={target}
      href={offSite ? undefined : hrefOf(resolveTo(to, location))}
      onClick={handleClick}
    />
  );
}
