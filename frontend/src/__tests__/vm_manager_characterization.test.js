// ARC-5: the VM manager keeps its exports, console helpers and rendered dialogs while the
// 6,400-line module is split up. The snapshots in __snapshots__/vm-manager/ were recorded
// before the split; update them only for an intended change (npx vitest run -u <this file>).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const FIXTURES = vi.hoisted(() => ({
  vms: [
    { id: 'vm-1', name: 'Ubuntu Server', state: 'running', vcpus: 4, memory_mb: 8192, disk_gb: 64, os: 'linux', vnc_port: 5901, autostart: true, vtpm: false, cpu_pct: 12.5, mem_used_mb: 2048 },
    { id: 'vm-2', name: 'Windows 11', state: 'stopped', vcpus: 8, memory_mb: 16384, disk_gb: 128, os: 'windows', vnc_port: null, autostart: false, vtpm: true, cpu_pct: 0, mem_used_mb: 0 },
  ],
  telemetry: { kvm_available: true, cpu_model: 'Intel N100', host_vcpus: 4, host_mem_mb: 16384, allocated_vcpus: 12, allocated_mem_mb: 24576, running: 1, total: 2 },
  isos: [{ name: 'ubuntu-24.04.iso', size: 2600000000 }, { name: 'win11.iso', size: 5800000000 }],
  bridges: ['br0', 'virbr0'],
  snapshots: [{ name: 'clean', date: '2026-10-19 12:00:00', size_formatted: '512 MB', is_live: false, description: 'Baseline' }],
  kvm: { kvm_available: true, nested: false, iommu: true, vfio: true, checks: [{ name: 'kvm', ok: true, detail: '/dev/kvm present' }] },
}));

vi.mock('../api.js', () => {
  const route = (url) => {
    if (url.includes('snapshot')) return { snapshots: FIXTURES.snapshots };
    if (url.includes('iso')) return { isos: FIXTURES.isos, files: FIXTURES.isos };
    if (url.includes('bridge') || url.includes('network')) return { bridges: FIXTURES.bridges };
    if (url.includes('kvm') || url.includes('diagnos')) return FIXTURES.kvm;
    if (url.includes('telemetry') || url.includes('host')) return FIXTURES.telemetry;
    if (url.includes('/vms')) return { vms: FIXTURES.vms, telemetry: FIXTURES.telemetry };
    return {};
  };
  const api = {
    get: vi.fn(async (url) => JSON.parse(JSON.stringify(route(url)))),
    post: vi.fn(async () => ({ status: 'ok' })),
    put: vi.fn(async () => ({ status: 'ok' })),
    delete: vi.fn(async () => ({ status: 'ok' })),
  };
  return { api, default: api, auth: { getToken: vi.fn(() => 'test-token') } };
});
vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
vi.mock('../components/dock.js', () => ({ makeDraggable: vi.fn(), bringToFront: vi.fn() }));
vi.mock('../components/terminal-view.js', () => ({
  createTerminalView: vi.fn(() => ({ write: vi.fn(), clear: vi.fn(), dispose: vi.fn(), element: document.createElement('div') })),
}));

import * as vm from '../components/vm-manager.js';

const SNAP = './__snapshots__/vm-manager';

async function settle() {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
}

function normalise(html) {
  return html
    .replace(/\b1[6-9]\d{11}\b/g, '<ts>') // epoch milliseconds
    .replace(/\b(\d{1,2}):(\d{2}):(\d{2})\b/g, '<time>')
    .replace(/(id|for|aria-labelledby|aria-controls)="([a-z-]*?)-[a-z0-9]{6,}"/gi, '$1="$2-<rand>"')
    .replace(/>\s+</g, '><');
}

describe('VM manager characterization (ARC-5)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers({ now: new Date('2026-10-26T12:00:00Z'), toFake: ['Date'] });
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('exports the same names', async () => {
    const surface = Object.keys(vm)
      .sort()
      .map((k) => `${k}: ${typeof vm[k]}${typeof vm[k] === 'function' ? `(${vm[k].length})` : ''}`);
    await expect(surface.join('\n') + '\n').toMatchFileSnapshot(`${SNAP}/exports.txt`);
  });

  it('console helpers give the same output', async () => {
    const ansi = [
      '\u001b[31mred\u001b[0m plain \u001b[1;32mbold green\u001b[0m',
      'tab\there <tag> & "quotes"',
      '\u001b[38;5;208morange\u001b[0m \u001b[4munderline\u001b[24m',
      'line1\r\nline2\u001b[2K\rover',
    ].map((s) => vm.formatAnsiToHtml(s));
    let buf = '';
    const stream = [];
    for (const chunk of ['hello ', 'world\r\n', '\u001b[2Jcleared', 'back\bspace', '\u0007bell']) {
      buf = vm.applyTerminalStream(buf, chunk);
      stream.push(buf);
    }
    const keys = [
      { key: 'a' }, { key: 'Enter' }, { key: 'Backspace' }, { key: 'Tab' }, { key: 'ArrowUp' },
      { key: 'c', ctrlKey: true }, { key: 'Escape' }, { key: 'F1' }, { key: 'Delete' },
    ].map((e) => vm.serialKeyToData({ preventDefault() {}, ...e }) ?? null);
    const out = { ansi, stream, keys, catalog: vm.OFFICIAL_ISO_CATALOG };
    await expect(JSON.stringify(out, null, 1) + '\n').toMatchFileSnapshot(`${SNAP}/console-helpers.json`);
  });

  it.each([
    ['qemu-error', () => vm.openQemuErrorModal('Ubuntu Server', 'qemu: could not open disk image', 'vm-1')],
    ['edit', () => vm.openVmEditModal('vm-1', FIXTURES.vms[0])],
    ['connect', () => vm.openVmConnectModal('vm-1', FIXTURES.vms[0])],
    ['kvm-diagnostics', () => vm.openKvmDiagnosticsModal(FIXTURES.kvm)],
    ['create', () => vm.openVmCreateModal()],
    ['iso-manager', () => vm.openIsoManagerModal('catalog')],
    ['snapshots', () => vm.openVmSnapshotsModal('vm-2', FIXTURES.vms[1])],
  ])('the %s dialog renders the same', async (name, open) => {
    try {
      await open();
    } catch (e) {
      document.body.insertAdjacentHTML('beforeend', `<pre data-threw>${e && e.name}</pre>`);
    }
    await settle();
    await expect(normalise(document.body.innerHTML) + '\n').toMatchFileSnapshot(`${SNAP}/${name}.html`);
  });
});
