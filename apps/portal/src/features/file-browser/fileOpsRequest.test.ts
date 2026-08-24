import {describe, expect, it} from 'vitest';
import {buildFileOpRequest, buildResubmitRequest, containingFolder, itemLabel, toFileOpItems} from './fileOps.request';
import {itemResultsFromPayload, outcomeHeading} from './fileOps.outcomes';
import type {FileOpItemResult, FileOpOutcome, FileOpSpace} from './fileOps.types';
import type {NotificationPayload} from '../notifications';

const ALICE: FileOpSpace = {kind: 'personal', name: 'alice'};
const IDS = {requestId: 'req-1', submittedAt: '2026-08-23T10:00:00.000Z'};

describe('toFileOpItems', () => {
  it('keeps a folder’s trailing slash', () => {
    // Not cosmetic: the plane expands a folder by LISTING the prefix, so `alice/report` would
    // match `alice/reports/` as well.
    expect(toFileOpItems([{type: 'folder', prefix: 'alice/reports/'}])).toEqual([
      {kind: 'folder', key: 'alice/reports/'}
    ]);
  });

  it('omits targetName entirely rather than sending an empty one', () => {
    // The plane REFUSES an empty string — it derives to the destination prefix itself, merging a
    // folder's contents into the destination and then, for a move, deleting the source.
    expect(toFileOpItems([{type: 'file', key: 'alice/a.csv'}], '')).toEqual([{kind: 'file', key: 'alice/a.csv'}]);
  });
});

describe('containingFolder + itemLabel', () => {
  it('finds the parent of a file and of a folder', () => {
    expect(containingFolder({type: 'file', key: 'alice/docs/a.csv'})).toBe('alice/docs/');
    expect(containingFolder({type: 'folder', prefix: 'alice/docs/notes/'})).toBe('alice/docs/');
  });

  it('names an item by its leaf', () => {
    expect(itemLabel({type: 'file', key: 'alice/docs/a.csv'})).toBe('a.csv');
    expect(itemLabel({type: 'folder', prefix: 'alice/docs/notes/'})).toBe('notes');
  });
});

describe('buildFileOpRequest', () => {
  it('sends a delete with NO destination, NO onConflict and NO submittedAt', () => {
    // The plane rejects unknown top-level fields and rejects `onConflict` on a delete outright, so
    // sending them unconditionally refuses every delete at the front door.
    const request = buildFileOpRequest({operation: 'delete', items: [{type: 'file', key: 'alice/a.csv'}]}, ALICE, IDS);
    expect(Object.keys(request).sort()).toEqual(['operation', 'requestId', 'source']);
    // And true of the VALUE that goes on the wire, not only of its key list.
    const wire = JSON.parse(JSON.stringify(request));
    expect(wire).not.toHaveProperty('destination');
    expect(wire).not.toHaveProperty('onConflict');
    expect(wire).not.toHaveProperty('submittedAt');
  });

  it('sends a rename as the containing folder plus a targetName', () => {
    const request = buildFileOpRequest(
      {
        operation: 'move',
        items: [{type: 'folder', prefix: 'alice/docs/notes/'}],
        destination: {space: ALICE, prefix: 'alice/docs/'},
        targetName: 'archive'
      },
      ALICE,
      IDS
    );
    expect(request).toMatchObject({
      operation: 'move',
      destination: {prefix: 'alice/docs/'},
      onConflict: 'refuse',
      submittedAt: IDS.submittedAt,
      source: {items: [{kind: 'folder', key: 'alice/docs/notes/', targetName: 'archive'}]}
    });
  });

  it('sends a multi-item move as the chosen destination with NO targetName', () => {
    const request = buildFileOpRequest(
      {
        operation: 'move',
        items: [
          {type: 'file', key: 'alice/a.csv'},
          {type: 'folder', prefix: 'alice/docs/'}
        ],
        destination: {space: {kind: 'shared', name: 'finance'}, prefix: 'finance/in/'}
      },
      ALICE,
      IDS
    );
    expect(request.operation !== 'delete' && request.destination).toEqual({
      space: {kind: 'shared', name: 'finance'},
      prefix: 'finance/in/'
    });
    expect(request.source.items.every((item) => item.targetName === undefined)).toBe(true);
  });

  it('defaults onConflict to refuse, and carries overwrite only when asked', () => {
    const gesture = {
      operation: 'copy' as const,
      items: [{type: 'file' as const, key: 'alice/a.csv'}],
      destination: {space: ALICE, prefix: 'alice/out/'}
    };
    expect(buildFileOpRequest(gesture, ALICE, IDS)).toMatchObject({onConflict: 'refuse'});
    expect(buildFileOpRequest({...gesture, onConflict: 'overwrite'}, ALICE, IDS)).toMatchObject({
      onConflict: 'overwrite'
    });
  });

  it('refuses a copy with no destination rather than sending one the plane will reject', () => {
    expect(() =>
      buildFileOpRequest({operation: 'copy', items: [{type: 'file', key: 'alice/a.csv'}]}, ALICE, IDS)
    ).toThrow(/destination/);
  });
});

