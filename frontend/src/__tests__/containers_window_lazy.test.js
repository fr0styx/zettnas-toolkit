import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';

const main = readFileSync(path.resolve(__dirname, '../main.js'), 'utf8');

describe('containers window loads on first use (PERF-5)', () => {
  it('is not imported with the page', () => {
    expect(main).not.toMatch(/^import .*containers-manager\.js/m);
  });

  it('is registered as a lazy window that opens from its icon and globals', () => {
    const block = main.slice(main.indexOf("id: 'containers'") - 40, main.indexOf("id: 'containers'") + 400);
    expect(block).toContain("load: () => import('./components/containers-manager.js')");
    expect(block).toContain("init: 'initContainersManager'");
    expect(block).toContain("iconId: 'containers-desktop-icon'");
    expect(block).toContain("globals: ['openContainersManager', 'openContainersWindow']");
  });
});
