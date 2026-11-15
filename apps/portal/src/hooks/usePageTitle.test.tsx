import {Suspense, lazy, useEffect, useState, type ReactNode} from 'react';
import {act, render, screen} from '@testing-library/react';
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

  it('leaves the view’s title alone when a boundary above hides the page and shows it again', async () => {
    let arrive: () => void = () => undefined;
    const Late = lazy(
      () =>
        new Promise<{default: () => null}>((resolve) => {
          arrive = () => resolve({default: () => null});
        })
    );
    const control = {suspend: (): void => undefined};
    function Suspender() {
      const [suspended, setSuspended] = useState(false);
      useEffect(() => {
        control.suspend = () => setSuspended(true);
      }, []);
      return suspended ? <Late /> : null;
    }
    render(
      <Suspense fallback={<p>Loading</p>}>
        <Page>
          <Suspender />
          <View title="Notifications (3)" />
        </Page>
      </Suspense>
    );
    act(() => control.suspend());
    expect(screen.getByText('Loading')).toBeInTheDocument();

    await act(async () => arrive());

    expect(screen.queryByText('Loading')).not.toBeInTheDocument();
    expect(document.title).toBe('Notifications (3) — Data Quarry');
  });
});
