// Shared S3 key/prefix path helpers.

/** Leaf (last segment) of a file key: `a/b/c.txt` → `c.txt`. */
export function leafName(key: string): string {
  const i = key.lastIndexOf('/');
  return i === -1 ? key : key.slice(i + 1);
}

/** Parent prefix of a file key: `a/b/c.txt` → `a/b/`, `c.txt` → ``. */
export function fileParent(key: string): string {
  const i = key.lastIndexOf('/');
  return i === -1 ? '' : key.slice(0, i + 1);
}

/**
 * Parent prefix + leaf name of a folder prefix:
 * `a/b/photos/` → `{ parent: 'a/b/', leaf: 'photos' }`.
 */
export function folderParts(prefix: string): {parent: string; leaf: string} {
  const trimmed = prefix.replace(/\/$/, '');
  const i = trimmed.lastIndexOf('/');
  return i === -1 ? {parent: '', leaf: trimmed} : {parent: trimmed.slice(0, i + 1), leaf: trimmed.slice(i + 1)};
}

/**
 * Path shown to the user: a key or prefix with the user-root prefix stripped,
 * so the raw root segment (e.g. the username) is never surfaced.
 */
export function relativePath(keyOrPrefix: string, rootPrefix?: string): string {
  return rootPrefix && keyOrPrefix.startsWith(rootPrefix) ? keyOrPrefix.slice(rootPrefix.length) : keyOrPrefix;
}

/**
 * Last path segment of a key OR folder prefix (trailing slash tolerated), for
 * naming items in result messages: `a/b/photos/` → `photos`, `a/b/c.txt` → `c.txt`.
 */
export function lastSegment(keyOrPrefix: string): string {
  return keyOrPrefix.replace(/\/$/, '').split('/').pop() ?? keyOrPrefix;
}

/**
 * Uppercased file extension for a type chip, e.g. `report.pdf` → `PDF`. Returns
 * `fallback` when there's no extension; `maxLen` caps the chip width.
 */
export function fileExtension(name: string, opts?: {fallback?: string; maxLen?: number}): string {
  const fallback = opts?.fallback ?? 'File';
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return fallback;
  const ext = name.slice(dot + 1).toUpperCase();
  return opts?.maxLen ? ext.slice(0, opts.maxLen) : ext;
}
