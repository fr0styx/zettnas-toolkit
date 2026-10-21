import { defineConfig } from 'vite';

export default defineConfig({
  root: 'frontend',
  build: {
    outDir: '../static',
    emptyOutDir: false,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/@novnc/novnc')) {
            return 'vendor-novnc';
          }
          if (id.includes('node_modules/chart.js')) {
            return 'vendor-chartjs';
          }
          if (id.includes('node_modules/hammerjs') || id.includes('chartjs-plugin-zoom')) {
            return 'vendor-zoom';
          }
          if (id.includes('node_modules/qrcode')) {
            return 'vendor-qrcode';
          }
          if (id.includes('frontend/src/i18n.js')) {
            return 'app-i18n';
          }
        },
      },
    },
  },
});
