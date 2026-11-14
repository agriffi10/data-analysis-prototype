'use client';
import {useEffect} from 'react';
import {toHref} from './address';
import {useSeam} from './seamContext';
import type {To} from './navigation.types';

/**
 * Navigates from an effect once rendered, as react-router's does: a declarative redirect.
 *
 * @param props.to - Where to go.
 * @param props.replace - Replace the current entry rather than push.
 * @returns Nothing.
 *
 * @example
 * if (status === 'unauthenticated') return <Navigate to="/" replace />;
 */
export function Navigate({to, replace}: {to: To; replace?: boolean}): null {
  const {navigate} = useSeam();
  const target = toHref(to);
  useEffect(() => {
    navigate(target, {replace});
  }, [navigate, target, replace]);
  return null;
}
