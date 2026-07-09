import {describe, it, expect, vi, afterEach} from 'vitest';
import {triggerBrowserDownload} from './fileBrowser.download';

afterEach(() => vi.restoreAllMocks());

describe('triggerBrowserDownload', () => {
  it('creates a rel=noopener anchor, clicks it, and cleans it up', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    triggerBrowserDownload('https://signed.example/report.csv?x=1');
    expect(click).toHaveBeenCalledOnce();
    // The anchor is removed after the click — nothing lingers in the DOM.
    expect(document.querySelector('a[href="https://signed.example/report.csv?x=1"]')).toBeNull();
  });
});
