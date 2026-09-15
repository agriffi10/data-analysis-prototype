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
 * Whether every segment of a key or prefix is a name — none empty, none `.` or `..`.
 *
 * S3 resolves neither: `alice//docs/` is a different folder from `alice/docs/` that the
 * breadcrumbs render identically, and `alice/../bob/` names a folder the API refuses outright.
 * One trailing slash is the folder boundary, not an empty segment.
 */
export function isNamedPath(keyOrPrefix: string): boolean {
  return keyOrPrefix
    .replace(/\/$/, '')
    .split('/')
    .every((segment) => segment !== '' && segment !== '.' && segment !== '..');
}

/**
 * Last path segment of a key OR folder prefix (trailing slash tolerated), for
 * naming items in result messages: `a/b/photos/` → `photos`, `a/b/c.txt` → `c.txt`.
 */
export function lastSegment(keyOrPrefix: string): string {
  return keyOrPrefix.replace(/\/$/, '').split('/').pop() ?? keyOrPrefix;
}

/**
 * Whether `currentPrefix` is the space root — the point at which the parent-folder
 * (`..`) row is hidden. `rootPrefix` is the navigation floor (personal
 * `{username}/`, a shared space's root prefix, or `''` when unclamped).
 */
export function isAtRoot(currentPrefix: string, rootPrefix: string): boolean {
  return currentPrefix === rootPrefix;
}

/**
 * Immediate parent of `currentPrefix` (its last path segment dropped), never above
 * the space root: `alice/docs/reports/` → `alice/docs/`, and one level below root →
 * `rootPrefix`. Used to navigate up from the `..` row.
 */
export function parentPrefix(currentPrefix: string, rootPrefix: string): string {
  const trimmed = currentPrefix.replace(/\/$/, '');
  const i = trimmed.lastIndexOf('/');
  const parent = i === -1 ? '' : trimmed.slice(0, i + 1);
  // Clamp: never step above the space root (ancestry-aware, not just length).
  if (rootPrefix && (parent.length < rootPrefix.length || !parent.startsWith(rootPrefix))) return rootPrefix;
  return parent;
}

/**
 * Chip labels for extensions whose raw uppercase form reads as noise — the
 * compression suffixes, where `foo.tar.gz` would otherwise chip as a bare `GZ`.
 * Keyed on the lowercased extension. They all read `ZIP`: the chip answers "what
 * kind of thing is this", and *compressed* is the answer a user acts on — the
 * particular codec is not, and naming it (`GZIP` vs `ZSTD`) reads as a
 * distinction that matters here when it doesn't. Keep every value to **4
 * characters or fewer**: the upload list chips at `maxLen: 4`, and a label that
 * truncates is worse than the raw extension this map exists to replace.
 */
const EXTENSION_LABELS: Record<string, string> = {
  gz: 'ZIP',
  gzip: 'ZIP',
  tgz: 'ZIP',
  bz2: 'ZIP',
  tbz2: 'ZIP',
  xz: 'ZIP',
  zst: 'ZIP',
  '7z': 'ZIP'
};

/**
 * Uppercased file extension for a type chip, e.g. `report.pdf` → `PDF`, with a
 * friendlier label for the compression suffixes (`backup.tar.gz` → `ZIP`).
 * Returns `fallback` when there's no extension; `maxLen` caps the chip width.
 */
export function fileExtension(name: string, opts?: {fallback?: string; maxLen?: number}): string {
  const fallback = opts?.fallback ?? 'File';
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return fallback;
  const raw = name.slice(dot + 1);
  const ext = EXTENSION_LABELS[raw.toLowerCase()] ?? raw.toUpperCase();
  return opts?.maxLen ? ext.slice(0, opts.maxLen) : ext;
}

export type BreadcrumbItem = {
  label: string;
  prefix: string | undefined;
};

/**
 * The crumb trail from the space root down to `prefix`, clamped so nothing above the
 * root is ever shown — the raw root segment is a username, and `rootLabel` stands in
 * for it. Two components had written this out: the browser and the destination picker,
 * whose copy silently lacked the unclamped branch.
 *
 * A crumb's `prefix` is `undefined` only in the unclamped (dev-unauth) case, where the
 * root crumb is "Home" and navigating to it means "no prefix at all".
 */
export function buildBreadcrumbs(prefix: string | undefined, rootPrefix: string, rootLabel?: string): BreadcrumbItem[] {
  if (!rootPrefix) {
    // No root clamping — standard Home-rooted breadcrumb
    const crumbs: BreadcrumbItem[] = [{label: 'Home', prefix: undefined}];
    if (!prefix) return crumbs;

    const parts = prefix.split('/').filter(Boolean);
    parts.forEach((part, i) => {
      crumbs.push({
        label: part,
        prefix: parts.slice(0, i + 1).join('/') + '/'
      });
    });

    return crumbs;
  }

  // Root-clamped breadcrumb: show only segments at or below rootPrefix. The root
  // crumb uses rootLabel when provided (so the raw prefix segment — e.g. the
  // username — is never shown), otherwise the last path segment.
  const rootParts = rootPrefix.split('/').filter(Boolean);
  const label = rootLabel ?? rootParts[rootParts.length - 1] ?? rootPrefix;
  const crumbs: BreadcrumbItem[] = [{label, prefix: rootPrefix}];

  if (!prefix || prefix === rootPrefix) return crumbs;

  const allParts = prefix.split('/').filter(Boolean);
  const subParts = allParts.slice(rootParts.length);
  subParts.forEach((part, i) => {
    crumbs.push({
      label: part,
      prefix: [...rootParts, ...subParts.slice(0, i + 1)].join('/') + '/'
    });
  });

  return crumbs;
}