describe('buildResubmitRequest', () => {
  const payload: NotificationPayload = {
    requestId: 'first',
    operation: 'move',
    source: {kind: 'shared', name: 'finance'},
    destination: {kind: 'personal', name: 'alice', prefix: 'alice/out/'},
    conflicts: [{itemKey: 'finance/q1.csv', kind: 'file', targetName: 'q1.csv'}]
  };

  it('takes BOTH spaces from the payload, never from wherever the reader is standing', () => {
    // The control's href falls back to a bare `/files` when the row carries no usable prefix, and
    // that page resolves the reader's PERSONAL space — so a source taken from the mount would
    // hash to the wrong FIFO group and be refused for a space the items were never in.
    const request = buildResubmitRequest(
      payload,
      {requestId: 'req-2', submittedAt: 'later'},
      {
        onConflict: 'overwrite'
      }
    );
    expect(request?.source.space).toEqual({kind: 'shared', name: 'finance'});
    expect(request?.operation !== 'delete' && request?.destination).toEqual({
      space: {kind: 'personal', name: 'alice'},
      prefix: 'alice/out/'
    });
  });

  it('re-sends ONLY the conflicted items, with a new id and a fresh submittedAt', () => {
    const request = buildResubmitRequest(
      payload,
      {requestId: 'req-2', submittedAt: 'later'},
      {
        onConflict: 'overwrite'
      }
    );
    expect(request?.requestId).toBe('req-2');
    expect(request?.operation !== 'delete' && request?.submittedAt).toBe('later');
    expect(request?.source.items).toEqual([{kind: 'file', key: 'finance/q1.csv', targetName: 'q1.csv'}]);
  });

  it('a chosen new name re-submits as a REFUSE, which destroys nothing', () => {
    const request = buildResubmitRequest(
      payload,
      {requestId: 'req-3', submittedAt: 'later'},
      {onConflict: 'refuse', targetName: 'q1-v2.csv'}
    );
    expect(request?.operation !== 'delete' && request?.onConflict).toBe('refuse');
    expect(request?.source.items[0].targetName).toBe('q1-v2.csv');
  });

  it('infers a kind from the key when the payload lost one', () => {
    // Omitting it is the unsafe option: the plane derives a folder's destination by listing the
    // prefix, so a folder sent as a file plants a zero-byte object where the folder should be.
    const request = buildResubmitRequest(
      {...payload, conflicts: [{itemKey: 'finance/reports/'}]},
      {requestId: 'r', submittedAt: 's'},
      {onConflict: 'overwrite'}
    );
    expect(request?.source.items[0].kind).toBe('folder');
  });

  it('answers nothing for a payload that cannot describe a request', () => {
    const ids = {requestId: 'r', submittedAt: 's'};
    expect(buildResubmitRequest({requestId: 'x'}, ids, {onConflict: 'overwrite'})).toBeUndefined();
    expect(buildResubmitRequest({...payload, operation: 'delete'}, ids, {onConflict: 'overwrite'})).toBeUndefined();
    expect(buildResubmitRequest({...payload, conflicts: []}, ids, {onConflict: 'overwrite'})).toBeUndefined();
    // A space whose `kind` is not one of the two: the field is a bare string on the wire.
    expect(
      buildResubmitRequest({...payload, source: {kind: 'nonsense', name: 'x'}}, ids, {onConflict: 'overwrite'})
    ).toBeUndefined();
  });
});

describe('itemResultsFromPayload', () => {
  it('labels a conflicted item by its targetName, else by its leaf', () => {
    const results = itemResultsFromPayload({
      requestId: 'r',
      conflicts: [
        {itemKey: 'alice/a/b.csv'},
        {itemKey: 'alice/a/c.csv', targetName: 'renamed.csv', sample: ['b.csv'], more: true}
      ]
    });
    expect(results.map((r) => r.label)).toEqual(['b.csv', 'renamed.csv']);
    expect(results.every((r) => r.outcome === 'conflict')).toBe(true);
    expect(results[1]).toMatchObject({sample: ['b.csv'], more: true});
  });

  it('answers with nothing for a payload carrying no conflicts', () => {
    expect(itemResultsFromPayload(undefined)).toEqual([]);
    expect(itemResultsFromPayload({requestId: 'r'})).toEqual([]);
  });
});

describe('the outcome vocabulary', () => {
  it('has a heading for every member, and the browser invents none', () => {
    // The vocabulary is the plane's (`focommon.outcomes`). A member with no heading would render
    // as an empty group title; a heading with no member would be a browser-invented outcome.
    const outcomes: FileOpOutcome[] = [
      'cleared',
      'conflict',
      'noop',
      'source_missing',
      'source_empty',
      'protected',
      'copy_failed',
      'delete_failed',
      'duplicate',
      'refused',
      'moved',
      'copied',
      'deleted'
    ];
    for (const outcome of outcomes) expect(outcomeHeading(outcome)).toBeTruthy();
  });

  it('renders a mixed run as more than a success/failure binary', () => {
    // The shape `{count, errors}` cannot express: a `noop` is neither, and a `duplicate` put the
    // data where it was asked to.
    const results: FileOpItemResult[] = [
      {itemKey: 'a', label: 'a', outcome: 'moved'},
      {itemKey: 'b', label: 'b', outcome: 'noop'},
      {itemKey: 'c', label: 'c', outcome: 'protected'},
      {itemKey: 'd', label: 'd', outcome: 'conflict'}
    ];
    expect(new Set(results.map((r) => outcomeHeading(r.outcome))).size).toBe(4);
  });
});
