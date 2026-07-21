/**
 * The last meaningful segment of an S3 key or folder prefix, for use as a short label.
 *
 * Trailing slashes are stripped first, so a folder prefix yields the folder's own name
 * rather than an empty string. A location that is nothing but slashes, or empty, falls
 * back to the original input so a label is never blank.
 *
 * @example
 * locationLabel('alice/data/sales/')    // 'sales'
 * locationLabel('alice/data/sales.csv') // 'sales.csv'
 */
export function locationLabel(location: string): string {
  const trimmed = location.replace(/\/+$/, '');
  return trimmed.slice(trimmed.lastIndexOf('/') + 1) || location;
}
