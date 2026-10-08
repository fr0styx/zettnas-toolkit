import { defineConfig } from 'vite';

export default defineConfig({
  root: 'frontend',
  build: {
    outDir: '../static',
    emptyOutDir: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/chart.js')) {
            return 'vendor-chartjs';
          }
          if (id.includes('node_modules/hammerjs') || id.includes('chartjs-plugin-zoom')) {
            return 'vendor-zoom';
          }
        },
      },
    },
  },
});
