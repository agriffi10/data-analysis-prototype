import {exceedsAthenaQueryLimit} from './athenaLimit';

/**
 * The one line a Data Explorer save appends to a `.sql` file, and how to read it back.
 *
 * A comment, so the file is still a statement Query and Athena run unchanged. Its payload is
 * base64url over UTF-8, so the line holds no quote, semicolon, `*` + `/` or newline for any SQL
 * lexer to trip on. This module knows the FORMAT and nothing of what the payload means: that is
 * the Data Explorer's, which is why the payload is `unknown` here.
 *
 * The checksum covers the SQL above the line and detects an edit made in good faith — a file
 * changed in Query after it was saved. It is not a signature: whoever can write the file can
 * write a matching line, so what the payload describes is validated like any stored document.
 */
export const VIEW_LINE_MARKER = '-- dataquarry-view:';

/** The only line version this build writes or reads. */
export const VIEW_LINE_VERSION = 1;

const V1_BODY_RE = /^([0-9a-f]{8}):([A-Za-z0-9_-]*)$/;
const VERSION_RE = /^v(\d+):/;
const BASE64URL_RE = /^[A-Za-z0-9_-]*$/;

/**
 * What a file's text says about its view line. `sql` is always the text without the view line,
 * trailing whitespace trimmed, which is what **Open in Query** hands over.
 */
export type ParsedViewLine =
  | {kind: 'none'; sql: string}
  | {kind: 'newer'; sql: string; version: number}
  | {kind: 'edited'; sql: string}
  | {kind: 'damaged'; sql: string}
  | {kind: 'ok'; sql: string; version: 1; payload: unknown};

/** Drops a leading byte-order mark and turns CRLF into LF, so an editor's habits are not edits. */
function normalizeText(text: string): string {
  return (text.startsWith('\uFEFF') ? text.slice(1) : text).replace(/\r\n/g, '\n');
}

/**
 * FNV-1a 32-bit over the UTF-8 bytes of `sql`, as 8 lowercase hex digits.
 *
 * Normalised first — byte-order mark, CRLF, trailing whitespace — because those change when a
 * file passes through another editor without anyone changing the statement.
 *
 * @param sql - The statement the line sits under.
 * @returns The checksum.
 */
export function viewChecksum(sql: string): string {
  const bytes = new TextEncoder().encode(normalizeText(sql).trimEnd());
  let hash = 0x811c9dc5;
  for (const byte of bytes) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

function toBase64Url(text: string): string {
  let binary = '';
  for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(value: string): string | null {
  if (!BASE64URL_RE.test(value)) return null;
  try {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (value.length % 4)) % 4);
    const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
    return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
  } catch {
    return null;
  }
}

/**
 * The file body a save writes: the statement, then the view line.
 *
 * @param sql - The statement that ran.
 * @param payload - What the line records; serialised as JSON.
 * @returns `{sql}\n{line}\n`, or null when that would be too long for Athena to run, in which
 *   case the caller writes the statement alone.
 */
export function appendViewLine(sql: string, payload: unknown): string | null {
  const line = `${VIEW_LINE_MARKER}v${VIEW_LINE_VERSION}:${viewChecksum(sql)}:${toBase64Url(JSON.stringify(payload))}`;
  const body = `${sql}\n${line}\n`;
  return exceedsAthenaQueryLimit(body) ? null : body;
}

/**
 * Reads a file's view line.
 *
 * Only the LAST non-blank line can be one: the statement above it may itself hold a line that
 * starts like the marker, inside a multi-line literal. A marker line anywhere else means text was
 * added after it, which is an edit.
 *
 * @param text - The file's whole text.
 * @returns What the line says, and the text without it.
 */
export function parseViewLine(text: string): ParsedViewLine {
  const lines = normalizeText(text).split('\n');
  let last = lines.length - 1;
  while (last >= 0 && lines[last].trim() === '') last -= 1;
  const without = (index: number) =>
    lines
      .filter((_, i) => i !== index)
      .join('\n')
      .trimEnd();

  if (last < 0 || !lines[last].trim().startsWith(VIEW_LINE_MARKER)) {
    let marker = -1;
    for (let i = last - 1; i >= 0; i -= 1) {
      if (lines[i].startsWith(VIEW_LINE_MARKER)) {
        marker = i;
        break;
      }
    }
    return marker === -1 ? {kind: 'none', sql: without(-1)} : {kind: 'edited', sql: without(marker)};
  }

  const sql = without(last);
  const rest = lines[last].trim().slice(VIEW_LINE_MARKER.length);
  const version = VERSION_RE.exec(rest);
  if (!version) return {kind: 'damaged', sql};
  if (Number(version[1]) !== VIEW_LINE_VERSION) return {kind: 'newer', sql, version: Number(version[1])};
  const body = V1_BODY_RE.exec(rest.slice(version[0].length));
  if (!body) return {kind: 'damaged', sql};
  if (body[1] !== viewChecksum(sql)) return {kind: 'edited', sql};

  const json = fromBase64Url(body[2]);
  let payload: unknown = undefined;
  if (json !== null) {
    try {
      payload = JSON.parse(json);
    } catch {
      payload = undefined;
    }
  }
  return {kind: 'ok', sql, version: VIEW_LINE_VERSION, payload};
}
