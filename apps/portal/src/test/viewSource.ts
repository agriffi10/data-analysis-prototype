/**
 * The wrappers an area view puts around its page, read from the view module's source, outermost
 * first.
 *
 * Read from the source because what is checked is the ORDER of the composition: `FeatureRoute`
 * outside the boundary, so a disabled feature never starts its chunk, and the boundary outside the
 * `Suspense`, which has no error path of its own. Fails loudly when the block is not found, so a
 * renamed page or a reformat cannot quietly stop the check.
 *
 * @param source - The view module's source.
 * @param page - The page component's name, as rendered (`QueryPage`).
 * @returns The wrapper names, outermost first.
 */
export function wrappersOf(source: string, page: string): string[] {
  const block = new RegExp(`<FeatureRoute\\b[\\s\\S]*?<${page} />`).exec(source);
  if (!block) throw new Error(`no view block around <${page} /> was found`);
  return [...block[0].matchAll(/<(FeatureRoute|ErrorBoundary|Suspense)\b/g)].map((match) => match[1]);
}
