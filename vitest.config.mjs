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
      // OPS-16: floors a little under today's numbers; raise them as coverage grows
      thresholds: { lines: 58, statements: 56, functions: 48, branches: 44 },
    },
  },
});
