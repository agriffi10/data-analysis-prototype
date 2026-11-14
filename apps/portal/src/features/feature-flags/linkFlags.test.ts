import {describe, expect, it} from 'vitest';
import {linkFlags} from './linkFlags';

describe('linkFlags', () => {
  it.each([
    ['/files?prefix=alice/reports/', ['files']],
    ['/files?space=personal&prefix=alice/', ['files']],
    ['/files?prefix=x/&space=finance', ['files', 'sharedWorkspaces']],
    // `/files` spells the personal space as the literal only; a username there names nothing it can resolve.
    ['/files?space=alice', ['files', 'sharedWorkspaces']],
    ['/explore?space=alice&db=alice&table=sales', ['dataExplorer']],
    ['/explore?space=personal', ['dataExplorer']],
    ['/explore?space=finance&db=finance&table=sales', ['dataExplorer', 'sharedWorkspaces']],
    ['/query', ['query']],
    ['/query?refreshTable=alice.sales&removed=id', ['query']],
    ['/query?refreshTable=finance.sales&removed=id', ['query', 'sharedWorkspaces']],
    ['/data-quality', ['dataQuality']],
    ['/data-quality/alice/req-1', ['dataQuality']],
    ['/data-quality/finance/req-1', ['dataQuality', 'sharedWorkspaces']],
    ['/connections', ['sharedWorkspaces']],
    ['/help#files', []],
    ['/notifications', []],
    ['/filesystem', []],
    // Matched case-sensitively, as Next routes: `/Files` is no page, so it names no flag.
    ['/Files?space=finance', []]
  ])('%s needs %j', (link, expected) => {
    expect(linkFlags(link, 'alice').sort()).toEqual([...expected].sort());
  });

  it('treats every named space as shared when there is no viewer to be personal', () => {
    expect(linkFlags('/data-quality/alice/req-1', null).sort()).toEqual(['dataQuality', 'sharedWorkspaces']);
  });
});
