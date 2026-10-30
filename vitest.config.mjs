import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    pool: 'vmThreads',
    setupFiles: ['./frontend/src/__tests__/setup.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      include: ['frontend/src/**/*.js'],
      // locale data is loaded by tests but isn't code: counting it inflated the numbers (NARC-4)
      exclude: ['frontend/src/__tests__/**', 'frontend/src/locales/**'],
      // OPS-16, ARC-26: floors a little under today's numbers without locale data (63.8 / 61.4 / 55.4 /
      // 50.6 on 30 Oct 2026, NARC-4); raise them as coverage grows, towards 70 lines and 60 branches
      thresholds: { lines: 63, statements: 61, functions: 55, branches: 50 },
    },
  },
});
