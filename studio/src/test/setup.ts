import "@testing-library/jest-dom/vitest";

// React Flow and Recharts need these browser APIs, which jsdom lacks.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as any).ResizeObserver ??= RO;
(globalThis as any).DOMMatrixReadOnly ??= class {
  m22 = 1;
  constructor() {}
};
