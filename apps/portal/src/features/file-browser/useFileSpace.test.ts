import {describe, it, expect} from 'vitest';
import type {ReactNode} from 'react';
import {createElement} from 'react';
import {renderHook, act} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {useFileSpace} from './useFileSpace';
import type {Connection} from '../query/query.types';

const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
const marketing: Connection = {
  id: 'marketing_data',
  label: 'marketing_data',
  database: 'marketing_data',
  kind: 'shared',
  status: 'active',
  role: 'member'
};
const provisioning: Connection = {
  id: 'sales_2026',
  label: 'sales_2026',
  database: 'sales_2026',
  kind: 'shared',
  status: 'provisioning',
  role: 'owner'
};

const ALL = [personal, marketing, provisioning];

function setup(path: string, overrides: Partial<Parameters<typeof useFileSpace>[0]> = {}) {
  const wrapper = ({children}: {children: ReactNode}) =>
    createElement(MemoryRouter, {initialEntries: [path]}, children);
  return renderHook(
    () =>
      useFileSpace({
        username: 'alice',
        connections: ALL,
        isLoading: false,
        userSpaceBucket: 'user-bucket',
        sharedSpaceBucket: 'shared-bucket',
        ...overrides
      }),
    {wrapper}
  );
}

describe('useFileSpace (SPEC-057)', () => {
  it('defaults to the personal space when no ?space= is present', () => {
    const {result} = setup('/files');
    expect(result.current.activeSpaceId).toBe('personal');
    expect(result.current.space).toEqual({
      id: 'personal',
      bucket: 'user-bucket',
      rootPrefix: 'alice/',
      kind: 'personal',
      label: 'alice'
    });
    expect(result.current.fellBack).toBe(false);
  });

  it('targets a usable shared space from ?space=', () => {
    const {result} = setup('/files?space=marketing_data');
    expect(result.current.activeSpaceId).toBe('marketing_data');
    expect(result.current.space).toEqual({
      id: 'marketing_data',
      bucket: 'shared-bucket',
      rootPrefix: 'marketing_data/',
      kind: 'shared',
      label: 'marketing_data'
    });
    expect(result.current.fellBack).toBe(false);
  });

  it('falls back to personal with fellBack for an unknown ?space=', () => {
    const {result} = setup('/files?space=ghost');
    expect(result.current.space?.kind).toBe('personal');
    expect(result.current.fellBack).toBe(true);
  });

  it('falls back to personal for a not-yet-usable (provisioning) ?space=', () => {
    const {result} = setup('/files?space=sales_2026');
    expect(result.current.space?.kind).toBe('personal');
    expect(result.current.fellBack).toBe(true);
  });

  it('suppresses the fellBack notice while connections are still loading', () => {
    const {result} = setup('/files?space=ghost', {isLoading: true});
    expect(result.current.space?.kind).toBe('personal');
    expect(result.current.fellBack).toBe(false);
  });

  it('selectSpace switches the active space', () => {
    const {result} = setup('/files');
    act(() => result.current.selectSpace('marketing_data'));
    expect(result.current.activeSpaceId).toBe('marketing_data');
    expect(result.current.space?.bucket).toBe('shared-bucket');
  });

  it('selecting personal clears the ?space= param', () => {
    const {result} = setup('/files?space=marketing_data');
    expect(result.current.activeSpaceId).toBe('marketing_data');
    act(() => result.current.selectSpace('personal'));
    expect(result.current.activeSpaceId).toBe('personal');
    expect(result.current.fellBack).toBe(false);
  });

  it('dismissFellBack clears the stale space and the notice', () => {
    const {result} = setup('/files?space=ghost');
    expect(result.current.fellBack).toBe(true);
    act(() => result.current.dismissFellBack());
    expect(result.current.fellBack).toBe(false);
    expect(result.current.space?.kind).toBe('personal');
  });

  it('returns a null space when there is no username (dev/no-auth)', () => {
    const {result} = setup('/files', {username: null});
    expect(result.current.space).toBeNull();
  });

  it('returns a null space when the shared bucket is unconfigured', () => {
    const {result} = setup('/files?space=marketing_data', {sharedSpaceBucket: undefined});
    expect(result.current.space).toBeNull();
  });
});
