import { defineConfig } from 'vite';
import { iconsAtBuildTime } from './frontend/scripts/icons-build.mjs';

// HTML comments are notes for us, not bytes for the browser (FE-01 first-load budget); stripped
// until none is left, since one pass over "<!<!-- -->-- -->" would leave a "<!--" behind
export const withoutComments = (html) => {
  let prev;
  do {
    prev = html;
    html = html.replace(/<!--(?!\[if)[\s\S]*?-->\n?/g, '');
  } while (html !== prev);
  return html;
};
export const stripHtmlComments = () => ({
  name: 'zn-strip-html-comments',
  transformIndexHtml: { order: 'post', handler: (html) => withoutComments(html) },
});

export default defineConfig({
  root: 'frontend',
  // emoji in index.html and the window templates become icons at build time (PERF-8)
  plugins: [iconsAtBuildTime(), stripHtmlComments()],
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
