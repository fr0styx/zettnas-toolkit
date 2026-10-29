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
      exclude: ['frontend/src/__tests__/**'],
      // OPS-16, ARC-26: floors a little under today's numbers (62.7 / 60.3 / 53.9 / 49.4 on 29 Oct
      // 2026); raise them as coverage grows, towards 70 lines and 60 branches
      thresholds: { lines: 62, statements: 60, functions: 53, branches: 49 },
    },
  },
});
