// Node's experimental `localStorage` (--localstorage-file) shadows jsdom's and is
// non-functional in this runner, so tests that touch localStorage install a fresh
// in-memory Storage. Used by test-setup (a baseline install) and by prefs specs that
// stub a clean store per test (e.g. useRailCollapsed / CollapsibleRail, SPEC-085).

class MemoryStorage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null;
  }
}

/** A fresh, working in-memory `Storage` (typed as the DOM `Storage`). */
export function memoryStorage(): Storage {
  return new MemoryStorage() as unknown as Storage;
}
