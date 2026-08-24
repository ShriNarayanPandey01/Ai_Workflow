import "@testing-library/jest-dom/vitest"

Object.defineProperty(globalThis, "crypto", {
  value: {
    randomUUID: () => "11111111-1111-4111-8111-111111111111",
  },
})
