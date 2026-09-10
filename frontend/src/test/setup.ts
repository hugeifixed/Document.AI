import "@testing-library/jest-dom/vitest";

// jsdom has no media-query engine; browser checks cover live theme and viewport changes.
vi.stubGlobal("matchMedia", (query: string) => ({
  matches: false, media: query, onchange: null,
  addListener: vi.fn(), removeListener: vi.fn(),
  addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
}));

// Node's experimental localStorage can shadow jsdom's browser storage.
const stored = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (key: string) => stored.get(key) ?? null,
  setItem: (key: string, value: string) => { stored.set(key, String(value)); },
  removeItem: (key: string) => { stored.delete(key); },
  clear: () => stored.clear(),
  key: (index: number) => [...stored.keys()][index] ?? null,
  get length() { return stored.size; },
} satisfies Storage);
