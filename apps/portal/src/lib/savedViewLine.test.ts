import {describe, expect, it} from 'vitest';
import {ATHENA_QUERY_STRING_MAX} from './athenaLimit';
import {appendViewLine, parseViewLine, VIEW_LINE_MARKER, viewChecksum} from './savedViewLine';

const SQL = 'SELECT *\nFROM "alice"."orders"\nWHERE (region = \'west\')';
const PAYLOAD = {source: {database: 'alice', table: 'orders'}, note: 'naïve – ünïcode'};
const BOM = String.fromCharCode(0xfeff);
const saved = appendViewLine(SQL, PAYLOAD) as string;
const line = saved.split('\n').at(-2) as string;

describe('parseViewLine', () => {
  it.each([
    ['a file saved by this build', saved, {kind: 'ok', sql: SQL, version: 1, payload: PAYLOAD}],
    ['a file with no view line', `${SQL}\n`, {kind: 'none', sql: SQL}],
    ['SQL added after the line', `${saved}SELECT 1\n`, {kind: 'edited', sql: `${SQL}\nSELECT 1`}],
    ['SQL changed above the line', saved.replace('west', 'east'), {kind: 'edited', sql: SQL.replace('west', 'east')}],
    [
      'a newer line',
      saved.replace(`${VIEW_LINE_MARKER}v1:`, `${VIEW_LINE_MARKER}v2:`),
      {kind: 'newer', sql: SQL, version: 2}
    ],
    ['a line with no version', `${SQL}\n${VIEW_LINE_MARKER}garbage\n`, {kind: 'damaged', sql: SQL}],
    ['a newer line shaped differently', `${SQL}\n${VIEW_LINE_MARKER}v2\n`, {kind: 'newer', sql: SQL, version: 2}],
    [
      'a version with a leading zero',
      saved.replace(`${VIEW_LINE_MARKER}v1:`, `${VIEW_LINE_MARKER}v01:`),
      {kind: 'damaged', sql: SQL}
    ],
    ['a v1 line missing its checksum', `${SQL}\n${VIEW_LINE_MARKER}v1:e30\n`, {kind: 'damaged', sql: SQL}],
    [
      'a payload that is not JSON',
      `${SQL}\n${VIEW_LINE_MARKER}v1:${viewChecksum(SQL)}:bm90IGpzb24\n`,
      {kind: 'ok', sql: SQL, version: 1, payload: undefined}
    ],
    ['CRLF line endings', saved.replace(/\n/g, '\r\n'), {kind: 'ok', sql: SQL, version: 1, payload: PAYLOAD}],
    ['a byte-order mark', `${BOM}${saved}`, {kind: 'ok', sql: SQL, version: 1, payload: PAYLOAD}],
    [
      'trailing whitespace after the SQL and on the line',
      `${SQL}  \n\n${line}   \n\n`,
      {kind: 'ok', sql: SQL, version: 1, payload: PAYLOAD}
    ]
  ])('%s', (_label, text, expected) => {
    expect(parseViewLine(text)).toEqual(expected);
  });

  it('reads only the last line, so a marker-shaped line inside the SQL does not disturb it', () => {
    const tricky = `SELECT *\nFROM "alice"."t"\nWHERE "note" = 'a\n${VIEW_LINE_MARKER}v1:00000000:e30'`;

    expect(parseViewLine(appendViewLine(tricky, PAYLOAD) as string)).toEqual({
      kind: 'ok',
      sql: tricky,
      version: 1,
      payload: PAYLOAD
    });
  });
});

describe('appendViewLine', () => {
  it('writes the line only while the whole file stays within what Athena will run', () => {
    const overhead = (appendViewLine('', {}) as string).length;
    const fits = 'x'.repeat(ATHENA_QUERY_STRING_MAX - overhead);
    const over = `${fits}x`;

    expect(appendViewLine(fits, {})).toHaveLength(ATHENA_QUERY_STRING_MAX);
    expect(appendViewLine(over, {})).toBeNull();
  });
});
