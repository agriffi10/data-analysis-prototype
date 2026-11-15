import type {ReactNode} from 'react';
import {render} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {usePageTitle, usePageTitleOnMount} from './usePageTitle';

function Page({children}: {children?: ReactNode}) {
  usePageTitleOnMount('Notifications');
  return <>{children}</>;
}

function View({title}: {title: string}) {
  usePageTitle(title);
  return null;
}

beforeEach(() => {
  document.title = 'Files — Data Quarry';
});

describe('usePageTitleOnMount', () => {
  it('sets the page’s title as it mounts', () => {
    render(<Page />);

    expect(document.title).toBe('Notifications — Data Quarry');
  });

  it('never overwrites a title its view sets in the same commit', () => {
    render(
      <Page>
        <View title="Notifications (3)" />
      </Page>
    );

    expect(document.title).toBe('Notifications (3) — Data Quarry');
  });
});
